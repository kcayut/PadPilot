"""Regressions from the final preview review; all services and hardware are mocked."""
import ctypes
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import config, gui, menu
from core.betterdisplay import BetterDisplayCLI
from core.detector import DisplayDetector
from core.models import DisplayInfo, DisplayRole, IpadConfig, OperationMode, UserOverride
from core.state_engine import StateEngine
from core.storage import atomic_write, latest_state_path, UnsafePathError


class ReleaseRepairsTests(unittest.TestCase):
    def test_fallback_write_is_read_by_config_gui_and_menu_then_primary_recovers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, fallback = root / 'primary/config.json', root / 'fallback/config.json'
            old = config.Config(revision=1, mode=OperationMode.MANUAL_ONLY)
            new = config.Config(revision=2, mode=OperationMode.PREFER_IPAD)
            atomic_write(primary, json.dumps(old.to_dict()).encode())
            os.utime(primary, ns=(1, 1))
            def write(path, content):
                if path == primary:
                    raise PermissionError('simulated write failure')
                atomic_write(path, content)
            with patch.object(config, 'CONFIG_FILE', primary), patch.object(config, 'FALLBACK_CONFIG_FILE', fallback):
                with patch.object(config, 'atomic_write', side_effect=write):
                    config.save_config(new)
                self.assertEqual(config.load_config().revision, 2)
                self.assertEqual(config.get_config_file_path(), fallback)
                with patch.object(gui, 'read_status', return_value={}):
                    self.assertEqual(gui.read_view()['config'].revision, 2)
                self.assertEqual(menu.load_json(primary, fallback)['revision'], 2)
                os.utime(fallback, ns=(2, 2))
                new.revision = 3
                config.save_config(new)
                self.assertEqual(config.load_config().revision, 3)
                self.assertEqual(config.get_config_file_path(), primary)

    def test_status_readers_choose_fallback_and_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            primary, fallback = root / 'primary/runtime/status.json', root / 'fallback/runtime/status.json'
            atomic_write(primary, b'{"status_revision": 9}')
            os.utime(primary, ns=(1, 1))
            atomic_write(fallback, b'{"status_revision": 1}')  # A restarted daemon resets revisions.
            with patch.object(config, 'STATUS_FILE', primary), patch.object(config, 'FALLBACK_DIR', fallback.parent.parent):
                self.assertEqual(config.read_status()['status_revision'], 1)
                self.assertEqual(config.get_status_file_path(), fallback)
                self.assertEqual(menu.load_json(primary, fallback)['status_revision'], 1)
            fallback.unlink()
            fallback.symlink_to(primary)
            with self.assertRaises(UnsafePathError):
                latest_state_path(primary, fallback)

    def test_invalid_config_never_applies_defaults_or_overwrites_original(self):
        invalid = ['{broken', '[]', '{"ipad": null}', '{"paired_ipads": [null]}',
                   '{"mode": "typo"}', '{"auto_detect_ipad": "false"}',
                   '{"retry_interval": -1}', '{"cooldown_seconds": NaN}',
                   '{"max_retries": 1.5}', '{"ignore_list": [null]}']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'config.json'
            with patch.object(config, 'CONFIG_FILE', path), patch.object(config, 'FALLBACK_CONFIG_FILE', root / 'absent'), \
                 patch.object(gui, 'read_status', return_value={}), patch.object(gui, 'BetterDisplayCLI') as hardware:
                for content in invalid:
                    atomic_write(path, content.encode())
                    with self.subTest(content=content), self.assertRaisesRegex(ValueError, 'Repair or restore'):
                        config.load_config()
                    view = gui.read_view(scan=True)
                    self.assertTrue(view['config_error'])
                    self.assertEqual(view['config'].mode, OperationMode.MANUAL_ONLY)
                    self.assertFalse(view['config'].auto_detect_ipad)
                    self.assertEqual(path.read_text(), content)
                hardware.assert_not_called()


    def test_identifier_recovery_does_not_erase_an_incomplete_observation(self):
        cfg = config.Config(auto_detect_ipad=False)
        bd = BetterDisplayCLI.__new__(BetterDisplayCLI)
        bd.is_available = lambda: True
        identifiers = [{'displayID': '5', 'name': 'Capture Monitor', 'deviceType': 'Display'}]
        bd.run_cmd = MagicMock(side_effect=[(1, '', 'timeout'), (0, json.dumps(identifiers), '')])
        bd.get_sidecar_list = lambda: []
        detector = DisplayDetector(cfg, bd)
        detector.parse_usb_devices = lambda: []
        cg = MagicMock()
        def online(maximum, displays, count):
            displays[0] = 5
            ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32))[0] = 1
            return 0
        cg.CGGetOnlineDisplayList.side_effect = online
        for method, value in [('CGDisplayIsActive', 1), ('CGDisplayIsMain', 1), ('CGDisplayIsBuiltin', 0),
                              ('CGDisplayPixelsWide', 1920), ('CGDisplayPixelsHigh', 1080),
                              ('CGDisplayVendorNumber', 123), ('CGDisplayModelNumber', 456)]:
            getattr(cg, method).return_value = value
        detector._cg = cg
        engine = StateEngine(cfg, detector, bd)
        engine.runtime.last_topology_signature = ((), False)
        override = UserOverride(DisplayRole.IPAD_DISCONNECTED, 0)
        engine.runtime.user_override = override
        engine._export_status = MagicMock()
        engine.evaluate(async_transition=False)
        self.assertEqual(engine.actual.discovery_errors['identifiers'], 'timeout')
        self.assertEqual(engine.runtime.topology_generation, 0)
        self.assertIs(engine.runtime.user_override, override)
        self.assertEqual(engine.desired.target_display_role, DisplayRole.NO_CHANGE)

    def test_unknown_sidecar_identity_preserves_display_and_never_guesses(self):
        cfg = config.Config(ipad=IpadConfig('Custom label', 'session-a'))
        bd = MagicMock(sidecar_error='', identifiers_error='', connection_error='')
        bd.get_sidecar_list.return_value = []
        bd.get_sidecar_connected.return_value = True
        bd.check_virtual_display.return_value = (True, True)
        detector = DisplayDetector(cfg, bd)
        detector.parse_usb_devices = lambda: []
        engine = StateEngine(cfg, detector, bd)
        engine._export_status = MagicMock()
        for name in ('Other iPad', 'Custom label'):
            with self.subTest(name=name):
                detector.get_online_displays = lambda: [DisplayInfo(5, name, uuid='display-b', is_sidecar=True)]
                engine.evaluate(async_transition=False)
                self.assertIn('sidecar_identity', engine.actual.discovery_errors)
                self.assertEqual(engine.desired.target_display_role, DisplayRole.NO_CHANGE)
        bd.set_main_display.assert_not_called()
        bd.connect_sidecar.assert_not_called()

    def test_virtual_creation_hint_uses_configured_name(self):
        bd = BetterDisplayCLI.__new__(BetterDisplayCLI)
        bd.capabilities = MagicMock(virtual_creation_supported=False)
        bd.check_virtual_display = lambda name: (False, False)
        ok, message = bd.ensure_virtual_display('Recovery Screen')
        self.assertFalse(ok)
        self.assertIn("named 'Recovery Screen'", message)
        self.assertNotIn('{name}', message)


    def test_native_settings_transport_preserves_revision_and_reports_conflicts(self):
        import subprocess
        result = subprocess.CompletedProcess([], 0, 'OK: saved', '')
        with patch.object(gui.subprocess, 'run', return_value=result) as run:
            for revision in (7, 4):
                payload = {'enabled': True, '__expected_revision__': revision}
                original = dict(payload)
                self.assertEqual(gui.send_change('set_auto_detect_ipad', payload), 'OK: saved')
                self.assertEqual(json.loads(run.call_args.kwargs['input']), original)
                self.assertEqual(payload, original)
                self.assertEqual(run.call_args.args[0][-2:], ['change-settings', 'set_auto_detect_ipad'])
            result.returncode, result.stderr = 1, 'CONFIG_CONFLICT: stale revision'
            with self.assertRaisesRegex(RuntimeError, 'CONFIG_CONFLICT'):
                gui.send_change('set_auto_detect_ipad', {'enabled': True, '__expected_revision__': 4})


if __name__ == '__main__':
    unittest.main()
