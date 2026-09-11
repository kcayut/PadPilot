#!/usr/bin/env python3
"""Install/remove only this checkout's app and integrations. User data is preserved."""
import argparse
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
from core.config import APP_SUPPORT_DIR, FALLBACK_CONFIG_FILE, load_config
from core.storage import atomic_write, state_file_exists


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


def manage(uninstall=False, purge=False):
    app = Path.home() / 'Applications/PadPilot.app'
    if (app.exists() or app.is_symlink()) and (app.is_symlink() or not owned_app(app)):
        raise RuntimeError(f'Refusing to replace/remove an app from another checkout: {app}')
    plist = get_launch_agent_plist_path()
    validate_plist(plist)
    if not uninstall:
        cfg = load_config()  # Invalid configuration must fail before stopping anything.
        build(ROOT / 'build/PadPilot.app')
        was_loaded, was_running = job_loaded(plist), bool(daemon_pids())
        previous_plist = plist.read_bytes() if plist.exists() else None
    if purge:
        # Validate before any removal, including a fallback left by an earlier run.
        fallback_exists = state_file_exists(FALLBACK_CONFIG_FILE)
    shortcut = Path.home() / 'bin/padpilot-cli'
    if not uninstall:
        app.parent.mkdir(parents=True, exist_ok=True)
        previous_app = None
        replaced = False
        with tempfile.TemporaryDirectory(prefix='padpilot-install-', dir=app.parent) as directory:
            staging = Path(directory) / 'PadPilot.app'
            shutil.copytree(ROOT / 'build/PadPilot.app', staging)
            try:
                subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
                stop_menu_apps()
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
                    if previous_plist is None:
                        plist.unlink(missing_ok=True)
                    else:
                        atomic_write(plist, previous_plist, private_parent=False)
                    if was_loaded:
                        subprocess.run(['launchctl', 'load', str(plist)], check=True, capture_output=True, timeout=10)
                        wait_for_daemon()
                    elif was_running:
                        start_standalone()
                    if was_running or was_loaded:
                        # start clears the hidden-menu marker and reopens the restored app.
                        subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
                except Exception as restore_error:
                    raise RuntimeError(f'Installation failed: {error}. Rollback incomplete: {restore_error}') from error
                raise RuntimeError(f'Installation failed: {error}. Previous app and service state restored.') from error
        retire_legacy_plugin()
        if shortcut.parent.is_dir() and not (shortcut.exists() or shortcut.is_symlink()):
            shortcut.symlink_to(ROOT / 'bin/padpilot-cli')
        print(f'Installed: {app}\nPython: {sys.executable}\nKeep source folder: {ROOT}')
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
        if shortcut.is_symlink() and shortcut.resolve() == ROOT / 'bin/padpilot-cli':
            trash(shortcut)
        if purge:
            if fallback_exists and FALLBACK_CONFIG_FILE.parent != APP_SUPPORT_DIR:
                trash(FALLBACK_CONFIG_FILE)
            for path in (APP_SUPPORT_DIR, Path.home() / 'Library/Logs/PadPilot'):
                if path.exists():
                    trash(path)
        print('Uninstalled. Source, BetterDisplay and virtual displays were preserved.')
        return


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    parser.add_argument('--purge', action='store_true', help='Move configuration and logs to Trash during uninstall')
    args = parser.parse_args()
    if args.purge and not args.uninstall:
        parser.error('--purge requires --uninstall')
    try:
        manage(args.uninstall, args.purge)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Setup failed: {error}\n')
