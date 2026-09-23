"""UI commands share validated changes; confirmations never mutate before Yes."""
import contextlib
import io
import json
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config
from core.gui import read_view
from core.models import OperationMode, pairing_key
from core.settings import apply_change

ROOT = Path(__file__).resolve().parents[1]
MENU = runpy.run_path(str(ROOT/'core/menu.py'))
DAEMON = runpy.run_path(str(ROOT/'bin/sidecarswitchd'))
ONE = {'name': '同名 iPad', 'sidecar_uuid': '11111111-1111-4111-8111-111111111111', 'usb_serial': 'usb1'}
TWO = dict(ONE, sidecar_uuid='22222222-2222-4222-8222-222222222222', usb_serial='usb2')


class GuiSettingsTests(unittest.TestCase):
    def config(self):
        return Config.from_dict({'mode': 'automatic', 'ipad': ONE, 'paired_ipads': [ONE, TWO]})

    def test_delete_exact_profile_preserves_namesake_and_current_connection_policy(self):
        cfg = self.config()
        self.assertFalse(apply_change(cfg, 'delete_pairing', {'key': pairing_key(TWO)}))
        self.assertEqual(cfg.ipad.to_dict(), ONE)
        self.assertEqual(cfg.mode, OperationMode.AUTOMATIC)
        self.assertTrue(apply_change(cfg, 'delete_pairing', {'key': pairing_key(ONE)}))
        roundtrip = Config.from_dict(cfg.to_dict())
        self.assertEqual(roundtrip.paired_ipads, [])
        self.assertFalse(any(roundtrip.ipad.to_dict().values()))
        self.assertEqual(roundtrip.mode, OperationMode.MANUAL_ONLY)

    def test_stale_confirmation_cannot_delete_changed_profile(self):
        cfg = self.config()
        key = pairing_key(TWO)
        cfg.paired_ipads[1].name = 'Renamed'
        with self.assertRaises(ValueError):
            apply_change(cfg, 'delete_pairing', {'key': key})
        self.assertEqual(len(cfg.paired_ipads), 2)

    def test_virtual_choice_is_validated_against_current_hardware(self):
        cfg = self.config()
        bd = MagicMock(identifiers_error='')
        virtual = {'name': 'Recovery Screen', 'deviceType': 'VirtualScreen', 'displayID': '0'}
        bd.get_display_identifiers.return_value = [virtual, {'name': 'Real Monitor', 'deviceType': 'Display'}]
        self.assertTrue(apply_change(cfg, 'set_virtual_display', {'name': 'Recovery Screen'}, bd))
        self.assertEqual(Config.from_dict(cfg.to_dict()).virtual_display_name, 'Recovery Screen')
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_virtual_display', {'name': 'Real Monitor'}, bd)
        bd.get_display_identifiers.return_value += [dict(virtual, name='Recovery Screen 2')]
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_virtual_display', {'name': 'Recovery Screen'}, bd)
        bd.identifiers_error = 'timeout'
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_virtual_display', {'name': 'Recovery Screen'}, bd)


    def test_settings_page_is_interactive_and_read_view_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as d, patch('core.gui.get_config_file_path', return_value=Path(d)/'config.json'), \
             patch('core.gui.read_status', return_value=None):
            read_view()
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_menu_uses_gui_for_pairing_and_preserves_deleted_profiles(self):
        model = MENU['render']({}, self.config().to_dict(), True)
        rows = model['items']
        self.assertEqual(sum(r['title'] == '刪除配對' for r in rows), 2)
        for row in rows:
            if row['title'] in ('設定與配對', '刪除配對'):
                self.assertEqual(row['args'][0], 'gui')
        self.assertNotIn('開啟 BetterDisplay', [r['title'] for r in rows])
        model = MENU['render']({'paired_ipads': [ONE], 'configured_ipad': ONE},
                               {'ipad': {}, 'paired_ipads': []}, True)
        self.assertFalse(any('同名 iPad' in row['title'] for row in model['items']))

    def test_daemon_deleting_target_pauses_before_reevaluation(self):
        cls = DAEMON['SidecarSwitchDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
        obj.engine.run_control.side_effect = lambda action: action()
        cfg = self.config()
        with patch.dict(cls.handle_client_cmd.__globals__, {'load_config': lambda: cfg, 'save_config': MagicMock()}):
            response = obj.handle_client_cmd('delete_pairing:'+json.dumps({'key': pairing_key(ONE)}))
        self.assertTrue(response.startswith('OK:'))
        self.assertEqual(obj.engine.runtime.mode, OperationMode.MANUAL_ONLY)
        obj.engine.reset_automation.assert_called_once()

    def test_virtual_change_preserves_current_override(self):
        cls = DAEMON['SidecarSwitchDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
        obj.engine.run_control.side_effect = lambda action: action()
        obj.bd_cli = MagicMock(identifiers_error='')
        obj.bd_cli.get_display_identifiers.return_value = [{'name':'Alternate', 'deviceType':'VirtualScreen'}]
        override = obj.engine.runtime.user_override
        with patch.dict(cls.handle_client_cmd.__globals__, {'load_config': self.config, 'save_config': MagicMock()}):
            response = obj.handle_client_cmd('set_virtual_display:'+json.dumps({'name':'Alternate'}))
        self.assertTrue(response.startswith('OK:'))
        obj.engine.reset_automation.assert_not_called()
        self.assertIs(obj.engine.runtime.user_override, override)
    def test_set_betterdisplaycli_path_validation_and_apply(self):
        cfg = self.config()
        with patch('core.settings.BetterDisplayCLI.resolve_cli_path', return_value='/opt/homebrew/bin/betterdisplaycli'):
            self.assertTrue(apply_change(cfg, 'set_betterdisplaycli_path', {'path': '/opt/homebrew/bin/betterdisplaycli'}))
            self.assertEqual(cfg.betterdisplaycli_path, '/opt/homebrew/bin/betterdisplaycli')

        with patch('core.settings.BetterDisplayCLI.resolve_cli_path', return_value=None):
            with self.assertRaises(ValueError):
                apply_change(cfg, 'set_betterdisplaycli_path', {'path': '/invalid/path'})

        # Reset to default
        self.assertTrue(apply_change(cfg, 'set_betterdisplaycli_path', {'path': None}))
        self.assertIsNone(cfg.betterdisplaycli_path)

        # Invalid payload
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_betterdisplaycli_path', {})
        with self.assertRaises(ValueError):
            apply_change(cfg, 'set_betterdisplaycli_path', {'path': 123})

    def test_daemon_handles_betterdisplaycli_path_change(self):
        cls = DAEMON['SidecarSwitchDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
        obj.engine.run_control.side_effect = lambda action: action()
        cfg = self.config()
        cfg.betterdisplaycli_path = '/old/path'
        mock_bd = MagicMock()
        with patch.dict(cls.handle_client_cmd.__globals__, {
            'load_config': lambda: cfg,
            'save_config': MagicMock(),
            'BetterDisplayCLI': MagicMock(return_value=mock_bd),
        }):
            response = obj.handle_client_cmd('set_betterdisplaycli_path:' + json.dumps({'path': None}))
        self.assertTrue(response.startswith('OK:'))
        obj.engine.evaluate.assert_called_once_with(trigger='betterdisplaycli_path_change')


    def test_native_payload_keeps_profile_identity_controls_and_preferences(self):
        from core.gui import build_gui_payload
        cfg = self.config()
        cfg.revision = 7
        view = {'config': cfg, 'config_error': '', 'actual': {}, 'status': {},
                'fresh': False, 'scanned': False, 'consistency_state': 'CONSISTENT',
                'identifiers': [{'name': 'Backup', 'deviceType': 'VirtualScreen'},
                                {'name': 'Monitor', 'deviceType': 'Display'}]}
        with patch('core.gui.read_view', return_value=view), \
             patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value='/custom/BetterDisplay'):
            payload = build_gui_payload()
        self.assertEqual(json.loads(json.dumps(payload))['config'], cfg.to_dict())
        self.assertEqual([p['key'] for p in payload['profiles']], [pairing_key(ONE), pairing_key(TWO)])
        self.assertEqual([p['can_control'] for p in payload['profiles']], [True, False])
        self.assertEqual([p['is_target'] for p in payload['profiles']], [True, False])
        self.assertEqual(payload['virtuals'], [view['identifiers'][0]])
        self.assertEqual(payload['paths']['betterdisplaycli'], '/custom/BetterDisplay')
        for key in ('debounce_seconds', 'max_retries', 'retry_interval', 'cooldown_seconds',
                    'ignore_list', 'auto_detect_ipad', 'usb_event_wakeup', 'autostart_on_login'):
            self.assertEqual(payload['config'][key], cfg.to_dict()[key])
        view['config_error'] = 'Repair the original configuration.'
        with patch('core.gui.read_view', return_value=view), \
             patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value=None):
            readonly = build_gui_payload(scan=True)
        self.assertTrue(readonly['ui']['readonly'])
        self.assertFalse(any(profile['can_control'] for profile in readonly['profiles']))

    def test_native_launch_reuses_app_and_rejects_invalid_profile_key(self):
        from core.gui import run_gui
        app = ROOT / 'build/SidecarSwitch.app'
        with patch('core.autostart.find_menu_app', return_value=app), \
             patch('core.gui.subprocess.run') as launch:
            run_gui('diagnostics')
            args = launch.call_args.args[0]
            self.assertEqual(args[:3], ['/usr/bin/open', '-a', str(app)])
            self.assertIn('sidecarswitch://settings?page=diagnostics', args)
            run_gui('wizard', delete=pairing_key(ONE))
            self.assertIn('page=search&delete=' + pairing_key(ONE), launch.call_args.args[0][3])
            launch.reset_mock()
            with self.assertRaises(ValueError):
                run_gui('paired', select='not-a-profile-key')
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
