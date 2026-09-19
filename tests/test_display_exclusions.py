"""Display exclusions keep hardware identity and shared settings transactions intact."""
import contextlib
import ctypes
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config, load_config, save_config
from core.detector import DisplayDetector
from core.models import DisplayInfo, DisplayRole, IpadConfig, OperationMode
from core.settings import apply_change
from core.state_engine import StateEngine

ROOT = Path(__file__).resolve().parents[1]
ONE = 'ABCDEF01-1111-4111-8111-111111111111'
TWO = 'ABCDEF02-2222-4222-8222-222222222222'


class DisplayExclusionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(mode=OperationMode.AUTOMATIC, auto_detect_ipad=False,
                          ipad=IpadConfig('iPad', 'SESSION'))
        self.bd = MagicMock(spec=BetterDisplayCLI)
        for field in ('identifiers_error', 'sidecar_error', 'connection_error'):
            setattr(self.bd, field, '')
        self.bd.check_virtual_display.return_value = (True, True)
        self.bd.get_sidecar_list.return_value = []
        self.bd.get_sidecar_connected.return_value = False
        with patch.object(DisplayDetector, '_init_coregraphics', return_value=None):
            self.detector = DisplayDetector(self.cfg, self.bd)

    def observe(self, *displays):
        with patch.object(self.detector, 'get_online_displays', return_value=list(displays)), \
             patch.object(self.detector, 'parse_usb_devices', return_value=[]):
            return self.detector.observe()[0]

    def test_generic_default_stays_visible_and_override_prevents_virtual_main(self):
        monitor = DisplayInfo(7, 'Generic', uuid=ONE.lower(), is_main=True, width=1920, height=1080)
        actual = self.observe(monitor)
        self.assertEqual(actual.physical_displays, [])
        self.assertEqual(actual.online_displays, [monitor])
        self.assertTrue(monitor.excluded_from_physical_detection)
        self.assertFalse(monitor.is_virtual)

        self.cfg.display_exclusions[ONE] = False
        engine = StateEngine(self.cfg, self.detector, self.bd)
        with patch.object(self.detector, 'get_online_displays', return_value=[monitor]), \
             patch.object(self.detector, 'parse_usb_devices', return_value=[]), \
             patch.object(engine, '_export_status'):
            engine.evaluate(async_transition=False)
        self.assertEqual(engine.actual.physical_displays, [monitor])
        self.assertFalse(monitor.excluded_from_physical_detection)
        self.assertEqual(engine.desired.target_display_role, DisplayRole.PHYSICAL)
        self.bd.set_main_display.assert_not_called()
        self.bd.connect_virtual_display.assert_not_called()
        self.bd.connect_sidecar.assert_not_called()

    def test_virtual_in_real_monitor_name_does_not_change_hardware_type(self):
        cg = MagicMock()
        def online(_maximum, ids, count):
            ids[0] = 7
            ctypes.cast(count, ctypes.POINTER(ctypes.c_uint32))[0] = 1
            return 0
        cg.CGGetOnlineDisplayList.side_effect = online
        cg.CGDisplayIsActive.return_value = cg.CGDisplayIsMain.return_value = 1
        cg.CGDisplayIsBuiltin.return_value = 0
        cg.CGDisplayPixelsWide.return_value = 1920
        cg.CGDisplayPixelsHigh.return_value = 1080
        cg.CGDisplayVendorNumber.return_value = 4268
        cg.CGDisplayModelNumber.return_value = 100
        self.detector._cg = cg
        self.bd.get_display_identifiers.return_value = [
            {'displayID': 7, 'name': 'Virtual Studio Monitor', 'UUID': ONE,
             'deviceType': 'Display', 'vendor': '4268'}]
        self.cfg.display_exclusions[ONE] = False
        with patch.object(self.detector, 'parse_usb_devices', return_value=[]):
            actual, _ = self.detector.observe()
        self.assertEqual(len(actual.physical_displays), 1)
        self.assertFalse(actual.physical_displays[0].is_virtual)
        self.assertFalse(actual.physical_displays[0].excluded_from_physical_detection)

    def test_namesakes_use_independent_uuids_and_excluded_display_remains_online(self):
        one = DisplayInfo(1, 'Same Monitor', uuid=ONE)
        two = DisplayInfo(2, 'Same Monitor', uuid=TWO)
        self.cfg.display_exclusions = {ONE: True, TWO: False}
        actual = self.observe(one, two)
        self.assertEqual(actual.physical_displays, [two])
        self.assertEqual(actual.online_displays, [one, two])
        self.assertTrue(one.excluded_from_physical_detection)
        self.assertFalse(two.excluded_from_physical_detection)
        self.assertFalse(one.is_virtual)
        self.assertTrue(actual.to_dict()['online_displays'][0]['excluded_from_physical_detection'])

    def test_saved_override_cannot_turn_virtual_or_sidecar_into_physical(self):
        self.cfg.display_exclusions = {ONE: False, TWO: False}
        virtual = DisplayInfo(1, 'Recovery', uuid=ONE, is_virtual=True)
        ipad = DisplayInfo(2, 'iPad', uuid=TWO, is_sidecar=True)
        actual = self.observe(virtual, ipad)
        self.assertEqual(actual.physical_displays, [])
        self.assertEqual(actual.online_displays, [virtual, ipad])
        self.assertTrue(virtual.is_virtual)
        self.assertTrue(ipad.is_sidecar)

    def test_settings_persist_across_reload_and_null_restores_automatic_detection(self):
        monitor = DisplayInfo(1, 'Generic', uuid=ONE)
        with patch('core.settings.DisplayDetector') as detector:
            detector.return_value.get_online_displays.return_value = [monitor]
            detector.return_value.display_error = ''
            payload = {'uuid': ONE.lower(), 'excluded': False}
            self.assertTrue(apply_change(self.cfg, 'set_display_exclusion', payload, self.bd))
            self.assertFalse(apply_change(self.cfg, 'set_display_exclusion', payload, self.bd))
            with tempfile.TemporaryDirectory() as directory:
                primary, fallback = Path(directory) / 'config.json', Path(directory) / 'fallback.json'
                with patch('core.config.CONFIG_FILE', primary), patch('core.config.FALLBACK_CONFIG_FILE', fallback):
                    save_config(self.cfg)
                    restored = load_config()
                self.assertEqual(json.loads(primary.read_text())['display_exclusions'], {ONE: False})
            self.assertEqual(restored.display_exclusions, {ONE: False})
            self.detector.config = restored
            self.assertEqual(self.observe(monitor).physical_displays, [monitor])
            self.assertTrue(apply_change(restored, 'set_display_exclusion', {'uuid': ONE, 'excluded': None}, self.bd))
            self.assertEqual(restored.display_exclusions, {})
            self.assertEqual(self.observe(monitor).physical_displays, [])

    def test_config_rejects_malformed_overrides_and_normalizes_uuid(self):
        self.assertEqual(Config.from_dict({'display_exclusions': {ONE.lower(): False}}).display_exclusions,
                         {ONE: False})
        for invalid in ([], None, {'invalid': True}, {ONE: None}, {ONE: 0}, {ONE: 'false'}):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                Config.from_dict({'display_exclusions': invalid})

    def test_setting_rejects_invalid_payload_and_unverified_hardware_without_mutation(self):
        monitor = DisplayInfo(1, 'Monitor', uuid=ONE)
        with patch('core.settings.DisplayDetector') as detector:
            detector.return_value.get_online_displays.return_value = [monitor]
            detector.return_value.display_error = ''
            invalid = ({}, {'uuid': 'invalid', 'excluded': True}, {'uuid': ONE, 'excluded': 1},
                       {'uuid': ONE, 'excluded': 'false'}, {'uuid': ONE, 'excluded': True, 'extra': 1})
            for payload in invalid:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    apply_change(self.cfg, 'set_display_exclusion', payload, self.bd)
            for displays in ([], [monitor, monitor],
                             [DisplayInfo(1, 'Virtual', uuid=ONE, is_virtual=True)],
                             [DisplayInfo(1, 'iPad', uuid=ONE, is_sidecar=True)]):
                detector.return_value.get_online_displays.return_value = displays
                with self.subTest(displays=displays), self.assertRaises(ValueError):
                    apply_change(self.cfg, 'set_display_exclusion', {'uuid': ONE, 'excluded': False}, self.bd)
            detector.return_value.get_online_displays.return_value = [monitor]
            detector.return_value.display_error = 'query failed'
            with self.assertRaises(ValueError):
                apply_change(self.cfg, 'set_display_exclusion', {'uuid': ONE, 'excluded': True}, self.bd)
        self.assertEqual(self.cfg.display_exclusions, {})

    def test_daemon_and_offline_cli_share_validation_and_revision_updates(self):
        daemon_cls = runpy.run_path(str(ROOT / 'bin/padpilotd'))['PadPilotDaemon']
        daemon = daemon_cls.__new__(daemon_cls)
        daemon.config, daemon.bd_cli = self.cfg, self.bd
        daemon.detector, daemon.engine = MagicMock(), MagicMock()
        daemon.engine.run_control.side_effect = lambda action: action()
        payload = {'uuid': ONE, 'excluded': False}
        request = {'command': 'set_display_exclusion', 'params': payload, 'expected_revision': 1}
        with patch('core.settings.DisplayDetector') as detector:
            detector.return_value.get_online_displays.return_value = [DisplayInfo(1, 'Generic', uuid=ONE)]
            detector.return_value.display_error = ''
            with patch.dict(daemon_cls.handle_client_cmd.__globals__, save_config=MagicMock()) as namespace:
                response = json.loads(daemon.handle_client_cmd(json.dumps(request)))
                self.assertTrue(response['ok'])
                self.assertEqual(response['config_revision'], 2)
                self.assertEqual(daemon.config.display_exclusions, {ONE: False})
                self.assertEqual(namespace['save_config'].call_count, 1)
                self.assertEqual(json.loads(daemon.handle_client_cmd(json.dumps(request)))['error'], 'CONFIG_CONFLICT')
                request['expected_revision'] = 2
                self.assertTrue(json.loads(daemon.handle_client_cmd(json.dumps(request)))['ok'])
                self.assertEqual(namespace['save_config'].call_count, 1)

            submit = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))['submit_settings']
            offline = Config(revision=8)
            save = MagicMock()
            with patch.dict(submit.__globals__, send_daemon_cmd=MagicMock(return_value='Daemon is not running.'),
                            load_config=lambda: offline, save_config=save, BetterDisplayCLI=lambda *a: self.bd), \
                 contextlib.redirect_stdout(io.StringIO()):
                submit('set_display_exclusion', payload, expected_revision=8)
                self.assertEqual(offline.revision, 9)
                self.assertEqual(offline.display_exclusions, {ONE: False})
                save.assert_called_once_with(offline)
                with self.assertRaisesRegex(RuntimeError, 'CONFIG_CONFLICT'):
                    submit('set_display_exclusion', payload, expected_revision=8)


if __name__ == '__main__':
    unittest.main()
