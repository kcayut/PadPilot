#!/usr/bin/env python3
"""Build the native menu app using Apple's command line tools; no Swift packages."""
import argparse
import json
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import __version__


def build_icon(directory, output):
    """Package the README artwork at macOS standard and Retina icon sizes."""
    chunks = []
    # Standard PNG-backed ICNS elements also work when iconutil's encoder is unavailable.
    for kind, size in ((b'icp4', 16), (b'ic11', 32), (b'icp5', 32), (b'ic12', 64),
                       (b'ic07', 128), (b'ic13', 256), (b'ic08', 256), (b'ic14', 512),
                       (b'ic09', 512), (b'ic10', 1024)):
        png = directory / (kind.decode() + '.png')
        subprocess.run(['/usr/bin/sips', '-z', str(size), str(size), str(ROOT / 'assets/sidecarswitch-icon.png'),
                        '--out', str(png)], check=True, capture_output=True)
        data = png.read_bytes()
        chunks.append(kind + (len(data) + 8).to_bytes(4, 'big') + data)
    data = b''.join(chunks)
    output.write_bytes(b'icns' + (len(data) + 8).to_bytes(4, 'big') + data)


def build(output, *, python_home=None, version=None, revision=None):
    if sys.platform != 'darwin':
        raise RuntimeError('SidecarSwitch.app requires macOS.')
    if python_home is not None and platform.machine() != 'arm64':
        raise RuntimeError('Release apps support Apple Silicon only.')
    version = version or __version__
    output = output.resolve()
    if output.suffix != '.app':
        raise ValueError('Output must end in .app')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sidecarswitch-build-', dir=output.parent) as directory:
        # Build in an ordinary folder; expose an app bundle only when its contents are complete.
        app = Path(directory) / 'payload'
        contents = app / 'Contents'
        resources = contents / 'Resources'
        resources.mkdir(parents=True)
        (contents / 'MacOS').mkdir()
        build_icon(Path(directory), resources / 'SidecarSwitch.icns')
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library', '-O',
                        '-target', f'{platform.machine()}-apple-macosx14.0',
                        '-module-cache-path', str(ROOT / 'build' / 'swift-cache'),
                        str(ROOT / 'native' / 'SidecarSwitch.swift'), str(ROOT / 'native' / 'Settings.swift'), str(ROOT / 'native' / 'ConnectionHotKey.swift'),
                        '-o', str(contents / 'MacOS' / 'SidecarSwitch')],
                       check=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.sidecarswitch.app', 'CFBundleName': 'SidecarSwitch',
            'CFBundleDisplayName': 'SidecarSwitch', 'CFBundleExecutable': 'SidecarSwitch',
            'CFBundleIconFile': 'SidecarSwitch.icns',
            'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': version.split('-')[0],
            'CFBundleVersion': version.split('-')[0], 'LSMinimumSystemVersion': '14.0',
            'LSUIElement': True, 'NSHighResolutionCapable': True,
            'CFBundleURLTypes': [{'CFBundleURLName': 'com.sidecarswitch.settings',
                                  'CFBundleURLSchemes': ['sidecarswitch']}],
        }))
        metadata = {'python': sys.executable, 'project_root': str(ROOT), 'locator': 1}
        if python_home is not None:
            shutil.copytree(python_home, resources / 'Python', symlinks=True)
            source = resources / 'SidecarSwitch'
            for name in ('bin', 'core', 'scripts'):
                shutil.copytree(ROOT / name, source / name,
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for name in ('LICENSE', 'NOTICE'):
                shutil.copy2(ROOT / name, source / name)
            (source / 'core/__init__.py').write_text(
                f'"""SidecarSwitch release metadata."""\n__version__ = {version!r}\n__revision__ = {revision or "unknown"!r}\n')
            metadata = {'bundled': True, 'python': 'Python/bin/python3', 'project_root': 'SidecarSwitch', 'locator': 1}
        from core.autostart import generate_plist_content
        agents = contents / 'Library/LaunchAgents'
        agents.mkdir(parents=True)
        (agents / 'com.sidecarswitch.daemon.plist').write_text(generate_plist_content())
        (resources / 'runtime.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        # The terminal shortcut must use the same Python as the app and launchd.
        launcher = resources / 'sidecarswitch-cli'
        if python_home is None:
            launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' '
                                + shlex.quote(str(ROOT / 'bin/sidecarswitch-cli')) + ' "$@"\n', encoding='utf-8')
        else:
            launcher.write_text('''#!/bin/sh
set -eu
entry="$0"
while [ -L "$entry" ]; do
    base="$(cd -P "$(dirname "$entry")" && pwd)"
    link="$(readlink "$entry")"
    case "$link" in /*) entry="$link" ;; *) entry="$base/$link" ;; esac
done
resources="$(cd -P "$(dirname "$entry")" && pwd)"
mode=--cli
if [ "${1:-}" = --bundled-cli ]; then mode=--bundled-cli; shift; fi
exec "$resources/../MacOS/SidecarSwitch" "$mode" "$@"
''', encoding='utf-8')
        launcher.chmod(0o755)
        shutil.copytree(ROOT / 'assets' / 'menu-icons', resources / 'menu-icons')
        shutil.copy2(ROOT / 'LICENSE', resources / 'LICENSE')
        shutil.copy2(ROOT / 'NOTICE', resources / 'NOTICE')
        if python_home is not None:
            # Sign nested Mach-O code before sealing the app; no Developer ID or notarization.
            magic = (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf')
            for binary in sorted((resources / 'Python').rglob('*')):
                if binary.is_symlink() or not binary.is_file():
                    continue
                with binary.open('rb') as stream:
                    is_macho = stream.read(4) in magic
                if is_macho:
                    result = subprocess.run(['codesign', '--force', '--sign', '-', str(binary)], capture_output=True, text=True)
                    if result.returncode:
                        raise RuntimeError(f'Cannot sign {binary.name}: {result.stderr.strip()}')
        ready = Path(directory) / 'SidecarSwitch.app'
        app.rename(ready)
        app = ready
        subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
        # Validate ownership before replacing only our generated output.
        if output.exists():
            info = plistlib.loads((output / 'Contents' / 'Info.plist').read_bytes())
            if info.get('CFBundleIdentifier') != 'com.sidecarswitch.app':
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
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'SidecarSwitch.app')
    args = parser.parse_args()
    try:
        build(args.output)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Build failed: {error}\n')
