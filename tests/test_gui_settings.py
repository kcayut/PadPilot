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
from core.gui import SettingsWindow, read_view
from core.models import OperationMode, pairing_key
from core.settings import apply_change

ROOT = Path(__file__).resolve().parents[1]
MENU = runpy.run_path(str(ROOT/'swiftbar/padpilot.30s.py'))
DAEMON = runpy.run_path(str(ROOT/'bin/padpilotd'))
ONE = {'name': '同名 iPad', 'sidecar_uuid': '11111111-1111-4111-8111-111111111111', 'usb_serial': 'usb1'}
TWO = dict(ONE, sidecar_uuid='22222222-2222-4222-8222-222222222222', usb_serial='usb2')


class GuiSettingsTests(unittest.TestCase):
    def config(self):
        return Config.from_dict({'ipad': ONE, 'paired_ipads': [ONE, TWO]})

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

    def test_no_confirmation_means_no_write_yes_uses_selected_key(self):
        app = SettingsWindow.__new__(SettingsWindow)
        app.readonly, app.busy = False, False
        app.root = MagicMock()
        app.view = {'config': self.config()}
        app.profiles = {pairing_key(ONE): ONE}
        app.change = MagicMock()
        with patch('core.gui.confirm', return_value=False) as dialog:
            app.delete_selected(pairing_key(ONE))
            app.change.assert_not_called()
            self.assertEqual(dialog.call_args.args[1], '確定刪除配對?')
        with patch('core.gui.confirm', return_value=True):
            app.delete_selected(pairing_key(ONE))
        app.change.assert_called_once_with('delete_pairing', {'key': pairing_key(ONE)})

    def test_settings_page_is_interactive_and_read_view_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as d, patch('core.gui.get_config_file_path', return_value=Path(d)/'config.json'), \
             patch('core.gui.read_status', return_value=None):
            read_view()
            self.assertEqual(list(Path(d).iterdir()), [])

    def test_menu_removes_pairing_and_start_entries_and_uses_gui(self):
        out = io.StringIO()
        cfg = self.config().to_dict()
        with contextlib.redirect_stdout(out):
            MENU['render']({}, cfg, True)
        text = out.getvalue()
        section = text.split('\n螢幕與裝置 |')[1].split('\niPad 控制 |')[0]
        self.assertNotIn('新增', section)
        self.assertNotIn('更新配對', section)
        self.assertEqual(section.count('刪除配對 |'), 2)
        self.assertNotIn('啟動 PadPilot |', text)
        for label in ('設定與配對', '刪除配對'):
            line = next(l for l in text.splitlines() if label+' |' in l)
            self.assertIn('param1=gui', line)
            self.assertIn('terminal=false', line)
        self.assertNotIn('開啟 BetterDisplay', text)
        self.assertNotIn('檢視設定', text)
        self.assertNotIn('配對精靈 Wizard…', text)
        # Deleting last profile must not resurrect an older daemon snapshot.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            MENU['render']({'paired_ipads': [ONE], 'configured_ipad': ONE},
                           {'ipad': {}, 'paired_ipads': []}, True)
        self.assertNotIn('同名 iPad', out.getvalue())

    def test_daemon_deleting_target_pauses_before_reevaluation(self):
        cls = DAEMON['PadPilotDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
        cfg = self.config()
        with patch.dict(cls.handle_client_cmd.__globals__, {'load_config': lambda: cfg, 'save_config': MagicMock()}):
            response = obj.handle_client_cmd('delete_pairing:'+json.dumps({'key': pairing_key(ONE)}))
        self.assertTrue(response.startswith('OK:'))
        self.assertEqual(obj.engine.runtime.mode, OperationMode.MANUAL_ONLY)
        obj.engine.reset_automation.assert_called_once()

    def test_virtual_change_preserves_current_override(self):
        cls = DAEMON['PadPilotDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
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
        cls = DAEMON['PadPilotDaemon']
        obj = cls.__new__(cls)
        obj.detector, obj.engine = MagicMock(), MagicMock()
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

    def test_gui_reset_betterdisplay_cli_action(self):
        app = SettingsWindow.__new__(SettingsWindow)
        app.readonly, app.busy = False, False
        app.root = MagicMock()
        cfg = self.config()
        cfg.betterdisplaycli_path = '/custom/path'
        app.view = {'config': cfg}
        app.change = MagicMock()

        # Decline confirmation
        with patch('core.gui.confirm', return_value=False):
            app.reset_betterdisplay_cli_action()
            app.change.assert_not_called()

        # Accept confirmation
        with patch('core.gui.confirm', return_value=True):
            app.reset_betterdisplay_cli_action()
            app.change.assert_called_once_with('set_betterdisplaycli_path', {'path': None})

        # When already default
        app.change.reset_mock()
        cfg.betterdisplaycli_path = None
        with patch('tkinter.messagebox.showinfo') as mock_info:
            app.reset_betterdisplay_cli_action()
            mock_info.assert_called_once()
            app.change.assert_not_called()


if __name__ == '__main__':
    unittest.main()
