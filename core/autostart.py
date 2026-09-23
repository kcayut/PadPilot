"""App-bundled SMAppService registration and current-session daemon control."""

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
from core.runtime import bundled_app, find_app, login_service_owner
from core.storage import atomic_write

logger = get_logger("Autostart")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLIST_FILENAME = "com.sidecarswitch.daemon.plist"
SOCKET_PATH = APP_SUPPORT_DIR / "sidecarswitch.sock"


def get_launch_agent_plist_path() -> Path:
    app = find_menu_app()
    if app is None:
        raise RuntimeError("Build/install SidecarSwitch.app before managing login startup")
    return app / "Contents/Library/LaunchAgents" / PLIST_FILENAME


def generate_plist_content() -> str:
    return plistlib.dumps({
        "Label": "com.sidecarswitch.daemon",
        "BundleProgram": "Contents/MacOS/SidecarSwitch",
        "ProgramArguments": ["SidecarSwitch", "--daemon"],
        "RunAtLoad": True,
        # Normal Exit stops this session; crashes restart, next login still launches.
        "KeepAlive": {"SuccessfulExit": False}, "Umask": 0o077,
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
    }).decode("utf-8")


def service_owner():
    return login_service_owner(APP_SUPPORT_DIR)


def service_owner_matches(app: Path) -> bool:
    owner = service_owner()
    # A moved app leaves a stale receipt. Never take over an existing copy.
    return owner == app.resolve() or (owner is not None and not owner.exists() and not owner.is_symlink())


def service_command(action="status", app=None) -> str:
    app = app or find_menu_app()
    if app is None:
        raise RuntimeError("Build/install SidecarSwitch.app before managing login startup")
    plist = app / "Contents/Library/LaunchAgents" / PLIST_FILENAME
    if not plist.is_file():
        raise RuntimeError("App has no bundled login service; rebuild/install the new version")
    validate_plist(plist)

    def invoke(command):
        result = subprocess.run([str(app / "Contents/MacOS/SidecarSwitch"), "--service", command],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Cannot manage SidecarSwitch login service")
        state = result.stdout.strip()
        if state not in {"enabled", "notRegistered", "requiresApproval", "notFound"}:
            raise RuntimeError("Unknown SidecarSwitch login service status")
        return state

    state = invoke("status")
    # SMAppService status is shared by copies with the same bundle ID; it does not
    # identify which copy owns the registration. Keep one private ownership receipt.
    if state in {"enabled", "requiresApproval"} and not service_owner_matches(app):
        raise RuntimeError("Login service belongs to another installation; remove that installation first")
    if action == "status":
        return state
    if action == "register":
        atomic_write(APP_SUPPORT_DIR / "login-service.json", json.dumps({"app": str(app.resolve())}).encode())
    result = invoke(action)
    if action == "unregister" and result not in {"notRegistered", "notFound"}:
        raise RuntimeError("Login service removal was not confirmed; app was preserved")
    return result


def autostart_status() -> str:
    try:
        return service_command()
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return "unknown"


def daemon_pids(project_root: Optional[Path] = None) -> list[int]:
    # pgrep only selects candidates; verify the executable and script position.
    script = str((project_root or PROJECT_ROOT) / "bin" / "sidecarswitchd")
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
            raise RuntimeError("Daemon handshake failed; check SidecarSwitch logs. Startup was not verified.")
        time.sleep(0.2)


def validate_plist(path: Path) -> None:
    if path.is_symlink() or plistlib.loads(path.read_bytes()) != plistlib.loads(generate_plist_content().encode()):
        raise RuntimeError(f"Not a SidecarSwitch bundled LaunchAgent: {path}")


def job_loaded(path: Optional[Path] = None) -> bool:
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/com.sidecarswitch.daemon"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode == 113:
        return False
    if result.returncode != 0:
        raise RuntimeError("Cannot inspect launchd job; refusing to stop an unverified service")
    path = path or get_launch_agent_plist_path()
    validate_plist(path)
    app = path.parents[3].resolve()
    managed = re.search(r"(?m)^\s*managed_by = com\.apple\.xpc\.ServiceManagement$", result.stdout)
    parent = re.search(r"(?m)^\s*parent bundle identifier = com\.sidecarswitch\.app$", result.stdout)
    program = re.search(r"(?m)^\s*program identifier = Contents/MacOS/SidecarSwitch \(mode: 2\)$", result.stdout)
    if not (managed and parent and program) or not service_owner_matches(app):
        raise RuntimeError("Loaded LaunchAgent belongs to another installation; remove that installation first")
    return True


def stop_daemon() -> None:
    # Check ownership, but keep the registration for the next login.
    job_loaded()
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


def start_registered() -> None:
    if not job_loaded():
        raise RuntimeError("Login service is not loaded; check System Settings > General > Login Items")
    if service_command("register") != "enabled":
        raise RuntimeError("Allow SidecarSwitch in System Settings > General > Login Items")
    wait_for_daemon()


def start_standalone() -> None:
    process = subprocess.Popen([sys.executable] + (['-I', '-B'] if bundled_app(PROJECT_ROOT) else []) + [str(PROJECT_ROOT / "bin/sidecarswitchd")],
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


def is_autostart_enabled() -> bool:
    return autostart_status() == "enabled"


def set_autostart(enabled: bool, expected_revision: Optional[int] = None, *, connect_on_boot: Optional[bool] = None) -> Tuple[bool, str]:
    before = None
    saved = stopped = changed = False
    previous = "notRegistered"
    was_running = False
    try:
        if type(enabled) is not bool or (connect_on_boot is not None and type(connect_on_boot) is not bool):
            raise ValueError('請提供布林值 enabled')
        if connect_on_boot and not enabled:
            raise ValueError('開機連線需要啟用登入時自動啟動')
        cfg = load_config()
        if expected_revision is not None and cfg.revision != expected_revision:
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        previous = service_command()
        was_running = is_daemon_running()
        stop_daemon()
        stopped = True
        cfg = load_config()
        if expected_revision is not None and cfg.revision != expected_revision:
            raise RuntimeError('CONFIG_CONFLICT: settings changed; refresh before retrying')
        before = copy.deepcopy(cfg)
        boot = (cfg.connect_on_boot if connect_on_boot is None else connect_on_boot) if enabled else False
        if cfg.autostart_on_login != enabled or cfg.connect_on_boot != boot or not cfg.login_service_initialized:
            cfg.autostart_on_login = enabled
            cfg.connect_on_boot = boot
            cfg.login_service_initialized = True
            cfg.revision += 1
            cfg.updated_at = time.time()
            save_config(cfg)
            saved = True
        changed = True
        state = service_command("register" if enabled else "unregister")
        if connect_on_boot and state != "enabled":
            raise RuntimeError('請先到系統設定 → 一般 → 登入項目允許 SidecarSwitch 背景執行，再啟用開機連線。')
        if enabled and state not in {"enabled", "requiresApproval"}:
            raise RuntimeError("Login service registration was not confirmed")
        if not enabled and state not in {"notRegistered", "notFound"}:
            raise RuntimeError("Login service removal was not confirmed")
        if enabled and state == "enabled":
            wait_for_daemon()
        elif was_running or enabled:
            start_standalone()
        if state == "requiresApproval":
            return True, "SidecarSwitch: 請到系統設定 → 一般 → 登入項目允許背景執行。 / Allow SidecarSwitch in System Settings > General > Login Items. / システム設定 → 一般 → ログイン項目で SidecarSwitch を許可してください。"
        return True, "✓ SidecarSwitch login startup " + ("enabled." if enabled else "disabled; current session preserved.")
    except Exception as error:
        rollback = ""
        if stopped:
            try:
                if changed:
                    # Unregister before reverting config, so no daemon writes race the restore.
                    service_command("unregister")
                if saved:
                    save_config(before)
                if changed and previous in {"enabled", "requiresApproval"}:
                    service_command("register")
                if was_running:
                    if previous == "enabled":
                        start_registered()
                    elif not is_daemon_running():
                        start_standalone()
                elif changed and previous == "enabled":
                    stop_daemon()
                rollback = " Previous preferences restored."
            except Exception as restore_error:
                rollback = f" Rollback incomplete: {restore_error}"
        message = f"Failed to change login startup: {error}.{rollback}"
        logger.error(message)
        return False, message


def enable_autostart(expected_revision: Optional[int] = None) -> Tuple[bool, str]:
    return set_autostart(True, expected_revision)


def disable_autostart(expected_revision: Optional[int] = None) -> Tuple[bool, str]:
    return set_autostart(False, expected_revision)


def toggle_autostart(expected_revision: Optional[int] = None) -> Tuple[bool, str]:
    state = service_command()
    # A pending/blocked registration can be explicitly disabled too.
    return set_autostart(state not in {"enabled", "requiresApproval"}, expected_revision)


def find_menu_app(*, settings=False) -> Optional[Path]:
    return find_app(PROJECT_ROOT, settings=settings, support_dir=APP_SUPPORT_DIR)


def open_menu_app() -> bool:
    """Background menu startup does not open a settings window."""
    app = find_menu_app()
    if app is None:
        return False
    try:
        # A URL delivery avoids the foreground reopen event if the app is already running.
        return subprocess.run(["open", "-g", "-a", str(app), "sidecarswitch://menu", "--args", "--menu-only"],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
