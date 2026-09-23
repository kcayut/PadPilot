"""App discovery and setup use isolated bundles, never the installed App."""
import contextlib
import io
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime
from core.betterdisplay import BetterDisplayCLI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import manage_app


class AppPathTests(unittest.TestCase):
    def setUp(self):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.home = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.source = self.home / 'source'
        self.source.mkdir()
        self.system = self.home / 'system/SidecarSwitch.app'
        self.user = self.home / 'Applications/SidecarSwitch.app'
        self.build = self.source / 'build/SidecarSwitch.app'
        self.receipt = self.home / 'Library/Application Support/SidecarSwitch/login-service.json'
        stack.enter_context(patch.object(Path, 'home', return_value=self.home))
        stack.enter_context(patch.object(runtime, 'ROOT', self.source))
        stack.enter_context(patch.object(runtime, 'SYSTEM_APP', self.system))

    def app(self, path, root=None):
        resources = path / 'Contents/Resources'
        resources.mkdir(parents=True, exist_ok=True)
        (resources / 'runtime.json').write_text(json.dumps({
            'project_root': str(root or self.source), 'python': sys.executable, 'locator': 1}))
        (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.sidecarswitch.app',
            'CFBundleURLTypes': [{'CFBundleURLSchemes': ['sidecarswitch']}]}))
        helper = path / 'Contents/MacOS/SidecarSwitch'
        helper.parent.mkdir(exist_ok=True)
        helper.touch()
        return path

    def owner(self, app):
        self.receipt.parent.mkdir(parents=True, exist_ok=True)
        self.receipt.write_text(json.dumps({'app': str(app)}))

    def test_installed_locations_build_fallback_and_source_validation(self):
        self.app(self.build)
        self.assertEqual(runtime.find_app(), self.build)
        self.assertIsNone(runtime.find_app(include_build=False))
        self.owner(self.build)
        self.assertIsNone(runtime.find_app(include_build=False))
        self.app(self.system, root=self.home / 'another-source')
        self.assertEqual(runtime.find_app(), self.build)
        self.app(self.user)
        self.assertEqual(runtime.find_app(settings=True), self.user)
        self.receipt.unlink()
        self.app(self.system)
        with self.assertRaisesRegex(RuntimeError, 'Multiple'):
            runtime.find_app()
        self.owner(self.user)
        self.assertEqual(runtime.find_app(), self.user)
        self.owner(self.system)
        self.assertEqual(runtime.find_app(include_build=False), self.system)
        # A current release uses its own bundle, regardless of other copies.
        bundled_root = self.system / 'Contents/Resources/SidecarSwitch'
        self.assertEqual(runtime.find_app(bundled_root), self.system)

    def test_stale_receipt_recovers_without_rewriting_and_unsafe_receipt_fails(self):
        self.app(self.system)
        self.owner(self.home / 'removed/SidecarSwitch.app')
        before = self.receipt.read_bytes(), self.receipt.stat().st_mtime_ns
        self.assertEqual(runtime.find_app(), self.system)
        self.assertEqual((self.receipt.read_bytes(), self.receipt.stat().st_mtime_ns), before)
        self.receipt.unlink()
        self.receipt.symlink_to(self.home / 'missing')
        with self.assertRaises(RuntimeError):
            runtime.find_app()

    def test_uninstalled_lookup_does_not_create_state_or_accept_app_symlink(self):
        self.assertIsNone(runtime.find_app())
        self.assertFalse(self.receipt.parent.exists())
        self.app(self.home / 'elsewhere/SidecarSwitch.app')
        self.system.parent.mkdir(parents=True)
        self.system.symlink_to(self.home / 'elsewhere/SidecarSwitch.app')
        self.assertIsNone(runtime.find_app())

    def test_betterdisplay_locator_uses_installed_app_without_a_build(self):
        self.app(self.system)
        renamed = self.home / 'Utilities/Display Tool.app'
        renamed.mkdir(parents=True)
        original = Path.is_dir
        def is_dir(path):
            if path.name == 'BetterDisplay.app':
                return False
            return original(path)
        with patch.object(Path, 'is_dir', is_dir), patch('core.betterdisplay.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, str(renamed), '')) as launch:
            self.assertEqual(BetterDisplayCLI.resolve_app_path(), str(renamed))
        self.assertEqual(launch.call_args.args[0],
                         [str(self.system / 'Contents/MacOS/SidecarSwitch'), '--locate-betterdisplay'])

    def test_update_and_uninstall_keep_registered_location(self):
        self.app(self.system)
        self.app(self.user)  # A second copy must be left alone.
        self.owner(self.system)
        (self.system / 'version').write_text('old')
        from core.config import Config
        cfg = Config()
        def build(path):
            self.app(path)
            (path / 'version').write_text('new')
        with patch.object(manage_app, 'ROOT', self.source), \
             patch.object(manage_app, 'build', side_effect=build), \
             patch.object(manage_app, 'load_config', return_value=cfg), \
             patch.object(manage_app, 'installation_service', return_value='enabled') as inspect, \
             patch.object(manage_app, 'service_command', return_value='enabled') as service, \
             patch.object(manage_app, 'ensure_settings_closed'), \
             patch.object(manage_app, 'stop_menu_apps') as stop, \
             patch.object(manage_app, 'daemon_pids', return_value=[]), \
             patch.object(manage_app.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             contextlib.redirect_stdout(io.StringIO()):
            manage_app.manage()
            self.assertEqual((self.system / 'version').read_text(), 'new')
            self.assertTrue(self.user.exists())
            inspect.assert_called_with(self.system)
            stop.assert_called_with([self.system])
            self.assertTrue(all(call.kwargs.get('app', call.args[1] if len(call.args) > 1 else self.system)
                                == self.system for call in service.call_args_list))
            manage_app.manage(uninstall=True)
            self.assertFalse(self.system.exists())
            self.assertTrue(self.user.exists())
            self.assertEqual(len(list((self.home / '.Trash').glob('*/SidecarSwitch.app'))), 2)

    def test_stop_menu_targets_resolved_app(self):
        self.app(self.system)
        with patch.object(manage_app, 'ROOT', self.source), patch.object(manage_app.subprocess, 'run',
                return_value=subprocess.CompletedProcess([], 1)) as query:
            manage_app.stop_menu_apps()
        self.assertIn('system/SidecarSwitch', query.call_args.args[0][-1])

    @unittest.skipUnless(sys.platform == 'darwin', 'Uses macOS plutil')
    def test_shell_bootstrap_uses_system_or_registered_python(self):
        self.app(self.system)
        helper = self.home / 'source_runtime.sh'
        helper.write_text((ROOT / 'scripts/source_runtime.sh').read_text().replace(
            ' /Applications/SidecarSwitch.app ', f' "{self.system}" '))
        custom = self.home / 'Other Apps/SidecarSwitch.app'
        for app in (self.system, self.app(custom)):
            with self.subTest(app=app):
                if app == custom:
                    self.owner(app)
                command = 'source "$1"; valid_python() { [[ -x "$1" ]]; }; source_python'
                result = subprocess.run(['/bin/bash', '-c', command, 'test', str(helper)],
                    env={**os.environ, 'HOME': str(self.home), 'PROJECT_ROOT': str(self.source)},
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), sys.executable)
        self.assertFalse((self.receipt.parent / 'config.json').exists())


if __name__ == '__main__':
    unittest.main()
