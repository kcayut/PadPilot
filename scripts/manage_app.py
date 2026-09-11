#!/usr/bin/env python3
"""Install/remove only this checkout's app and integrations. User data is preserved."""
import argparse
import copy
import json
import os
import plistlib
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from build_app import ROOT, build
from core.autostart import (daemon_pids, get_launch_agent_plist_path, job_loaded, start_standalone,
                            stop_daemon, validate_plist, wait_for_daemon)
from core.config import APP_SUPPORT_DIR, FALLBACK_CONFIG_FILE, load_config, save_config
from core.settings import apply_change
from core.storage import atomic_write, private_directory, state_file_exists


def owned_app(app):
    try:
        info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
        runtime = json.loads((app / 'Contents/Resources/runtime.json').read_text())
        return info.get('CFBundleIdentifier') == 'com.padpilot.app' and Path(runtime['project_root']).resolve() == ROOT
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


def retire_legacy_plugin():
    folders = {Path.home() / 'Library/Application Support/SwiftBar/plugins'}
    preferences = Path.home() / 'Library/Preferences/com.ameba.SwiftBar.plist'
    try:
        custom = plistlib.loads(preferences.read_bytes()).get('PluginDirectory')
        if isinstance(custom, str) and custom:
            folders.add(Path(custom).expanduser())
    except (OSError, ValueError):
        pass
    for folder in folders:
        plugin = folder / 'padpilot.30s.py'
        if plugin.is_symlink() and plugin.resolve() == ROOT / 'swiftbar/padpilot.30s.py':
            trash(plugin)
        elif plugin.exists() or plugin.is_symlink():
            print(f'Not an owned legacy link; left untouched: {plugin}')


def stop_menu_apps():
    for app in (Path.home() / 'Applications/PadPilot.app', ROOT / 'build/PadPilot.app'):
        if not owned_app(app):
            continue
        pattern = '^' + re.escape(str(app / 'Contents/MacOS/PadPilot')) + r'( |$)'
        for attempt in range(30):
            result = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True, check=False)
            if result.returncode == 1:
                break
            if result.returncode != 0:
                raise RuntimeError('Unable to verify running PadPilot app')
            for pid in map(int, result.stdout.split()):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            time.sleep(0.1)
        else:
            raise RuntimeError('PadPilot app is still running; close it and retry.')


def ensure_settings_closed():
    # Tk windows can outlive the menu app and write settings after removal.
    pattern = r'(^| )' + re.escape(str(ROOT / 'bin/padpilot-cli')) + r' (gui|open-log)( |$)'
    result = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True, timeout=5)
    if result.returncode == 0:
        raise RuntimeError('請先儲存並關閉 PadPilot 設定／診斷視窗，再重試。 / Close PadPilot settings windows and retry.')
    if result.returncode != 1:
        raise RuntimeError('Cannot check open settings windows; no installation changes made.')


def manage(uninstall=False, purge=False, *, remove_config=False, remove_logs=False, betterdisplay_path=None):
    remove_config = remove_config or purge
    remove_logs = remove_logs or purge
    app = Path.home() / 'Applications/PadPilot.app'
    if (app.exists() or app.is_symlink()) and (app.is_symlink() or not owned_app(app)):
        raise RuntimeError(f'Refusing to replace/remove an app from another checkout: {app}')
    plist = get_launch_agent_plist_path()
    validate_plist(plist)
    ensure_settings_closed()
    if not uninstall:
        cfg = load_config()  # Invalid configuration must fail before stopping anything.
        if betterdisplay_path is not None:
            candidate = copy.deepcopy(cfg)
            apply_change(candidate, 'set_betterdisplaycli_path', {'path': betterdisplay_path})
        build(ROOT / 'build/PadPilot.app')
        was_loaded, was_running = job_loaded(plist), bool(daemon_pids())
        previous_plist = plist.read_bytes() if plist.exists() else None
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
                if not cfg.autostart_on_login:
                    plist.unlink(missing_ok=True)
                subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
            except Exception as error:
                try:
                    stop_daemon(plist)
                    stop_menu_apps()
                    if replaced:
                        trash(app)
                    if previous_app is not None:
                        previous_app.rename(app)
                    if path_changed:
                        save_config(cfg)
                    if previous_plist is None:
                        plist.unlink(missing_ok=True)
                    else:
                        atomic_write(plist, previous_plist, private_parent=False)
                    if was_loaded:
                        subprocess.run(['launchctl', 'load', str(plist)], check=True, capture_output=True, timeout=10)
                        wait_for_daemon()
                    elif was_running:
                        if previous_python == sys.executable:
                            start_standalone()
                        else:
                            subprocess.run([previous_python, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
                    if was_running or was_loaded:
                        # start clears the hidden-menu marker and reopens the restored app.
                        subprocess.run([previous_python, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
                except Exception as restore_error:
                    raise RuntimeError(f'Installation failed: {error}. Rollback incomplete: {restore_error}') from error
                raise RuntimeError(f'Installation failed: {error}. Previous app and service state restored.') from error
        retire_legacy_plugin()
        try:
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            if shortcut.is_symlink() and shortcut.resolve() == ROOT / 'bin/padpilot-cli':
                shortcut.unlink()
            if not (shortcut.exists() or shortcut.is_symlink()):
                shortcut.symlink_to(launcher)
            elif not (shortcut.is_symlink() and shortcut.resolve() == launcher):
                print(f'Existing CLI shortcut preserved: {shortcut}; use {launcher}')
        except OSError as error:
            print(f'App installed; optional CLI shortcut unavailable ({error}). Use: {launcher}')
        print(f'Installed: {app}\nPython: {sys.executable}\nKeep source folder: {ROOT}\nCLI: {launcher}')
        return
    # Shared CLI verifies launchd and exact daemon PIDs before removing snapshots.
    subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
    stop_menu_apps()
    retire_legacy_plugin()
    if uninstall:
        if plist.exists():
            trash(plist)
        if app.exists():
            trash(app)
        if shortcut.is_symlink() and shortcut.resolve() in (ROOT / 'bin/padpilot-cli', launcher):
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
