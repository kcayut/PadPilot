#!/usr/bin/env python3
"""Install/remove only this checkout's app and integrations. User data is preserved."""
import argparse
import copy
import fcntl
import json
import os
import plistlib
import re
import signal
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from build_app import ROOT, build
from core.autostart import daemon_pids, job_loaded, service_command
from core.config import APP_SUPPORT_DIR, FALLBACK_CONFIG_FILE, load_config, save_config
from core.settings import apply_change
from core.storage import private_directory, state_file_exists
from core.runtime import app_runtime, bundled_app


def owned_app(app, root=None):
    try:
        return app_runtime(app)[0] == (root or ROOT)
    except (OSError, ValueError, KeyError):
        return False


def trash(path):
    """Recoverable removal, only called for explicit validated PadPilot targets."""
    location = Path.home() / '.Trash'
    location.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='PadPilot-', dir=location))
    destination = folder / path.name
    shutil.move(str(path), str(destination))
    print(f'Moved to Trash: {destination}')
    return destination


def stop_menu_apps(apps=None):
    explicit = apps is not None
    for app in apps if explicit else (bundled_app() or Path.home() / 'Applications/PadPilot.app', ROOT / 'build/PadPilot.app'):
        if not owned_app(app, app_runtime(app)[0] if explicit else ROOT):
            continue
        # CLI wrappers may be running this very installer/uninstaller.
        executable = str(app / 'Contents/MacOS/PadPilot')
        pattern = '^' + re.escape(executable) + r'( |$)'
        for attempt in range(30):
            result = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True, check=False)
            if result.returncode == 1:
                break
            if result.returncode != 0:
                raise RuntimeError('Unable to verify running PadPilot app')
            menu_pids = []
            for pid in map(int, result.stdout.split()):
                command = subprocess.run(['ps', '-ww', '-p', str(pid), '-o', 'args='],
                                         capture_output=True, text=True, timeout=2)
                if command.returncode:
                    continue
                if any(command.stdout.strip().startswith(executable + ' ' + flag)
                       for flag in ('--cli', '--bundled-cli', '--runtime-info', '--locate-betterdisplay', '--service', '--daemon')):
                    continue
                menu_pids.append(pid)
            if not menu_pids:
                break
            for pid in menu_pids:
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            time.sleep(0.1)
        else:
            raise RuntimeError('PadPilot app is still running; close it and retry.')


def ensure_settings_closed():
    # Closing the native window does not cancel an already submitted CLI write.
    pattern = (r'(^| )' + re.escape(str(ROOT / 'bin/padpilot-cli'))
               + r' (gui|open-log|change-settings|set-mode|set-language|autostart|action|pair|set-ipad|select-ipad)( |$)')
    result = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        raise RuntimeError('請等待 PadPilot 操作完成、儲存並關閉設定／診斷視窗，再重試。 / Wait for PadPilot operations to finish, then close settings windows and retry.')
    if result.returncode != 1:
        raise RuntimeError('Cannot check open settings windows; no installation changes made.')
    for support in (Path.home() / 'Library/Application Support/PadPilot', FALLBACK_CONFIG_FILE.parent):
        path = support / 'runtime/settings-window.lock'
        try:
            for directory in (support, path.parent):
                info = directory.lstat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise RuntimeError(f'Refusing unsafe settings window directory: {directory}')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            continue
        except OSError as error:
            raise RuntimeError(f'Cannot safely check settings window lock: {path}') from error
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                raise RuntimeError(f'Refusing unsafe settings window lock: {path}')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('請先儲存並關閉 PadPilot 設定／診斷視窗，再重試。 / Close PadPilot settings windows and retry.') from error
        finally:
            os.close(fd)


def installation_service(app):
    """Inspect before stopping anything; this pre-release has no legacy migration."""
    legacy = Path.home() / 'Library/LaunchAgents/com.padpilot.daemon.plist'
    if legacy.exists() or legacy.is_symlink():
        raise RuntimeError(f'Remove the old development LaunchAgent manually first: {legacy}')
    job_loaded(app / 'Contents/Library/LaunchAgents/com.padpilot.daemon.plist')
    return service_command(app=app) if app.exists() else 'notRegistered'


def manage(uninstall=False, purge=False, *, remove_config=False, remove_logs=False, betterdisplay_path=None):
    remove_config = remove_config or purge
    remove_logs = remove_logs or purge
    app = bundled_app() or Path.home() / 'Applications/PadPilot.app'
    if bundled_app() and not uninstall:
        raise RuntimeError('Use install_release.sh to update a bundled app')
    if (app.exists() or app.is_symlink()) and (app.is_symlink() or not owned_app(app)):
        raise RuntimeError(f'Refusing to replace/remove an app from another checkout: {app}')
    previous_service = installation_service(app)
    ensure_settings_closed()
    if not uninstall:
        cfg = load_config()  # Invalid configuration must fail before stopping anything.
        if betterdisplay_path is not None:
            candidate = copy.deepcopy(cfg)
            apply_change(candidate, 'set_betterdisplaycli_path', {'path': betterdisplay_path})
        build(ROOT / 'build/PadPilot.app')
        was_running = bool(daemon_pids())
    if remove_config:
        # Validate before any removal, including a fallback left by an earlier run.
        fallback_exists = state_file_exists(FALLBACK_CONFIG_FILE)
        if APP_SUPPORT_DIR.exists() or APP_SUPPORT_DIR.is_symlink():
            private_directory(APP_SUPPORT_DIR)
    log_dir = Path.home() / 'Library/Logs/PadPilot'
    if remove_logs and (log_dir.exists() or log_dir.is_symlink()):
        private_directory(log_dir)
    shortcut = Path.home() / 'bin/padpilot-cli'
    launcher = app / 'Contents/Resources/padpilot-cli'
    if not uninstall:
        app.parent.mkdir(parents=True, exist_ok=True)
        previous_app = None
        replaced = False
        path_changed = False
        previous_python = sys.executable
        runtime = app / 'Contents/Resources/runtime.json'
        if runtime.is_file():
            previous_python = json.loads(runtime.read_text()).get('python', sys.executable)
        with tempfile.TemporaryDirectory(prefix='padpilot-install-', dir=app.parent) as directory:
            staging = Path(directory) / 'PadPilot.app'
            shutil.copytree(ROOT / 'build/PadPilot.app', staging)
            try:
                subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
                stop_menu_apps()
                if app.exists():
                    service_command('unregister', app)
                if betterdisplay_path is not None:
                    # Use the same validated offline settings transaction as the GUI/CLI.
                    path_changed = True
                    subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'),
                                    'change-settings', 'set_betterdisplaycli_path'],
                                   input=json.dumps({'path': betterdisplay_path}), text=True, check=True)
                if app.exists():
                    previous_app = trash(app)
                staging.rename(app)
                replaced = True
                if previous_service == 'enabled':
                    service_command('register', app)
                subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
            except Exception as error:
                try:
                    if replaced:
                        service_command('unregister', app)
                        subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
                        stop_menu_apps()
                        trash(app)
                    if previous_app is not None:
                        previous_app.rename(app)
                    if path_changed:
                        save_config(cfg)
                    if previous_service == 'enabled':
                        service_command('register', app)
                    if was_running:
                        subprocess.run([previous_python, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
                    elif previous_service == 'enabled':
                        subprocess.run([previous_python, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
                except Exception as restore_error:
                    raise RuntimeError(f'Installation failed: {error}. Rollback incomplete: {restore_error}') from error
                raise RuntimeError(f'Installation failed: {error}. Previous app and service state restored.') from error
        try:
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            if not (shortcut.exists() or shortcut.is_symlink()):
                shortcut.symlink_to(launcher)
            elif not (shortcut.is_symlink() and shortcut.resolve() == launcher.resolve()):
                print(f'Existing CLI shortcut preserved: {shortcut}; use {launcher}')
        except OSError as error:
            print(f'App installed; optional CLI shortcut unavailable ({error}). Use: {launcher}')
        print(f'Installed: {app}\nPython: {sys.executable}\nKeep source folder: {ROOT}\nCLI: {launcher}')
        if service_command(app=app) == 'enabled':
            print('登入自動啟動已啟用。 / Login startup enabled.')
        else:
            print('登入自動啟動尚未啟用；請查看系統登入項目。 / Login startup is off or awaiting approval; check System Settings.')
        return
    # Shared CLI verifies launchd and exact daemon PIDs before removing snapshots.
    subprocess.run([sys.executable] + (['-I', '-B'] if bundled_app() else [])
                   + [str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
    stop_menu_apps()
    if uninstall:
        if app.exists():
            service_command('unregister', app)
            trash(app)
        if shortcut.is_symlink() and shortcut.resolve() == launcher.resolve():
            trash(shortcut)
        if remove_config:
            if fallback_exists and FALLBACK_CONFIG_FILE.parent != APP_SUPPORT_DIR:
                trash(FALLBACK_CONFIG_FILE)
            if APP_SUPPORT_DIR.exists():
                trash(APP_SUPPORT_DIR)
        if remove_logs and log_dir.exists():
            trash(log_dir)
        print('Uninstalled. Source, BetterDisplay and virtual displays were preserved.')
        return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--purge', action='store_true', help='Move configuration and logs to Trash during uninstall')
    parser.add_argument('--remove-config', action='store_true')
    parser.add_argument('--remove-logs', action='store_true')
    parser.add_argument('--betterdisplay-path', help='Save the selected BetterDisplay app or CLI path')
    args = parser.parse_args()
    if (args.purge or args.remove_config or args.remove_logs) and not args.uninstall:
        parser.error('Removal options require --uninstall')
    if args.betterdisplay_path is not None and args.uninstall:
        parser.error('--betterdisplay-path cannot be used with --uninstall')
    try:
        manage(args.uninstall, args.purge, remove_config=args.remove_config,
               remove_logs=args.remove_logs, betterdisplay_path=args.betterdisplay_path)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Setup failed: {error}\n')
