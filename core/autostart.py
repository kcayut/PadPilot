"""LaunchAgent autostart manager for PadPilot daemon."""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from core.config import APP_SUPPORT_DIR, load_config, save_config
from core.logger import get_logger

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

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.padpilot.daemon</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py}</string>
        <string>{daemon_bin}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
    <key>StandardOutPath</key>
    <string>{stdout_log}</string>
    <key>StandardErrorPath</key>
    <string>{stderr_log}</string>
</dict>
</plist>
"""


def daemon_pids() -> list[int]:
    # Match this checkout's full script path, never unrelated Python processes.
    pattern = r"(^| )" + re.escape(str(PROJECT_ROOT / "bin" / "padpilotd")) + r"( |$)"
    result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True, timeout=2)
    if result.returncode not in (0, 1):
        raise RuntimeError("無法確認背景服務程序，未隱藏選單。" + result.stderr)
    return [int(pid) for pid in result.stdout.split()]


def is_daemon_running() -> bool:
    """Check if the background daemon is actively responding on its Unix socket."""
    if not SOCKET_PATH.exists():
        return False
    s = None
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(SOCKET_PATH))
        s.sendall(b"status\n")
        resp = s.recv(256).decode("utf-8")
        return "OK" in resp
    except Exception:
        return False
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def is_autostart_enabled(plist_path: Optional[Path] = None) -> bool:
    """Check whether LaunchAgent autostart on login is enabled."""
    target_plist = plist_path or get_launch_agent_plist_path()
    return target_plist.is_file()


def enable_autostart(
    plist_path: Optional[Path] = None,
    python_bin: Optional[str] = None,
    project_root: Optional[Path] = None,
    log_dir: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Enable daemon autostart on user login by writing and loading the LaunchAgent plist."""
    target_plist = plist_path or get_launch_agent_plist_path()
    try:
        target_plist.parent.mkdir(parents=True, exist_ok=True)
        content = generate_plist_content(
            python_bin=python_bin,
            project_root=project_root,
            log_dir=log_dir,
        )
        with open(target_plist, "w", encoding="utf-8") as f:
            f.write(content)

        # Update config
        cfg = load_config()
        cfg.autostart_on_login = True
        save_config(cfg)

        # Stop any standalone process before loading launchd job
        if is_daemon_running():
            subprocess.run(["pkill", "-f", "bin/padpilotd"], capture_output=True, check=False)
            time.sleep(0.5)

        # Load with launchctl
        subprocess.run(["launchctl", "unload", str(target_plist)], capture_output=True, check=False)
        res = subprocess.run(["launchctl", "load", str(target_plist)], capture_output=True, text=True, check=False)
        if res.returncode != 0 and "service already loaded" not in res.stderr.lower():
            raise RuntimeError(f"登入設定已寫入，但背景服務啟動失敗：{res.stderr.strip()}")

        # Trigger SwiftBar refresh
        notify_swiftbar(cfg.swiftbar_plugin_id)

        msg = "✓ PadPilot daemon will automatically run at login."
        logger.info(msg)
        return True, msg
    except Exception as e:
        err_msg = f"Failed to enable autostart: {e}"
        logger.error(err_msg)
        return False, err_msg


def disable_autostart(
    plist_path: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Disable daemon autostart on user login by unloading and removing the LaunchAgent plist."""
    target_plist = plist_path or get_launch_agent_plist_path()
    try:
        was_running = is_daemon_running()

        if target_plist.is_file():
            subprocess.run(["launchctl", "unload", str(target_plist)], capture_output=True, check=False)
            target_plist.unlink()

        # Update config
        cfg = load_config()
        cfg.autostart_on_login = False
        save_config(cfg)

        # If daemon was running, preserve the current session by launching a standalone process
        if was_running:
            time.sleep(0.5)
            daemon_bin = PROJECT_ROOT / "bin" / "padpilotd"
            subprocess.Popen(
                [sys.executable, str(daemon_bin)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("Preserved current session by restarting daemon as standalone process")

        # Trigger SwiftBar refresh
        notify_swiftbar(cfg.swiftbar_plugin_id)

        msg = "✓ PadPilot daemon autostart at login has been disabled."
        logger.info(msg)
        return True, msg
    except Exception as e:
        err_msg = f"Failed to disable autostart: {e}"
        logger.error(err_msg)
        return False, err_msg


def toggle_autostart(plist_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Toggle autostart between enabled and disabled."""
    if is_autostart_enabled(plist_path):
        return disable_autostart(plist_path)
    else:
        return enable_autostart(plist_path)


def is_swiftbar_recovery_bug_present() -> bool:
    """Check if environment has macOS >= 26 and SwiftBar <= 2.1.1 which triggers the recovery popup on URL open."""
    try:
        import platform
        mac_ver = platform.mac_ver()[0]
        if not mac_ver:
            return False
        major = int(mac_ver.split(".")[0])
        if major < 26:
            return False

        info_plist = Path("/Applications/SwiftBar.app/Contents/Info.plist")
        if not info_plist.exists():
            return False

        import plistlib
        with open(info_plist, "rb") as f:
            data = plistlib.load(f)
        ver_str = data.get("CFBundleShortVersionString", "")
        parts = [int(p) for p in ver_str.split(".") if p.isdigit()]
        if len(parts) >= 2 and parts[:2] == [2, 1] and (len(parts) < 3 or parts[2] <= 1):
            return True
        return False
    except Exception:
        return False


_notify_lock = threading.Lock()
_notify_timer: Optional[threading.Timer] = None


def _fire_swiftbar_notification() -> None:
    global _notify_timer
    with _notify_lock:
        _notify_timer = None
    try:
        subprocess.Popen(
            ["open", "-g", "swiftbar://refreshallplugins"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.warning(f"SwiftBar refresh notification failed: {e}")


def notify_swiftbar(plugin_id: str = "", delay: float = 0.1) -> None:
    """Trigger thread-safe debounced non-blocking SwiftBar UI refresh via URL scheme.

    100ms debounce ensures rapid transitions or mutations in the process (e.g. config update -> evaluation -> export)
    coalesce into a single URL event, preventing duplicate execution or menu flicker.
    Uses subprocess.Popen to guarantee the state engine and caller threads are never blocked.
    """
    global _notify_timer
    with _notify_lock:
        if _notify_timer is not None:
            _notify_timer.cancel()
            _notify_timer = None

        if delay > 0:
            _notify_timer = threading.Timer(delay, _fire_swiftbar_notification)
            _notify_timer.daemon = True
            _notify_timer.start()

    if delay <= 0:
        _fire_swiftbar_notification()

