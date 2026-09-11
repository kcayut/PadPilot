#!/usr/bin/env python3
"""Read-only dependency check: never builds, starts a service, or writes user files."""
import argparse
import json
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.betterdisplay import BetterDisplayCLI
from core.storage import UnsafePathError, latest_state_path, private_file


def resolve_betterdisplay_path(custom=None):
    """Read the selected CLI without importing configuration or creating state."""
    cfg_file = Path.home() / 'Library/Application Support/PadPilot/config.json'
    cfg_file = latest_state_path(cfg_file, Path('/tmp/PadPilot/config.json'))
    if cfg_file.exists() or cfg_file.is_symlink():
        info = cfg_file.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise UnsafePathError('untrusted configuration directory')
        private_file(cfg_file, harden=False)
        configured = json.loads(cfg_file.read_text(encoding='utf-8')).get('betterdisplaycli_path')
        if configured is not None and not isinstance(configured, str):
            raise ValueError('invalid CLI path')
        if custom is None:
            custom = configured
    return BetterDisplayCLI.resolve_cli_path(str(Path(custom).expanduser()) if custom else None)


def check(betterdisplay_path=None):
    errors = []
    def report(ok, label, detail):
        print(f'{"PASS" if ok else "FAIL"}: {label}: {detail}')
        if not ok:
            errors.append(label)
    mac_version = platform.mac_ver()[0]
    report(sys.platform == 'darwin' and bool(mac_version) and int(mac_version.split('.')[0]) >= 14,
           'macOS', mac_version or sys.platform)
    report(sys.version_info >= (3, 10), 'Python', f'{platform.python_version()} ({sys.executable})')
    try:
        developer = subprocess.run(['xcode-select', '-p'], capture_output=True, text=True, timeout=5)
        if developer.returncode != 0 and not os.environ.get('DEVELOPER_DIR'):
            raise OSError('Apple Command Line Tools are not installed')
        compiler = subprocess.run(['xcrun', '--find', 'swiftc'], capture_output=True, text=True, timeout=5)
        report(compiler.returncode == 0, 'Swift compiler', compiler.stdout.strip() or 'Run xcode-select --install')
    except (OSError, subprocess.SubprocessError):
        report(False, 'Swift compiler', 'Run xcode-select --install')
    try:
        cli = resolve_betterdisplay_path(betterdisplay_path)
    except (OSError, ValueError, AttributeError, UnsafePathError):
        report(False, 'Configuration', 'Cannot read configured CLI path; repair config before installing')
        cli = BetterDisplayCLI.resolve_cli_path(None)
    app = BetterDisplayCLI.resolve_app_path(cli or betterdisplay_path)
    report(app is not None, 'BetterDisplay app', app or 'Install BetterDisplay or select its app path')
    if not cli:
        report(False, 'BetterDisplay CLI', 'Executable missing or configured path invalid')
    else:
        try:
            response = subprocess.run([cli, 'help'], capture_output=True, text=True, timeout=15)
            report(response.returncode == 0 and bool(response.stdout.strip() or response.stderr.strip()),
                   'BetterDisplay CLI', cli if response.returncode == 0 else 'Help command failed; check CLI configuration')
        except (OSError, subprocess.SubprocessError):
            report(False, 'BetterDisplay CLI', 'Help unavailable/timed out; check CLI configuration')
    print('NOTE: This check does not verify BetterDisplay licensing, Sidecar pairing, permissions, or physical displays.')
    return not errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--betterdisplay-path', help='Selected BetterDisplay app or CLI executable')
    args = parser.parse_args()
    sys.exit(0 if check(args.betterdisplay_path) else 1)
