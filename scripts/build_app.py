#!/usr/bin/env python3
"""Build the native menu app using Apple's command line tools; no Swift packages."""
import argparse
import json
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import __version__


def build(output):
    if sys.platform != 'darwin':
        raise RuntimeError('PadPilot.app requires macOS.')
    output = output.resolve()
    if output.suffix != '.app':
        raise ValueError('Output must end in .app')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='padpilot-build-', dir=output.parent) as directory:
        app = Path(directory) / 'PadPilot.app'
        contents = app / 'Contents'
        resources = contents / 'Resources'
        resources.mkdir(parents=True)
        (contents / 'MacOS').mkdir()
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library', '-O',
                        '-target', f'{platform.machine()}-apple-macosx14.0',
                        '-module-cache-path', str(ROOT / 'build' / 'swift-cache'),
                        str(ROOT / 'native' / 'PadPilot.swift'), '-o', str(contents / 'MacOS' / 'PadPilot')],
                       check=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.padpilot.app', 'CFBundleName': 'PadPilot',
            'CFBundleDisplayName': 'PadPilot', 'CFBundleExecutable': 'PadPilot',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': __version__,
            'CFBundleVersion': __version__, 'LSMinimumSystemVersion': '14.0',
            'LSUIElement': True, 'NSHighResolutionCapable': True,
        }))
        (resources / 'runtime.json').write_text(json.dumps({
            'python': sys.executable, 'project_root': str(ROOT),
        }, indent=2), encoding='utf-8')
        shutil.copytree(ROOT / 'assets' / 'menu-icons', resources / 'menu-icons')
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
        # Validate ownership before replacing only our generated output.
        if output.exists():
            info = plistlib.loads((output / 'Contents' / 'Info.plist').read_bytes())
            if info.get('CFBundleIdentifier') != 'com.padpilot.app':
                raise ValueError(f'Refusing to replace another app: {output}')
            backup = Path(directory) / 'previous.app'
            output.rename(backup)
            try:
                app.rename(output)
            except OSError:
                backup.rename(output)
                raise
        else:
            app.rename(output)
    print(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'PadPilot.app')
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Build failed: {error}\n')
