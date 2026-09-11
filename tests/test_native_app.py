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
    def test_new_user_install_persists_login_startup_and_opens_installed_menu(self):
        start = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))['cmd_start']
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve()
            source = home / 'source checkout'
            (source / 'assets/menu-icons').mkdir(parents=True)
            for name in ('LICENSE', 'NOTICE'):
                (source / name).write_text('test package resource')
            support = home / 'Library/Application Support/PadPilot'
            configuration = support / 'config.json'
            agents = home / 'Library/LaunchAgents'
            plist = agents / 'com.padpilot.daemon.plist'
            app = home / 'Applications/PadPilot.app'
            open_menu = ['open', '-g', '-a', str(app), 'padpilot://menu', '--args', '--menu-only']
            python = str(home / 'Python runtime/python3')
            cli = [python, str(source / 'bin/padpilot-cli')]
            commands = []

            def run(command, **kwargs):
                commands.append(command)
                if command == cli + ['start']:
                    start(argparse.Namespace(no_menu=False))
                elif command == cli + ['exit']:
                    pass  # No prior daemon exists in this isolated user's home.
                elif command[0] not in ('xcrun', 'codesign'):
                    self.assertIn(command, (['launchctl', 'load', str(plist)], open_menu))
                return subprocess.CompletedProcess(command, 0)

            with contextlib.ExitStack() as stack:
                for context in (
                    patch('pathlib.Path.home', return_value=home),
                    patch.object(sys, 'executable', python), patch.object(sys, 'platform', 'darwin'),
                    patch.object(build_app, 'ROOT', source), patch.object(build_app, 'build_icon'),
                    patch.object(manage_app, 'ROOT', source),
                    patch.object(manage_app, 'job_loaded', return_value=False),
                    patch.object(manage_app, 'daemon_pids', return_value=[]),
                    patch.object(manage_app, 'ensure_settings_closed'), patch.object(manage_app, 'stop_menu_apps'),
                    patch.object(config, 'CONFIG_FILE', configuration),
                    patch.object(config, 'FALLBACK_CONFIG_FILE', home / 'fallback/config.json'),
                    patch.object(config, 'detect_system_language', return_value='en'), patch.object(config.logger, 'info'),
                    patch.object(autostart, 'PROJECT_ROOT', source),
                    patch.object(autostart, 'USER_LAUNCH_AGENTS_DIR', agents),
                    patch.object(autostart, 'job_loaded', return_value=False),
                    patch.object(autostart, 'is_daemon_running', return_value=False),
                    patch.object(autostart, 'stop_daemon'), patch.object(autostart, 'wait_for_daemon'),
                    patch.dict(start.__globals__, daemon_pids=lambda: [], remove_state_file=lambda _: None),
                    patch.object(subprocess, 'run', side_effect=run),
                    patch.object(subprocess, 'Popen', side_effect=AssertionError('Unexpected process launch')),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    stack.enter_context(context)
                self.assertFalse(configuration.exists())
                self.assertIs(config.Config().autostart_on_login, True)
                manage_app.manage()

            saved = json.loads(configuration.read_text())
            self.assertIs(saved['autostart_on_login'], True)
            installed = plistlib.loads(plist.read_bytes())
            self.assertIs(installed['RunAtLoad'], True)
            self.assertIs(installed['KeepAlive'], True)
            self.assertEqual(installed['ProgramArguments'], [python, str(source / 'bin/padpilotd')])
            runtime = json.loads((app / 'Contents/Resources/runtime.json').read_text())
            self.assertEqual(runtime, {'python': python, 'project_root': str(source), 'locator': 1})
            self.assertEqual([command for command in commands if command[:2] == cli],
                             [cli + ['exit'], cli + ['start']])
            self.assertEqual(commands.count(['launchctl', 'load', str(plist)]), 1)
            self.assertEqual(commands[-1], open_menu)
            self.assertEqual((home / 'bin/padpilot-cli').resolve(), app / 'Contents/Resources/padpilot-cli')

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
                            str(ROOT / 'native/PadPilot.swift'), str(ROOT / 'native/Settings.swift'), str(ROOT / 'tests/native_menu.swift'),
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
                            str(ROOT / 'native/PadPilot.swift'), str(ROOT / 'native/Settings.swift'),
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
