#!/usr/bin/env python3
"""Build a relocatable Apple Silicon development release. Never install or publish."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from build_app import ROOT, build


def release_version(tag):
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-(?:dev|alpha|beta|rc)\.\d+)?', tag):
        raise ValueError('Expected vX.Y.Z or vX.Y.Z-dev.N / alpha.N / beta.N / rc.N')
    return tag[1:]


def python_distribution():
    if sys.version_info < (3, 12):
        raise RuntimeError('Release packaging requires Python 3.12+ for safe archive extraction')
    pin = json.loads((ROOT / 'scripts/python-runtime.json').read_text())
    cache = ROOT / 'build/python-download'
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (pin['sha256'] + '.tar.gz')
    if not archive.exists():
        temporary = archive.with_suffix('.partial')
        subprocess.run(['curl', '--fail', '--location', '--proto', '=https', '--tlsv1.2',
                        '--retry', '2', pin['url'], '--output', str(temporary)], check=True)
        temporary.replace(archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != pin['sha256']:
        raise RuntimeError(f'Python SHA-256 mismatch; remove the invalid cache file: {archive}')
    return archive, pin


def smoke_check(app):
    """Exercise the distributed CLI from a different path and an empty user home."""
    with tempfile.TemporaryDirectory(prefix='padpilot-relocation-') as directory:
        root = Path(directory)
        moved = root / 'Applications with spaces/PadPilot.app'
        moved.parent.mkdir()
        shutil.copytree(app, root / 'payload', symlinks=True)
        (root / 'payload').rename(moved)
        home = root / 'clean-home'
        home.mkdir()
        environment = dict(os.environ, HOME=str(home), PYTHONPATH='/nonexistent', PYTHONHOME='/nonexistent')
        native = moved / 'Contents/MacOS/PadPilot'
        info = subprocess.check_output([str(native), '--runtime-info'], env=environment, text=True)
        runtime = json.loads(info)
        assert runtime['bundled'] and str(moved) in runtime['python'] and str(moved) in runtime['project_root']
        cli = moved / 'Contents/Resources/padpilot-cli'
        for arguments in (['--version'], ['--help'], ['runtime', 'status'], ['menu-json'], ['gui-data']):
            result = subprocess.run([str(cli), *arguments], env=environment, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError(f'Relocated CLI failed ({arguments}): {result.stderr}')
            if arguments[0] in ('menu-json', 'gui-data'):
                json.loads(result.stdout)
        probe = ('import ctypes,ssl,socket,fcntl,threading; '
                 '[ctypes.CDLL(p) for p in ("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics", '
                 '"/System/Library/Frameworks/IOKit.framework/IOKit", '
                 '"/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]')
        subprocess.run([runtime['python'], '-I', '-B', '-c', probe], env=environment, check=True)
        external = home / 'External Python/python3'
        external.parent.mkdir()
        external.symlink_to(sys.executable)
        subprocess.run([str(cli), '--bundled-cli', 'runtime', 'external', '--python', str(external)],
                       env=environment, check=True, capture_output=True, text=True)
        selected = json.loads(subprocess.check_output([str(native), '--runtime-info'], env=environment, text=True))
        assert selected['python'] == str(external), 'Native app ignored the selected external Python'
        subprocess.run([str(cli), '--version'], env=environment, check=True, capture_output=True)
        external.unlink()
        assert subprocess.run([str(native), '--runtime-info'], env=environment, capture_output=True).returncode != 0
        subprocess.run([str(cli), '--bundled-cli', 'runtime', 'bundled'], env=environment, check=True,
                       capture_output=True, text=True)
        restored = json.loads(subprocess.check_output([str(native), '--runtime-info'], env=environment, text=True))
        assert restored['python'] == runtime['python'], 'Bundled Python recovery failed'
        # Runtime selection must not modify the sealed bundle.
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(moved)], check=True)
    print('PASS: relocated app, bundled/external Python, missing-Python recovery, CLI/JSON and system frameworks (no display control)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--check-app', type=Path, help='Only check an already built app')
    parser.add_argument('--no-dmg', action='store_true')
    args = parser.parse_args()
    version = release_version(args.tag)
    if args.check_app:
        smoke_check(args.check_app)
        return
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    archive, pin = python_distribution()
    destination = ROOT / 'dist' / args.tag
    destination.mkdir(parents=True, exist_ok=True)
    app = destination / 'PadPilot.app'
    with tempfile.TemporaryDirectory(prefix='padpilot-python-') as directory:
        with tarfile.open(archive) as source:
            source.extractall(directory, filter='data')
        python = Path(directory) / 'python'
        subprocess.run([str(python / 'bin/python3'), '-I', '-B', '-c',
                        'import platform; assert platform.machine() == "arm64"'], check=True)
        build(app, python_home=python, version=version, revision=revision)
    smoke_check(app)
    stem = f'PadPilot-{version}-macos-arm64'
    zipped = destination / (stem + '.zip')
    subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(app), str(zipped)], check=True)
    assets = [zipped]
    if not args.no_dmg:
        with tempfile.TemporaryDirectory(prefix='padpilot-dmg-') as directory:
            stage = Path(directory)
            shutil.copytree(app, stage / 'payload', symlinks=True)
            (stage / 'payload').rename(stage / 'PadPilot.app')
            (stage / 'Applications').symlink_to('/Applications')
            dmg = destination / (stem + '.dmg')
            subprocess.run(['hdiutil', 'create', '-ov', '-format', 'UDZO', '-volname', 'PadPilot',
                            '-srcfolder', str(stage), str(dmg)], check=True)
            assets.append(dmg)
    (destination / 'SHA256SUMS').write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in assets))
    (destination / 'build-info.json').write_text(json.dumps({
        'tag': args.tag, 'commit': revision, 'dirty': dirty, 'python': pin, 'architecture': 'arm64',
        'signing': 'ad-hoc', 'notarized': False, 'physical_acceptance': 'unknown',
    }, indent=2) + '\n')
    print(destination)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f'Release build failed: {error}')
