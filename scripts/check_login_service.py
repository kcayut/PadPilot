#!/usr/bin/env python3
"""Opt-in macOS integration check using an isolated app ID; never runs PadPilot core."""
import argparse
import json
import os
import plistlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


def check(app_source, trash=False):
    source = app_source.resolve()
    if not (source / 'Contents/Library/LaunchAgents/com.padpilot.daemon.plist').is_file():
        raise ValueError('Build the SMAppService app first')
    base = Path(tempfile.mkdtemp(prefix='padpilot-service-check-', dir='/private/tmp'))
    app = base / 'PadPilot.app'
    label = 'com.padpilot.test.' + uuid.uuid4().hex
    target = f'gui/{os.getuid()}/{label}'
    print(f'Isolated fixture: {base}', flush=True)

    def native(action):
        return subprocess.check_output([str(app / 'Contents/MacOS/PadPilot'), '--service', action],
                                       text=True, stderr=subprocess.PIPE, timeout=30, env={**os.environ, 'HOME': str(base)}).strip()

    def starts():
        path = base / 'starts'
        return path.read_text().count('start') if path.exists() else 0

    def wait_for(count):
        deadline = time.monotonic() + 20
        while starts() < count and time.monotonic() < deadline:
            time.sleep(.1)
        assert starts() == count, f'Expected {count} starts; got {starts()}'

    registered = False
    try:
        shutil.copytree(source, app)
        info = app / 'Contents/Info.plist'
        value = plistlib.loads(info.read_bytes())
        value['CFBundleIdentifier'] = label
        info.write_bytes(plistlib.dumps(value))
        plist = app / 'Contents/Library/LaunchAgents/com.padpilot.daemon.plist'
        value = plistlib.loads(plist.read_bytes())
        value['Label'] = label
        value['EnvironmentVariables']['HOME'] = str(base)
        plist.write_bytes(plistlib.dumps(value))
        metadata_path = app / 'Contents/Resources/runtime.json'
        metadata = json.loads(metadata_path.read_text())
        if metadata.get('bundled'):
            daemon = app / 'Contents/Resources/PadPilot/bin/padpilotd'
        else:
            daemon = base / 'bin/padpilotd'
            daemon.parent.mkdir()
            metadata_path.write_text(json.dumps({'python': sys.executable, 'project_root': str(base)}))
        daemon.write_text(f"""import os, signal, time
from pathlib import Path
root = Path({str(base)!r})
signal.signal(signal.SIGTERM, lambda *_: exit(0))
(root / 'pid').write_text(str(os.getpid()))
with (root / 'starts').open('a') as stream: stream.write('start\\n')
while True: time.sleep(.1)
""")
        subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', label, str(app)],
                       check=True, capture_output=True)
        assert native('status') in {'notRegistered', 'notFound'}
        registered = True  # Always attempt cleanup if registration only partially succeeds.
        assert native('register') == 'enabled', 'System approval is required for the isolated fixture'
        wait_for(1)
        output = subprocess.check_output(['launchctl', 'print', target], text=True)
        assert 'managed_by = com.apple.xpc.ServiceManagement' in output
        assert 'program identifier = Contents/MacOS/PadPilot (mode: 2)' in output
        os.kill(int((base / 'pid').read_text()), signal.SIGTERM)
        time.sleep(2)
        assert starts() == 1, 'Normal Exit must not restart'
        assert native('status') == 'enabled', 'Normal Exit must preserve next-login registration'
        assert native('register') == 'enabled'  # Same operation used after an app replacement.
        wait_for(2)
        os.kill(int((base / 'pid').read_text()), signal.SIGKILL)
        wait_for(3)
        print('PASS: registration, Python launch, normal Exit, restart, crash recovery', flush=True)
        if trash:
            os.kill(int((base / 'pid').read_text()), signal.SIGTERM)
            time.sleep(1)
            script = ('import Foundation; var result: NSURL?; '
                      'try FileManager.default.trashItem(at: URL(fileURLWithPath: CommandLine.arguments[1]), '
                      'resultingItemURL: &result); print(result!.path!)')
            destination = subprocess.check_output(['swift', '-module-cache-path', str(base / 'swift-cache'),
                                                   '-e', script, str(app)], text=True).strip()
            app = Path(destination)
            assert '.Trash' in app.parts or '.Trashes' in app.parts
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job = subprocess.run(['launchctl', 'print', target], capture_output=True, text=True)
                if job.returncode == 113:
                    break
                time.sleep(.2)
            assert starts() == 3, 'Trashed app must not start Python'
            job = subprocess.run(['launchctl', 'print', target], capture_output=True, text=True)
            assert job.returncode == 113, \
                f'Trashed app is still registered:\n{job.stdout}'
            assert native('status') in {'notRegistered', 'notFound'}
            assert subprocess.run(['launchctl', 'kickstart', target], capture_output=True).returncode != 0
            print('PASS: Trash remains unemptied; login service removed without Python restart', flush=True)
    finally:
        # If unregister fails, retain the executable for explicit cleanup, not a broken launch item.
        if registered:
            native('unregister')
            job = subprocess.run(['launchctl', 'print', target], capture_output=True)
            if job.returncode != 113:
                raise RuntimeError(f'Fixture still registered; retained at {app}')
        if app.exists() and app.parent != base:
            shutil.rmtree(app)
        shutil.rmtree(base)
    print('PASS: test service unregistered and fixture removed', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True, help='Already built PadPilot.app; source is copied, never changed')
    parser.add_argument('--trash', action='store_true', help='Also move the isolated fixture to the real macOS Trash')
    args = parser.parse_args()
    check(args.app, args.trash)
