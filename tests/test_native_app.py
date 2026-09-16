"""Native AppKit contract and recoverable setup checks; never operate displays."""
import argparse
import contextlib
import io
import json
import os
import plistlib
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_app
import manage_app
from core import autostart, config
from core.menu import render
from core.i18n import set_language


class NativeAppTests(unittest.TestCase):
    def setUp(self):
        # Never discover or remove the developer's installed system App.
        system = patch('core.runtime.SYSTEM_APP', Path('/nonexistent-padpilot-test/PadPilot.app'))
        system.start()
        self.addCleanup(system.stop)

    def test_new_user_install_bundles_service_without_external_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'source checkout'
            (source / 'assets/menu-icons').mkdir(parents=True)
            for name in ('LICENSE', 'NOTICE'):
                (source / name).write_text('test resource')
            cfg = config.Config()
            commands = []
            def run(command, **kwargs):
                commands.append(command)
                return subprocess.CompletedProcess(command, 0)
            with contextlib.ExitStack() as stack:
                for context in (
                    patch.object(Path, 'home', return_value=home),
                    patch.object(build_app, 'ROOT', source), patch.object(build_app, 'build_icon'),
                    patch.object(manage_app, 'ROOT', source), patch.object(manage_app, 'load_config', return_value=cfg),
                    patch.object(manage_app, 'installation_service', return_value='notFound'),
                    patch.object(manage_app, 'service_command', return_value='enabled'),
                    patch.object(manage_app, 'daemon_pids', return_value=[]),
                    patch.object(manage_app, 'ensure_settings_closed'), patch.object(manage_app, 'stop_menu_apps'),
                    patch.object(subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()),
                ): stack.enter_context(context)
                manage_app.manage()
            app = home / 'Applications/PadPilot.app'
            plist = app / 'Contents/Library/LaunchAgents/com.padpilot.daemon.plist'
            self.assertEqual(plistlib.loads(plist.read_bytes()), plistlib.loads(autostart.generate_plist_content().encode()))
            self.assertFalse((home / 'Library/LaunchAgents').exists())
            self.assertFalse(any(command[0] == 'launchctl' for command in commands))
            self.assertIn([sys.executable, str(source / 'bin/padpilot-cli'), 'start'], commands)
            self.assertEqual((home / 'bin/padpilot-cli').resolve(), app / 'Contents/Resources/padpilot-cli')

    def test_install_failure_restores_app_and_previous_service_state(self):
        for registered, running in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(registered=registered, running=running), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                source = home / 'source'
                built, app = source / 'build/PadPilot.app', home / 'Applications/PadPilot.app'
                for path, version in ((built, 'new'), (app, 'old')):
                    path.mkdir(parents=True)
                    (path / 'version').write_text(version)
                original = 'enabled' if registered else 'notRegistered'
                state = {'service': original, 'running': running, 'starts': 0}
                def service(action='status', target=None, **kwargs):
                    if action == 'register': state.update(service='enabled', running=True)
                    elif action == 'unregister': state.update(service='notRegistered', running=False)
                    return state['service']
                def run(command, **kwargs):
                    if command[-1] == 'exit': state['running'] = False
                    elif command[-1] == 'start':
                        state['starts'] += 1
                        if state['starts'] == 1: raise subprocess.CalledProcessError(1, command)
                        state['running'] = True
                        self.assertEqual((app / 'version').read_text(), 'old')
                    return subprocess.CompletedProcess(command, 0)
                with contextlib.ExitStack() as stack:
                    for context in (
                        patch.object(Path, 'home', return_value=home), patch.object(manage_app, 'ROOT', source),
                        patch.object(manage_app, 'owned_app', return_value=True), patch.object(manage_app, 'build'),
                        patch.object(manage_app, 'installation_service', return_value=original),
                        patch.object(manage_app, 'service_command', side_effect=service),
                        patch.object(manage_app, 'load_config', return_value=config.Config()),
                        patch.object(manage_app, 'daemon_pids', return_value=[123] if running else []),
                        patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'),
                        patch.object(manage_app.subprocess, 'run', side_effect=run),
                    ): stack.enter_context(context)
                    with self.assertRaisesRegex(RuntimeError, 'Previous app and service state restored'):
                        manage_app.manage()
                self.assertEqual((state['service'], state['running']), (original, running))
                self.assertEqual((app / 'version').read_text(), 'old')
                self.assertTrue(any(p.read_text() == 'new' for p in (home / '.Trash').glob('*/PadPilot.app/version')))

    def test_purge_trashes_primary_and_fallback_and_rejects_foreign_fallback(self):
        for unsafe in (False, True):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                primary, fallback = home / 'state/config.json', home / 'fallback/config.json'
                config.atomic_write(primary, b'{"revision": 1}')
                fallback.parent.mkdir()
                if unsafe:
                    fallback.symlink_to(primary)
                else:
                    config.atomic_write(fallback, b'{"revision": 8}')
                with patch('pathlib.Path.home', return_value=home), \
                     patch.object(manage_app, 'APP_SUPPORT_DIR', primary.parent), \
                     patch.object(manage_app, 'FALLBACK_CONFIG_FILE', fallback), \
                     patch.object(manage_app, 'installation_service', return_value='notRegistered'), patch.object(manage_app, 'service_command', return_value='notRegistered'), \
                     patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), patch.object(manage_app.subprocess, 'run') as run:
                    if unsafe:
                        with self.assertRaises(RuntimeError):
                            manage_app.manage(uninstall=True, purge=True)
                        run.assert_not_called()
                        self.assertTrue(primary.exists())
                    else:
                        manage_app.manage(uninstall=True, purge=True)
                        self.assertFalse(primary.exists() or fallback.exists())
                        recovered = [p.read_text() for p in (home / '.Trash').rglob('config.json')]
                        self.assertEqual(set(recovered), {'{"revision": 1}', '{"revision": 8}'})

    @unittest.skipUnless(sys.platform == 'darwin', 'AppKit requires macOS')
    def test_native_menu_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'native-menu-test'
            subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library', '-D', 'MENU_TESTING',
                            '-module-cache-path', str(ROOT / 'build/swift-cache'),
                            str(ROOT / 'native/PadPilot.swift'), str(ROOT / 'native/Settings.swift'), str(ROOT / 'native/ConnectionHotKey.swift'), str(ROOT / 'tests/native_menu.swift'),
                            '-o', str(binary)], check=True, capture_output=True)
            fixture = Path(directory) / 'menu.json'
            device = {'name': 'Test | --exit " iPad', 'sidecar_uuid': '11111111-1111-4111-8111-111111111111'}
            try:
                for language in ('zh-Hant', 'en', 'ja'):
                    config = {'language': language, 'ipad': device, 'paired_ipads': [device]}
                    status = {'configured_ipad': device, 'actual': {'timestamp': 1000, 'sidecar_devices': []}}
                    fixture.write_text(json.dumps(render(status, config, True, now=1000, service_running=True)))
                    result = subprocess.run([str(binary), str(fixture)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('PASS:', result.stdout)
            finally:
                set_language('zh-Hant')

    @unittest.skipUnless(sys.platform == 'darwin', 'AppKit requires macOS')
    def test_native_launch_and_reopen(self):
        from check_gui_layout import fixtures
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contents = root / 'LaunchChecks.app/Contents'
            (contents / 'MacOS').mkdir(parents=True)
            (contents / 'Resources').mkdir()
            (root / 'bin').mkdir()
            (contents / 'Info.plist').write_bytes(plistlib.dumps({
                'CFBundleIdentifier': 'com.padpilot.launch-checks', 'CFBundleExecutable': 'LaunchChecks',
                'CFBundlePackageType': 'APPL', 'LSUIElement': True,
            }))
            (contents / 'Resources/runtime.json').write_text(json.dumps({'python': sys.executable, 'project_root': str(root)}))
            (root / 'gui.json').write_text(json.dumps(fixtures()['zh-Hant']))
            (root / 'bin/padpilot-cli').write_text('''import json, sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
with (Path.home() / "commands.jsonl").open("a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "gui-data": print((root / "gui.json").read_text())
elif sys.argv[1] == "menu-json": print(json.dumps({"schema_version": 1, "hidden": False, "icon": "ipad", "items": []}))
elif sys.argv[1:] == ["start", "--no-menu"]: print("{}")
else: sys.exit(1)
''')
            binary = contents / 'MacOS/LaunchChecks'
            subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-parse-as-library', '-D', 'MENU_TESTING',
                            '-module-cache-path', str(ROOT / 'build/swift-cache'),
                            str(ROOT / 'native/PadPilot.swift'), str(ROOT / 'native/Settings.swift'), str(ROOT / 'native/ConnectionHotKey.swift'),
                            str(ROOT / 'tests/native_launch.swift'), '-o', str(binary)], check=True, capture_output=True)
            for arguments in ([], ['--menu-only']):
                home = root / ('background' if arguments else 'foreground')
                home.mkdir()
                result = subprocess.run([str(binary), *arguments], env={**os.environ, 'HOME': str(home)},
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stderr)
                commands = [json.loads(line) for line in (home / 'commands.jsonl').read_text().splitlines()]
                self.assertEqual(commands.count(['start', '--no-menu']), 1)
                self.assertTrue(all(command[0] in {'start', 'gui-data', 'menu-json'} for command in commands))

    def test_app_ownership_requires_matching_bundle_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'PadPilot.app'
            contents = app / 'Contents'
            (contents / 'Resources').mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.app'}))
            runtime = contents / 'Resources/runtime.json'
            runtime.write_text(json.dumps({'project_root': str(ROOT), 'python': sys.executable}))
            self.assertTrue(manage_app.owned_app(app))
            runtime.write_text(json.dumps({'project_root': '/another/checkout'}))
            self.assertFalse(manage_app.owned_app(app))

    def test_uninstall_preserves_foreign_shortcut_and_user_data(self):
        for target in ('installed', 'source', 'foreign'):
            with tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                shortcut = home / 'bin/padpilot-cli'
                shortcut.parent.mkdir()
                launcher = home / 'Applications/PadPilot.app/Contents/Resources/padpilot-cli'
                shortcut.symlink_to({'installed': launcher, 'source': ROOT / 'bin/padpilot-cli',
                                     'foreign': home / 'another-cli'}[target])
                own_link = target == 'installed'
                user_data = home / 'Library/Application Support/PadPilot'
                user_data.mkdir(parents=True)
                (user_data / 'config.json').write_text('keep')
                with patch('pathlib.Path.home', return_value=home), \
                     patch.object(manage_app, 'installation_service', return_value='notRegistered'), patch.object(manage_app, 'service_command', return_value='notRegistered'), \
                     patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), \
                     patch.object(manage_app.subprocess, 'run') as run:
                    manage_app.manage(uninstall=True)
                self.assertEqual(shortcut.is_symlink(), not own_link)
                self.assertEqual((user_data / 'config.json').read_text(), 'keep')
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-1], 'exit')
                # Python 3.10's literal glob skips dangling links; inspect the link itself.
                trash = home / '.Trash'
                moved = [directory / shortcut.name for directory in trash.iterdir()] if trash.is_dir() else []
                self.assertEqual(any(path.is_symlink() and path.readlink() == launcher for path in moved), own_link)


if __name__ == '__main__':
    unittest.main()
