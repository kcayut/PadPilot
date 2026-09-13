"""Portable app layout and explicit, user-owned Python selection."""
import fcntl
import json
import os
import plistlib
import re
import stat
import subprocess
from pathlib import Path

from core.storage import atomic_write, private_file

ROOT = Path(__file__).resolve().parents[1]


def bundled_app(root=ROOT):
    root = Path(root).resolve()
    if root.name == 'PadPilot' and root.parent.name == 'Resources' and root.parent.parent.name == 'Contents':
        app = root.parent.parent.parent
        if app.suffix == '.app':
            return app
    return None


def app_runtime(app):
    app = Path(app).resolve()
    resources = app / 'Contents/Resources'
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    value = json.loads((resources / 'runtime.json').read_text())
    if info.get('CFBundleIdentifier') != 'com.padpilot.app' or not isinstance(value, dict):
        raise ValueError('Not a PadPilot app')
    if value.get('bundled') is True:
        # Release paths are fixed, never a build-machine absolute path.
        if value.get('project_root') != 'PadPilot' or value.get('python') != 'Python/bin/python3':
            raise ValueError('Invalid bundled runtime layout')
        return (resources / 'PadPilot').resolve(), (resources / value['python']).resolve()
    root, python = Path(value['project_root']), Path(value['python'])
    if not root.is_absolute() or not python.is_absolute():
        raise ValueError('Invalid source runtime paths')
    return root.resolve(), python


def preference_path():
    return Path.home() / 'Library/Application Support/PadPilot/python-runtime.json'


def read_preference():
    path = preference_path()
    if path.parent.exists() or path.parent.is_symlink():
        info = path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Unsafe Python preference directory')
    private_file(path, harden=False)
    if not path.exists():
        return {}
    if path.stat().st_size >= 16384:
        raise ValueError('Python preference file is too large')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), encoding='utf-8') as stream:
        value = json.load(stream)
    if (not isinstance(value, dict) or set(value) - {'python'} or
            ('python' in value and (not isinstance(value['python'], str) or not value['python'].startswith('/')))):
        raise ValueError('Invalid Python preference; use --bundled-cli runtime bundled to reset')
    return value


def check_python(python):
    path = Path(python).expanduser()
    if not path.is_absolute() or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Select an executable Python 3.10+ using an absolute path')
    if not re.fullmatch(r'python(?:[0-9.]+)?', path.name.lower()):
        raise ValueError('Select a CPython executable named python or python3.x')
    for parent in path.resolve().parents:
        if parent.suffix == '.app':
            try:
                info = plistlib.loads((parent / 'Contents/Info.plist').read_bytes())
            except (OSError, ValueError):
                continue
            if info.get('CFBundleIdentifier') == 'com.padpilot.app':
                raise ValueError('Use bundled mode instead of selecting Python inside another PadPilot.app')
    probe = ('import sys,platform,json,socket,threading,fcntl,ctypes,ctypes.util,ssl; '
             'assert sys.version_info >= (3,10), "Python 3.10+ required"; '
             'assert sys.platform == "darwin" and platform.machine() == "arm64", "Apple Silicon Python required"; '
             'print(platform.python_version())')
    result = subprocess.run([str(path), '-I', '-B', '-c', probe], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError('Python validation failed: ' + (result.stderr.strip() or str(path)))
    return str(path), result.stdout.strip()


def set_python(python=None):
    """Only change interpreter after this user's app and daemon have exited."""
    if bundled_app() is None:
        raise RuntimeError('Python selection applies to a bundled release app')
    from core.autostart import daemon_pids, service_command
    service_command()
    if daemon_pids():
        raise RuntimeError('Exit PadPilot before changing Python / 請先離開 PadPilot 再切換 Python')
    lock = preference_path().parent / 'runtime/menu-app.lock'
    if lock.parent.exists() or lock.parent.is_symlink():
        info = lock.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise RuntimeError('Unsafe app lock directory')
    private_file(lock, harden=False)
    if lock.exists():
        with os.fdopen(os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('Close PadPilot before changing Python / 請先關閉 PadPilot') from error
    value = {'python': check_python(python)[0]} if python else {}
    # atomic_write checks directory ownership and rejects links even when resetting damaged JSON.
    path = preference_path()
    atomic_write(path, (json.dumps(value) + '\n').encode())
