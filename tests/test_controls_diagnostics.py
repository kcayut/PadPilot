"""Control identity, recovered state, startup evidence and menu routing regressions."""
import argparse
import contextlib
import io
import runpy
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.betterdisplay import BetterDisplayCLI
from core.config import Config
from core.detector import DisplayDetector
from core.diagnostics import betterdisplay_login_status
from core.models import ActualState, DisplayInfo, DisplayRole, IpadConfig, OperationMode, TransitionState
from core.state_engine import StateEngine

ROOT = Path(__file__).resolve().parents[1]


class ControlsTests(unittest.TestCase):
    def test_renamed_profile_resolves_live_sidecar_and_distinct_display_uuid(self):
        cfg = Config(ipad=IpadConfig(name='自訂標籤', sidecar_uuid='SESSION'))
        bd = MagicMock(spec=BetterDisplayCLI)
        bd.check_virtual_display.return_value = (True, True)
        bd.get_sidecar_list.return_value = [{'uuid': 'SESSION', 'name': 'ky iPad pro m2'}]
        bd.get_sidecar_connected.return_value = True
        detector = DisplayDetector(cfg, bd)
        ipad = DisplayInfo(2, 'ky iPad pro m2', uuid='DISPLAY', is_sidecar=True)
        with patch.object(detector, 'get_online_displays', return_value=[ipad]), \
             patch.object(detector, 'parse_usb_devices', return_value=[]):
            actual, _ = detector.observe()
        self.assertTrue(actual.sidecar_connected)
        self.assertTrue(actual.sidecar_display_online)
        engine = StateEngine(cfg, detector, bd)
        engine.actual = actual
        engine.desired = engine.policy(actual, cfg, engine.runtime)
        with patch.object(engine, '_observe', return_value=actual), \
             patch.object(engine, '_export_status'), patch('core.state_engine.time.sleep'):
            engine._run_transition()
        bd.set_main_display.assert_called_once_with('DISPLAY')

    def test_session_connected_without_display_is_not_offline(self):
        cfg = Config(ipad=IpadConfig(name='Label', sidecar_uuid='SESSION'))
        bd = MagicMock(spec=BetterDisplayCLI)
        bd.get_sidecar_list.return_value = []
        bd.check_virtual_display.return_value = (False, False)
        bd.get_sidecar_connected.return_value = True
        detector = DisplayDetector(cfg, bd)
        with patch.object(detector, 'get_online_displays', return_value=[]), \
             patch.object(detector, 'parse_usb_devices', return_value=[]):
            actual, _ = detector.observe()
        self.assertTrue(actual.sidecar_connected)
        self.assertFalse(actual.sidecar_display_online)
        engine = StateEngine(cfg, detector, bd)
        from core.models import UserOverride
        engine.runtime.user_override = UserOverride(DisplayRole.IPAD_DISCONNECTED, 0)
        self.assertTrue(engine.policy(actual, cfg, engine.runtime).needs_sidecar_disconnect)

    def test_disconnect_requires_verified_off_not_just_zero_exit(self):
        bd = BetterDisplayCLI.__new__(BetterDisplayCLI)
        with patch.object(bd, 'is_available', return_value=True), \
             patch.object(bd, 'run_cmd', return_value=(0, '', '')), \
             patch('time.sleep'), patch.object(bd, 'get_sidecar_connected') as state:
            state.return_value = True
            self.assertFalse(bd.disconnect_sidecar('SESSION'))
            state.side_effect = [True, False]
            self.assertTrue(bd.disconnect_sidecar('SESSION'))

    def test_state_query_unknown_is_not_false(self):
        bd = BetterDisplayCLI.__new__(BetterDisplayCLI)
        with patch.object(bd, 'run_cmd') as run:
            for response, expected in [((0, 'on', ''), True), ((0, 'off', ''), False),
                                       ((-1, '', 'timeout'), None), ((0, '', ''), None)]:
                run.return_value = response
                self.assertIs(bd.get_sidecar_connected('SESSION'), expected)

    def test_late_connection_clears_error_and_cooldown_without_transition(self):
        cfg = Config(ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
        detector, bd = MagicMock(), MagicMock()
        engine = StateEngine(cfg, detector, bd)
        actual = ActualState(main_display=DisplayInfo(2, 'iPad', is_sidecar=True, is_main=True),
                             sidecar_connected=True, sidecar_display_online=True)
        detector.observe.return_value = (actual, ((), False))
        engine.runtime.last_error = 'failed earlier'
        engine.runtime.cooldown_until = time.time() + 30
        engine.runtime.transition_state = TransitionState.COOLDOWN
        with patch.object(engine, '_export_status'), patch.object(engine, '_trigger_transition') as transition:
            engine.evaluate()
        self.assertIsNone(engine.runtime.last_error)
        self.assertEqual(engine.runtime.cooldown_until, 0)
        self.assertEqual(engine.runtime.transition_state, TransitionState.IDLE)
        self.assertEqual(engine._determine_icon(True), '📱')
        transition.assert_not_called()

    def test_fallback_during_cooldown_does_not_falsely_clear_failure(self):
        cfg = Config(mode=OperationMode.PREFER_IPAD)
        detector = MagicMock()
        engine = StateEngine(cfg, detector, MagicMock())
        physical = DisplayInfo(1, 'Monitor', is_main=True)
        detector.observe.return_value = (ActualState(physical_displays=[physical], main_display=physical,
                                                       sidecar_available=True), ((1,), False))
        engine.runtime.cooldown_until = time.time() + 30
        engine.runtime.last_error = 'connection failed'
        with patch.object(engine, '_export_status'):
            engine.evaluate()
        self.assertEqual(engine.runtime.last_error, 'connection failed')

    def test_reconnect_preserves_secondary_override_after_intentional_disconnect(self):
        cfg = Config(ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
        detector, bd = MagicMock(), MagicMock()
        engine = StateEngine(cfg, detector, bd)
        physical = DisplayInfo(1, 'Monitor', is_main=True)
        before = ActualState(physical_displays=[physical], main_display=physical,
                             sidecar_connected=True, sidecar_display_online=True)
        after = ActualState(physical_displays=[physical], main_display=physical, sidecar_available=True)
        engine.actual = before
        detector.observe.side_effect = [(before, ((1,), False)), (after, ((1,), False)),
                                        (after, ((1,), False)), (after, ((1,), False))]
        with patch.object(engine, '_export_status'), patch.object(engine, '_trigger_transition'):
            self.assertTrue(engine.reconnect_sidecar())
        self.assertEqual(engine.desired.target_display_role, DisplayRole.IPAD_SECONDARY)
        self.assertTrue(engine.desired.needs_sidecar_connect)

    def test_menu_order_diagnostics_and_readable_labels(self):
        menu = runpy.run_path(str(ROOT / 'swiftbar/padpilot.30s.py'))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            menu['render']({}, {}, False)
        lines = output.getvalue().splitlines()
        titles = [line.split(' |')[0] for line in lines if not line.startswith('-')]
        expected = ['螢幕與裝置', 'iPad 控制', '運作模式', '背景服務', '設定與配對',
                    '狀態與診斷', '重新整理螢幕狀態', 'Exit']
        self.assertEqual(titles[-8:], expected)
        diag = next(line for line in lines if line.startswith('狀態與診斷'))
        self.assertIn('param1=gui param2=diagnostics', diag)
        self.assertIn('color=#1c1c1e,#f2f2f7', diag)

    def test_action_errors_reach_gui_instead_of_false_success(self):
        cli = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
        function = cli['cmd_action']
        with patch.dict(function.__globals__, {'send_daemon_cmd': lambda *a, **kw: 'ERROR: failed'}):
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace(action='disconnect_ipad'))

    def test_gui_four_controls_route_to_shared_actions_and_reject_stale_target(self):
        from core.gui import SettingsWindow
        app = SettingsWindow.__new__(SettingsWindow)
        app.readonly = app.busy = False
        cfg = Config(ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
        app.view = {'config': cfg}
        app.run_action = MagicMock(return_value='OK: requested')
        app.task = lambda work, complete: work()
        with patch('core.gui.read_view', return_value=app.view):
            for action in ('use_ipad_secondary', 'use_ipad_main', 'disconnect_ipad', 'reconnect_sidecar'):
                app.control_ipad(cfg.ipad.to_dict(), action)
                app.run_action.assert_called_with(action)
        with patch('core.gui.read_view', return_value={'config': Config()}):
            with self.assertRaisesRegex(RuntimeError, '控制目標已變更'):
                app.control_ipad(cfg.ipad.to_dict(), 'disconnect_ipad')

    def test_cli_accepts_both_custom_path_and_reset_from_gui(self):
        cli = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
        submit = MagicMock()
        # Parser, stdin decoding and dispatcher are exercised together.
        with patch.dict(cli['submit_settings'].__globals__, {'submit_settings': submit}), \
             patch('sys.argv', ['padpilot-cli', 'change-settings', 'set_betterdisplaycli_path']):
            for payload in ('{"path": null}', '{"path": "/custom/BetterDisplay"}'):
                with patch('sys.stdin', io.StringIO(payload)):
                    cli['main']()
                self.assertEqual(submit.call_args.args[0], 'set_betterdisplaycli_path')

    def test_gui_refresh_reconciles_daemon_before_reading_view(self):
        from core.gui import SettingsWindow
        app = SettingsWindow.__new__(SettingsWindow)
        app.current_tab = 'paired'
        app.display = MagicMock()
        app.task = lambda work, complete: work()
        events = []
        app.run_action = lambda action: events.append(action)
        with patch('core.autostart.is_daemon_running', return_value=True), \
             patch('core.gui.read_view', side_effect=lambda **kw: events.append('read') or {}):
            app.search()
        self.assertEqual(events, ['refresh', 'read'])

    def test_profile_name_draft_preserves_expected_revision(self):
        from core.gui import SettingsWindow
        app = SettingsWindow.__new__(SettingsWindow)
        app.busy = False
        app.root = MagicMock()
        cfg = Config(ipad=IpadConfig(name='Old name', sidecar_uuid='SESSION'), revision=9)
        app.view = {'config': cfg}
        app.dirty_fields = {'name.SESSION': {'value': 'New name', 'base_revision': 7}}
        app.change = MagicMock()
        with patch('core.gui.confirm', return_value=True):
            app.update_profile_name(cfg.ipad.to_dict(), 'New name')
        self.assertEqual(app.change.call_args.args[1]['__expected_revision__'], 7)

    def test_autostart_failure_is_not_reported_as_cli_success(self):
        cli = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
        function = cli['cmd_autostart']
        with patch.dict(function.__globals__, {'enable_autostart': lambda: (False, 'load failed')}), \
             contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'load failed'):
                function(argparse.Namespace(action='enable'))

    def test_general_checks_never_query_authenticated_login_items(self):
        from core.diagnostics import collect_system_checks
        with patch('core.diagnostics.command', return_value='FileVault is Off.') as command, \
             patch('core.diagnostics.is_daemon_running', return_value=False):
            checks = collect_system_checks(Config(), {})
        self.assertEqual(command.call_args_list[0].args[0], ['/usr/bin/fdesetup', 'status'])
        self.assertEqual(command.call_count, 1)
        self.assertNotIn('BetterDisplay 登入啟動', [label for label, _ in checks])

    def test_diagnostic_refresh_updates_only_requested_card(self):
        from core.gui import SettingsWindow
        for section in ('decision', 'system_checks', 'authenticated_checks'):
            with self.subTest(section=section):
                app = SettingsWindow.__new__(SettingsWindow)
                app.current_tab = 'diagnostics'
                app.view = {'config': Config(), 'system_checks': [('general', 'old')],
                            'authenticated_checks': [('auth', 'old')]}
                app.diagnostic_hosts = {key: MagicMock() for key in
                    ('decision', 'system_checks', 'authenticated_checks', 'logs')}
                app.buttons = []
                app.render_decision_card = MagicMock()
                app.render_checks_card = MagicMock()
                app._update_scrollregion = MagicMock()
                app.notice = MagicMock()
                app.run_action = MagicMock()
                app.task = lambda work, complete: complete(work())
                with patch('core.gui.read_view', return_value={'config': Config(), 'actual': {}}), \
                     patch('core.autostart.is_daemon_running', return_value=True), \
                     patch('core.diagnostics.collect_system_checks', return_value=[('general', 'new')]) as general, \
                     patch('core.diagnostics.collect_authenticated_checks', return_value=[('auth', 'new')]) as auth:
                    app.refresh_diagnostic(section)
                self.assertEqual(general.call_count, int(section == 'system_checks'))
                self.assertEqual(auth.call_count, int(section == 'authenticated_checks'))
                self.assertEqual(app.run_action.call_count, int(section == 'decision'))
                for key, host in app.diagnostic_hosts.items():
                    self.assertEqual(host.winfo_children.call_count, int(key == section))
                if section != 'authenticated_checks':
                    self.assertEqual(app.view['authenticated_checks'], [('auth', 'old')])
                if section != 'system_checks':
                    self.assertEqual(app.view['system_checks'], [('general', 'old')])

    def test_login_items_filter_current_user_and_distinguish_unknown(self):
        data = '''Records for UID 501\n #1:\n Bundle Identifier: pro.betterdisplay.BetterDisplay\n Disposition: [enabled, allowed, notified] (0xb)\nRecords for UID 502\n #1:\n Bundle Identifier: pro.betterdisplay.BetterDisplay\n Disposition: [disabled, allowed] (0x2)\n'''
        self.assertEqual(betterdisplay_login_status(data, 501), '已啟用')
        self.assertEqual(betterdisplay_login_status(data, 502), '未啟用')
        self.assertTrue(betterdisplay_login_status(data, 503).startswith('未知'))
        self.assertTrue(betterdisplay_login_status(None, 501).startswith('未知'))


if __name__ == '__main__':
    unittest.main()
