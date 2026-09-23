#!/usr/bin/env python3
"""Package an existing app in the three-language drag-to-install disk image."""
import argparse
import plistlib
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_dmg(app, destination):
    try:
        import dmgbuild
    except ImportError as error:
        raise RuntimeError('DMG packaging needs: python -m pip install -r scripts/dmg-requirements.txt') from error
    app, destination = Path(app).resolve(), Path(destination).resolve()
    if not (app / 'Contents/Info.plist').is_file():
        raise ValueError(f'Not an application bundle: {app}')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sidecarswitch-dmg-') as directory:
        stage = Path(directory)
        subprocess.run(['swift', str(ROOT / 'scripts/dmg_background.swift'), str(stage)], check=True)
        link = stage / 'BetterDisplay.webloc'
        link.write_bytes(plistlib.dumps({'URL': 'https://github.com/waydabber/BetterDisplay#readme'}))
        dmgbuild.build_dmg(str(destination), 'SidecarSwitch', settings={
            'format': 'UDZO',
            'files': [(str(app), 'SidecarSwitch.app'), str(link), str(ROOT / 'assets/dmg/Start Here.html')],
            'symlinks': {'Applications': '/Applications'},
            'background': str(stage / 'background.png'),
            'window_rect': ((100, 100), (960, 700)),
            'default_view': 'icon-view',
            'grid_spacing': 96,
            'show_status_bar': False, 'show_tab_view': False, 'show_toolbar': False,
            'show_pathbar': False, 'show_sidebar': False,
            'icon_size': 72, 'text_size': 13,
            'icon_locations': {'SidecarSwitch.app': (320, 326), 'Applications': (610, 326),
                               'BetterDisplay.webloc': (840, 131), 'Start Here.html': (840, 507),
                               # Keep the asset out of the copy even when Show Hidden Files is on.
                               '.background.png': (1100, 100)},
            # Setting FinderInfo on the signed .app breaks strict codesign verification.
            'hide_extensions': ['BetterDisplay.webloc', 'Start Here.html'],
        })
    subprocess.run(['hdiutil', 'verify', str(destination)], check=True)
    # dmgbuild's ditto call does not check its exit status; verify the copied bundle.
    with tempfile.TemporaryDirectory(prefix='sidecarswitch-dmg-check-') as directory:
        mount = Path(directory) / 'volume'
        subprocess.run(['hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', str(mount),
                        str(destination)], check=True, stdout=subprocess.DEVNULL)
        try:
            if ((mount / 'Applications').readlink() != Path('/Applications')
                    or not (mount / '.DS_Store').is_file()
                    or not (mount / '.background.png').is_file()
                    or (mount / 'Start Here.html').read_bytes() != (ROOT / 'assets/dmg/Start Here.html').read_bytes()
                    or plistlib.loads((mount / 'BetterDisplay.webloc').read_bytes()).get('URL')
                    != 'https://github.com/waydabber/BetterDisplay#readme'):
                raise RuntimeError('Incomplete DMG installation layout')
            subprocess.run(['codesign', '--verify', '--deep', '--strict', str(mount / 'SidecarSwitch.app')], check=True)
        finally:
            subprocess.run(['hdiutil', 'detach', str(mount)], check=True, stdout=subprocess.DEVNULL)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(build_dmg(args.app, args.destination))
