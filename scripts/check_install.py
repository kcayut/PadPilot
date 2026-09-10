#!/usr/bin/env python3
"""Read-only dependency check: never builds, starts a service, or writes user files."""
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
from core.storage import UnsafePathError, private_file


def check():
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
        import tkinter
        print(f'PASS: Tkinter: {tkinter.TkVersion}')
    except (ImportError, OSError) as error:
        print(f'WARN: Tkinter unavailable ({type(error).__name__}); GUI disabled, daemon/CLI/native menu remain usable.')
    try:
        compiler = subprocess.run(['xcrun', '--find', 'swiftc'], capture_output=True, text=True, timeout=5)
        report(compiler.returncode == 0, 'Swift compiler', compiler.stdout.strip() or 'Run xcode-select --install')
    except (OSError, subprocess.SubprocessError):
        report(False, 'Swift compiler', 'Run xcode-select --install')
    apps = (Path('/Applications/BetterDisplay.app'), Path.home() / 'Applications/BetterDisplay.app')
    app = next((p for p in apps if p.is_dir()), None)
    report(app is not None, 'BetterDisplay app', str(app) if app else 'Install BetterDisplay first')
    cfg_file = Path.home() / 'Library/Application Support/PadPilot/config.json'
    custom = None
    try:
        if cfg_file.exists() or cfg_file.is_symlink():
            info = cfg_file.parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise UnsafePathError('untrusted configuration directory')
            private_file(cfg_file, harden=False)
            custom = json.loads(cfg_file.read_text(encoding='utf-8')).get('betterdisplaycli_path')
            if custom is not None and not isinstance(custom, str):
                raise ValueError('invalid CLI path')
    except (OSError, ValueError, AttributeError, UnsafePathError):
        custom = None
        report(False, 'Configuration', 'Cannot read configured CLI path; repair config before installing')
    cli = BetterDisplayCLI.resolve_cli_path(custom)
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
    sys.exit(0 if check() else 1)
