"""Native AppKit contract and recoverable setup checks; never operate displays."""
import contextlib
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import manage_app
from core import autostart, config
from core.menu import render
from core.i18n import set_language


class NativeAppTests(unittest.TestCase):
    def test_install_failure_restores_app_and_previous_service_state(self):
        for loaded, running in ((True, True), (False, True), (False, False)):
            with self.subTest(loaded=loaded, running=running), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                source = home / 'source'
                built = source / 'build/PadPilot.app'
                built.mkdir(parents=True)
                (built / 'version').write_text('new')
                app = home / 'Applications/PadPilot.app'
                app.mkdir(parents=True)
                (app / 'version').write_text('old')
                plist = home / 'daemon.plist'
                original = autostart.generate_plist_content().encode()
                plist.write_bytes(original)
                cfg = config.Config(autostart_on_login=loaded)
                state = {'loaded': loaded, 'running': running, 'starts': 0}
                def stop(*args):
                    state.update(loaded=False, running=False)
                def standalone():
                    state['running'] = True
                def run(command, **kwargs):
                    if command[-1] == 'exit':
                        stop()
                    elif command[0] == 'launchctl':
                        state.update(loaded=True, running=True)
                    elif command[-1] == 'start':
                        state['starts'] += 1
                        if state['starts'] == 1:
                            if loaded:
                                ok, _ = autostart.enable_autostart(plist_path=plist, log_dir=home / 'logs')
                                self.assertFalse(ok)
                            raise subprocess.CalledProcessError(1, command)
                        self.assertTrue(state['running'])
                        self.assertEqual((app / 'version').read_text(), 'old')
                    return subprocess.CompletedProcess(command, 0)
                with contextlib.ExitStack() as stack:
                    for context in (
                        patch('pathlib.Path.home', return_value=home), patch.object(manage_app, 'ROOT', source),
                        patch.object(manage_app, 'owned_app', return_value=True), patch.object(manage_app, 'build'),
                        patch.object(manage_app, 'get_launch_agent_plist_path', return_value=plist),
                        patch.object(manage_app, 'load_config', return_value=cfg),
                        patch.object(manage_app, 'job_loaded', side_effect=lambda _: state['loaded']),
                        patch.object(manage_app, 'daemon_pids', side_effect=lambda: [123] if state['running'] else []),
                        patch.object(manage_app, 'stop_daemon', side_effect=stop), patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'),
                        patch.object(manage_app, 'start_standalone', side_effect=standalone),
                        patch.object(manage_app, 'wait_for_daemon'), patch.object(manage_app.subprocess, 'run', side_effect=run),
                        patch.object(autostart, 'job_loaded', side_effect=lambda _: state['loaded']),
                        patch.object(autostart, 'is_daemon_running', side_effect=lambda: state['running']),
                        patch.object(autostart, 'load_config', return_value=cfg), patch.object(autostart, 'save_config'),
                        patch.object(autostart, 'stop_daemon', side_effect=stop),
                        patch.object(autostart, 'wait_for_daemon', side_effect=RuntimeError('failed new handshake')),
                    ):
                        stack.enter_context(context)
                    with self.assertRaisesRegex(RuntimeError, 'Previous app and service state restored'):
                        manage_app.manage()
                self.assertEqual((state['loaded'], state['running']), (loaded, running))
                self.assertEqual(plist.read_bytes(), original)
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
                     patch.object(manage_app, 'get_launch_agent_plist_path', return_value=home / 'missing.plist'), \
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
                            str(ROOT / 'native/PadPilot.swift'), str(ROOT / 'tests/native_menu.swift'),
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

    def test_migration_preserves_custom_plugins_and_trashes_only_owned_link(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            root = home / 'source & space'
            folder = home / 'Library/Application Support/SwiftBar/plugins'
            folder.mkdir(parents=True)
            plugin = folder / 'padpilot.30s.py'
            plugin.symlink_to(root / 'swiftbar/padpilot.30s.py')
            other = folder / 'unrelated.5s.sh'
            other.write_text('keep')
            with patch.object(manage_app, 'ROOT', root), patch('pathlib.Path.home', return_value=home):
                manage_app.retire_legacy_plugin()
                self.assertFalse(plugin.is_symlink())
                # The retired plugin is a dangling link; check the link itself.
                moved = [directory / plugin.name for directory in (home / '.Trash').iterdir()]
                self.assertTrue(any(path.is_symlink() and path.readlink() == root / 'swiftbar/padpilot.30s.py'
                                    for path in moved))
                self.assertEqual(other.read_text(), 'keep')
                plugin.write_text('custom plugin')
                manage_app.retire_legacy_plugin()
                self.assertEqual(plugin.read_text(), 'custom plugin')

    def test_app_ownership_requires_matching_bundle_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'PadPilot.app'
            contents = app / 'Contents'
            (contents / 'Resources').mkdir(parents=True)
            (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.app'}))
            runtime = contents / 'Resources/runtime.json'
            runtime.write_text(json.dumps({'project_root': str(ROOT)}))
            self.assertTrue(manage_app.owned_app(app))
            runtime.write_text(json.dumps({'project_root': '/another/checkout'}))
            self.assertFalse(manage_app.owned_app(app))

    def test_uninstall_preserves_foreign_shortcut_and_user_data(self):
        for own_link in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                shortcut = home / 'bin/padpilot-cli'
                shortcut.parent.mkdir()
                shortcut.symlink_to(ROOT / 'bin/padpilot-cli' if own_link else home / 'another-cli')
                user_data = home / 'Library/Application Support/PadPilot'
                user_data.mkdir(parents=True)
                (user_data / 'config.json').write_text('keep')
                with patch('pathlib.Path.home', return_value=home), \
                     patch.object(manage_app, 'get_launch_agent_plist_path', return_value=home / 'missing.plist'), \
                     patch.object(manage_app, 'stop_menu_apps'), patch.object(manage_app, 'ensure_settings_closed'), \
                     patch.object(manage_app.subprocess, 'run') as run:
                    manage_app.manage(uninstall=True)
                self.assertEqual(shortcut.is_symlink(), not own_link)
                self.assertEqual((user_data / 'config.json').read_text(), 'keep')
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-1], 'exit')
                self.assertEqual(bool(list((home / '.Trash').glob('*/padpilot-cli'))), own_link)


if __name__ == '__main__':
    unittest.main()
