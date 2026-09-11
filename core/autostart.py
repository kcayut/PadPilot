"""LaunchAgent autostart manager for PadPilot daemon."""

from __future__ import annotations

import copy
import json
import os
import plistlib
import re
import signal
import shutil
import socket
import subprocess
import sys
import time
import threading
from pathlib import Path
from typing import Optional, Tuple

from core.config import APP_SUPPORT_DIR, load_config, save_config
from core.logger import get_logger
from core.storage import atomic_write, private_directory, private_file

logger = get_logger("Autostart")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLIST_FILENAME = "com.padpilot.daemon.plist"
USER_LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
SOCKET_PATH = APP_SUPPORT_DIR / "padpilot.sock"


def get_launch_agent_plist_path() -> Path:
    return USER_LAUNCH_AGENTS_DIR / PLIST_FILENAME


def generate_plist_content(
    python_bin: Optional[str] = None,
    project_root: Optional[Path] = None,
    log_dir: Optional[Path] = None,
) -> str:
    py = python_bin or sys.executable
    root = project_root or PROJECT_ROOT
    logs = log_dir or (Path.home() / "Library" / "Logs" / "PadPilot")
    daemon_bin = root / "bin" / "padpilotd"
    stdout_log = logs / "launchd.stdout.log"
    stderr_log = logs / "launchd.stderr.log"

    return plistlib.dumps({
        "Label": "com.padpilot.daemon",
        "ProgramArguments": [py, str(daemon_bin)],
        "RunAtLoad": True, "KeepAlive": True, "Umask": 0o077,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "StandardOutPath": str(stdout_log), "StandardErrorPath": str(stderr_log),
    }).decode("utf-8")


def daemon_pids() -> list[int]:
    # pgrep only selects candidates; verify the executable and script position.
    script = str(PROJECT_ROOT / "bin" / "padpilotd")
    pattern = r"(^| )" + re.escape(script) + r"( |$)"
    result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=2)
    if result.returncode not in (0, 1):
        raise RuntimeError("Could not verify daemon processes")
    verified = []
    for pid in map(int, result.stdout.split()):
        executable = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                                    capture_output=True, text=True, timeout=2)
        command = subprocess.run(["ps", "-ww", "-p", str(pid), "-o", "args="],
                                 capture_output=True, text=True, timeout=2)
        if executable.returncode or command.returncode:
            continue  # Process exited during inspection.
        exe = executable.stdout.strip()
        if not re.fullmatch(r"(?:python(?:[0-9.]+)?|pypy[0-9]*)", Path(exe).name.lower()):
            continue
        args = command.stdout.strip()
        prefix, separator, suffix = args.partition(script)
        interpreter = re.sub(r"(?:\s+-(?:u|B|I|E))*\s+$", "", prefix)
        interpreter_path = shutil.which(interpreter) or interpreter
        if (separator and (not suffix or suffix.startswith(' '))
                and Path(interpreter_path).resolve() == Path(exe).resolve()):
            verified.append(pid)
    return verified


def is_daemon_running() -> bool:
    """Require a structured handshake from this checkout, not a stale status file."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(str(SOCKET_PATH))
            client.sendall(b'{"command":"status"}\n')
            with client.makefile('rb') as reader:
                response = json.loads(reader.read(4097).decode("utf-8"))
        return (response.get("ok") is True and response.get("project_root") == str(PROJECT_ROOT)
                and type(response.get("pid")) is int and response["pid"] > 0)
    except (OSError, ValueError, AttributeError):
        return False


def wait_for_daemon(timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not is_daemon_running():
        if time.monotonic() >= deadline:
            raise RuntimeError("Daemon handshake failed; check PadPilot logs. Startup was not verified.")
        time.sleep(0.2)


def validate_plist(path: Path) -> None:
    if not (path.exists() or path.is_symlink()):
        return
    private_file(path, harden=False)
    value = plistlib.loads(path.read_bytes())
    args = value.get("ProgramArguments")
    if (value.get("Label") != "com.padpilot.daemon" or not isinstance(args, list) or len(args) != 2
            or args[1] != str(PROJECT_ROOT / "bin/padpilotd")
            or not isinstance(args[0], str)
            or not re.fullmatch(r"(?:python(?:[0-9.]+)?|pypy[0-9]*)", Path(args[0]).name.lower())):
        raise RuntimeError(f"LaunchAgent belongs to another program or checkout: {path}")


def job_loaded(path: Path) -> bool:
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.padpilot.daemon"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode == 113:
        return False
    if result.returncode != 0:
        raise RuntimeError("Cannot inspect launchd job; refusing to stop an unverified service")
    validate_plist(path)
    value = plistlib.loads(path.read_bytes()) if path.exists() else {}
    source = re.search(r"(?m)^\s*path = (.+)$", result.stdout)
    arguments = re.search(r"(?ms)^\s*arguments = \{\n(.*?)^\s*\}", result.stdout)
    loaded_args = [line.strip().strip('"') for line in arguments[1].splitlines() if line.strip()] if arguments else []
    if (not source or source[1].strip().strip('"') != str(path)
            or loaded_args != value.get("ProgramArguments")):
        raise RuntimeError("Loaded LaunchAgent is not this checkout; refusing to modify it")
    return True


def stop_daemon(plist_path: Optional[Path] = None) -> None:
    path = plist_path or get_launch_agent_plist_path()
    validate_plist(path)
    if job_loaded(path):
        subprocess.run(["launchctl", "unload", str(path)], capture_output=True, check=True, timeout=10)
        if job_loaded(path):
            raise RuntimeError("LaunchAgent remains loaded; runtime state was preserved")
    for pid in daemon_pids():
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5
    while daemon_pids():
        if time.monotonic() >= deadline:
            raise RuntimeError("Daemon has not stopped; runtime state was preserved")
        time.sleep(0.1)


def start_standalone() -> None:
    process = subprocess.Popen([sys.executable, str(PROJECT_ROOT / "bin/padpilotd")],
                               start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_for_daemon()
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise
    threading.Thread(target=process.wait, daemon=True).start()


def is_autostart_enabled(plist_path: Optional[Path] = None) -> bool:
    """Check whether LaunchAgent autostart on login is enabled."""
    target_plist = plist_path or get_launch_agent_plist_path()
    return target_plist.is_file()


def enable_autostart(
    plist_path: Optional[Path] = None,
    python_bin: Optional[str] = None,
    project_root: Optional[Path] = None,
    log_dir: Optional[Path] = None,
    expected_revision: Optional[int] = None,
) -> Tuple[bool, str]:
    """One installation path for CLI, GUI and installer; roll back on failed startup."""
    target = plist_path or get_launch_agent_plist_path()
    previous = None
    before = None
    was_loaded = False
    was_running = False
    stopped = False
    changed = False
    try:
        if project_root is not None and project_root.resolve() != PROJECT_ROOT:
            raise RuntimeError("Cannot install a LaunchAgent for another checkout")
        validate_plist(target)
        was_loaded = job_loaded(target)
        was_running = is_daemon_running()
        previous = target.read_bytes() if target.exists() else None
        before = copy.deepcopy(load_config())
        if expected_revision is not None and before.revision != expected_revision:
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        logs = log_dir or Path.home() / "Library/Logs/PadPilot"
        private_directory(logs)
        for name in ("launchd.stdout.log", "launchd.stderr.log"):
            private_file(logs / name, create=True)
        stopped = True
        stop_daemon(target)
        # Re-read after stopping: a queued daemon edit must not be overwritten.
        current = load_config()
        if expected_revision is not None and current.revision != expected_revision:
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        before = copy.deepcopy(current)
        atomic_write(target, generate_plist_content(python_bin, project_root, log_dir).encode(),
                     private_parent=False)
        changed = True
        cfg = copy.deepcopy(before)
        if not cfg.autostart_on_login:
            cfg.autostart_on_login = True
            cfg.revision += 1
            cfg.updated_at = time.time()
            save_config(cfg)
        subprocess.run(["launchctl", "load", str(target)], capture_output=True, check=True, timeout=10)
        wait_for_daemon()
        return True, "✓ PadPilot login startup enabled; daemon handshake verified."
    except Exception as error:
        rollback = ""
        if stopped:
            try:
                if changed:
                    stop_daemon(target)
                    if previous is None:
                        target.unlink(missing_ok=True)
                    else:
                        atomic_write(target, previous, private_parent=False)
                    if before is not None:
                        save_config(before)
                if was_loaded:
                    if not job_loaded(target):
                        subprocess.run(["launchctl", "load", str(target)], capture_output=True, check=True, timeout=10)
                    wait_for_daemon()
                elif was_running and not is_daemon_running():
                    start_standalone()
                rollback = " Previous login configuration restored."
            except Exception as restore_error:
                rollback = f" Rollback incomplete: {restore_error}"
        message = f"Failed to enable autostart: {error}.{rollback}"
        logger.error(message)
        return False, message


def disable_autostart(plist_path: Optional[Path] = None, expected_revision: Optional[int] = None) -> Tuple[bool, str]:
    target = plist_path or get_launch_agent_plist_path()
    try:
        validate_plist(target)
        cfg = load_config()
        if expected_revision is not None and cfg.revision != expected_revision:
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        was_running = is_daemon_running()
        was_loaded = job_loaded(target)
        stop_daemon(target)
        cfg = load_config()
        if expected_revision is not None and cfg.revision != expected_revision:
            if was_loaded:
                subprocess.run(['launchctl', 'load', str(target)], capture_output=True, check=True, timeout=10)
                wait_for_daemon()
            elif was_running:
                start_standalone()
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        target.unlink(missing_ok=True)
        if cfg.autostart_on_login:
            cfg.autostart_on_login = False
            cfg.revision += 1
            cfg.updated_at = time.time()
            save_config(cfg)
        if was_running:
            start_standalone()
        return True, "✓ PadPilot login startup disabled; current session preserved."
    except Exception as error:
        message = f"Failed to disable autostart: {error}"
        logger.error(message)
        return False, message


def toggle_autostart(plist_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Toggle autostart between enabled and disabled."""
    if is_autostart_enabled(plist_path):
        return disable_autostart(plist_path)
    else:
        return enable_autostart(plist_path)



def find_menu_app(*, settings=False) -> Optional[Path]:
    """Resolve only an app built for this checkout."""
    for app in (Path.home() / "Applications" / "PadPilot.app", PROJECT_ROOT / "build" / "PadPilot.app"):
        try:
            with (app / "Contents" / "Resources" / "runtime.json").open() as stream:
                import json
                runtime = json.load(stream)
            if Path(runtime.get("project_root", "")).resolve() != PROJECT_ROOT:
                continue
            if settings:
                with (app / 'Contents/Info.plist').open('rb') as stream:
                    info = plistlib.load(stream)
                if not any('padpilot' in item.get('CFBundleURLSchemes', []) for item in info.get('CFBundleURLTypes', [])):
                    continue
            return app
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
    return None


def open_menu_app() -> bool:
    """Background menu startup does not open a settings window."""
    app = find_menu_app()
    if app is None:
        return False
    try:
        return subprocess.run(["open", "-g", str(app)], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
