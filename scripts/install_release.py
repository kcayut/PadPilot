#!/usr/bin/env python3
"""Install a verified, already compiled app. No compiler or third-party Python needed."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from core.config import load_config
from core.runtime import app_runtime, bundled_app, check_python, preference_path, read_preference
from core.storage import atomic_write
from manage_app import ensure_settings_closed, stop_menu_apps, trash, installation_service
from core.autostart import service_command


def cli(app, *args, capture=False):
    return subprocess.run([str(app / 'Contents/Resources/padpilot-cli'), *args],
                          check=True, text=True, capture_output=capture, timeout=90)


def install(source, target, python=None):
    source, target = source.resolve(), target.expanduser().absolute()
    source_root, _ = app_runtime(source)
    if bundled_app(source_root) != source:
        raise ValueError('Installer requires a self-contained release app')
    if target.name != 'PadPilot.app' or source == target:
        raise ValueError('Choose a different destination ending in PadPilot.app')
    if target.is_symlink() or target.parent.is_symlink():
        raise ValueError('Installation paths must not be symbolic links')
    target.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(target.parent, os.W_OK):
        raise ValueError('Destination is not writable; use --target "$HOME/Applications/PadPilot.app"')
    previous_root = app_runtime(target)[0] if target.exists() else None
    if target.exists() and target.stat().st_uid != os.getuid():
        raise ValueError('Existing app must be owned by you')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(source)], check=True)
    chosen = {'python': check_python(python)[0]} if python else {}
    load_config()  # Invalid settings fail before stopping the previous version.
    ensure_settings_closed()
    read_preference()
    pref = preference_path()
    previous_pref = pref.read_bytes() if pref.exists() else None
    previous_service = installation_service(target)
    previous_app = None
    replaced = False
    was_running = False
    if previous_root:
        was_running = json.loads(cli(target, 'status', '--json', capture=True).stdout)['daemon_responding']
    with tempfile.TemporaryDirectory(prefix='padpilot-release-', dir=target.parent) as directory:
        staged = Path(directory) / 'PadPilot.app'
        shutil.copytree(source, Path(directory) / 'payload', symlinks=True)
        (Path(directory) / 'payload').rename(staged)
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(staged)], check=True)
        try:
            if previous_root:
                cli(target, 'exit')
                stop_menu_apps([target])
                service_command('unregister', target)
            if target.exists():
                previous_app = trash(target)
            staged.rename(target)
            replaced = True
            atomic_write(pref, (json.dumps(chosen) + '\n').encode())
            cli(target, '--version')
            cli(target, 'gui-data', capture=True)
            if previous_service == 'enabled':
                service_command('register', target)
            if was_running:
                cli(target, 'start')
            elif previous_service == 'enabled':
                cli(target, 'exit')
        except Exception as error:
            try:
                if replaced:
                    service_command('unregister', target)
                    cli(target, 'exit')
                    stop_menu_apps([target])
                    trash(target)
                if previous_app:
                    previous_app.rename(target)
                if previous_pref is None:
                    pref.unlink(missing_ok=True)
                else:
                    atomic_write(pref, previous_pref)
                if previous_service == 'enabled':
                    service_command('register', target)
                if was_running and previous_root:
                    cli(target, 'start')
                elif previous_service == 'enabled':
                    cli(target, 'exit')
            except Exception as restore_error:
                raise RuntimeError(f'Installation failed: {error}. Rollback incomplete: {restore_error}') from error
            raise
    shortcut = Path.home() / 'bin/padpilot-cli'
    launcher = target / 'Contents/Resources/padpilot-cli'
    try:
        shortcut.parent.mkdir(exist_ok=True)
        if not (shortcut.exists() or shortcut.is_symlink()):
            shortcut.symlink_to(launcher)
    except OSError as error:
        print(f'Optional shortcut unavailable: {error}')
    print(f'Installed: {target}\nPython: {python or "bundled"}\nCLI: {launcher}')
    print('Open the installed PadPilot app to start. / 開啟安裝好的 PadPilot 即可啟動。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--python')
    args = parser.parse_args()
    try:
        install(args.source, args.target, args.python)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, f'Installation failed: {error}\n')
