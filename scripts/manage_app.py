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
from core.autostart import get_launch_agent_plist_path, validate_plist
from core.config import APP_SUPPORT_DIR, load_config


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
    path.rename(folder / path.name)
    print(f'Moved to Trash: {folder / path.name}')


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
        build(ROOT / 'build/PadPilot.app')
    # Shared CLI verifies launchd and exact daemon PIDs before removing snapshots.
    subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'exit'], check=True)
    stop_menu_apps()
    retire_legacy_plugin()
    shortcut = Path.home() / 'bin/padpilot-cli'
    if uninstall:
        if plist.exists():
            trash(plist)
        if app.exists():
            trash(app)
        if shortcut.is_symlink() and shortcut.resolve() == ROOT / 'bin/padpilot-cli':
            trash(shortcut)
        if purge:
            for path in (APP_SUPPORT_DIR, Path.home() / 'Library/Logs/PadPilot'):
                if path.exists():
                    trash(path)
        print('Uninstalled. Source, BetterDisplay and virtual displays were preserved.')
        return
    app.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='padpilot-install-', dir=app.parent) as directory:
        staging = Path(directory) / 'PadPilot.app'
        shutil.copytree(ROOT / 'build/PadPilot.app', staging)
        if app.exists():
            trash(app)
        staging.rename(app)
    cfg = load_config()
    if cfg.autostart_on_login:
        subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'autostart', 'enable'], check=True)
    elif plist.exists():
        trash(plist)
    if shortcut.parent.is_dir() and not (shortcut.exists() or shortcut.is_symlink()):
        shortcut.symlink_to(ROOT / 'bin/padpilot-cli')
    subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'start'], check=True)
    print(f'Installed: {app}\nPython: {sys.executable}\nKeep source folder: {ROOT}')


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
