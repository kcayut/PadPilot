"""Native AppKit contract and recoverable setup checks; never operate displays."""
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
from core.menu import render
from core.i18n import set_language


class NativeAppTests(unittest.TestCase):
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
                self.assertTrue(any((home / '.Trash').rglob('padpilot.30s.py')))
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


if __name__ == '__main__':
    unittest.main()
