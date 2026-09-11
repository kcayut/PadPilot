"""Control identity, recovered state, startup evidence and menu routing regressions."""
import argparse
import contextlib
import io
import runpy
import subprocess
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
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='自訂標籤', sidecar_uuid='SESSION'))
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
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='Label', sidecar_uuid='SESSION'))
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
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
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
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
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
        from core.menu import render
        rows = render({}, {}, False, service_running=True)['items']
        titles = [r['title'] for r in rows if r['depth'] == 0 and not r['separator']]
        expected = ['螢幕與裝置', 'iPad 控制', '運作模式', '背景服務', '🌐 Language', '設定與配對',
                    '狀態與診斷', '重新整理螢幕狀態', '結束']
        self.assertEqual(titles[-9:], expected)
        for title in ('狀態與診斷', '重新整理螢幕狀態'):
            index = next(i for i, r in enumerate(rows) if r['title'] == title)
            self.assertTrue(rows[index + 1]['separator'])
        diag = next(r for r in rows if r['title'] == '狀態與診斷')
        self.assertEqual(diag['args'], ['gui', 'diagnostics'])
        self.assertTrue(diag['enabled'])

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
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
        app.view = {'config': cfg}
        app.run_action = MagicMock(return_value='OK: requested')
        app.task = lambda work, complete: work()
        for auto_detect in (False, True):
            cfg.auto_detect_ipad = auto_detect
            with patch('core.gui.read_view', return_value=app.view):
                for action in ('use_ipad_secondary', 'use_ipad_main', 'disconnect_ipad', 'reconnect_sidecar'):
                    app.run_action.reset_mock()
                    app.control_ipad(cfg.ipad.to_dict(), action)
                    app.run_action.assert_called_once_with(action)
            app.run_action.reset_mock()
            app.control_ipad(dict(cfg.ipad.to_dict(), sidecar_uuid='OTHER'), 'disconnect_ipad')
            app.run_action.assert_not_called()
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

    def test_gui_open_refresh_uses_real_action_success_path(self):
        from core.gui import SettingsWindow
        app = SettingsWindow.__new__(SettingsWindow)
        app.current_tab = 'paired'
        app.display = MagicMock()
        app.task = lambda work, complete: complete(work())
        view = {'config': Config(), 'actual': {}}
        # Mock only external boundaries; run the shared action helper itself.
        result = subprocess.CompletedProcess([], 0, stdout='OK: refreshed\n', stderr='')
        with patch('core.autostart.is_daemon_running', return_value=True), \
             patch('core.gui.subprocess.run', return_value=result) as run, \
             patch('core.gui.read_view', return_value=view) as read:
            app.search()
            self.assertEqual(run.call_args.args[0][-2:], ['action', 'refresh'])
            read.assert_called_once_with(scan=True)
            app.display.assert_called_once_with(view)
            self.assertEqual(SettingsWindow.run_action('refresh'), 'OK: refreshed')
            result.returncode, result.stderr = 1, 'refresh failed'
            with self.assertRaisesRegex(RuntimeError, 'refresh failed'):
                SettingsWindow.run_action('refresh')

    def test_profile_name_draft_preserves_expected_revision(self):
        from core.gui import SettingsWindow
        app = SettingsWindow.__new__(SettingsWindow)
        app.busy = False
        app.root = MagicMock()
        cfg = Config(auto_detect_ipad=False, ipad=IpadConfig(name='Old name', sidecar_uuid='SESSION'), revision=9)
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
                app.readonly = False
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

    def test_check_light_indicator_colors_and_categories(self):
        from core.gui import get_check_light, GREEN, RED, ORANGE
        # Passed cases -> GREEN
        for label, val in [
            ('PadPilot 登入啟動', '已設定（登入後啟用）'),
            ('背景服務', '執行中'),
            ('BetterDisplay 安裝', '已安裝'),
            ('BetterDisplay 控制介面', '可用'),
            ('虛擬備援螢幕', '已設定'),
            ('Sidecar 配對', '已設定 UUID'),
            ('BetterDisplay 登入啟動', '已啟用'),
        ]:
            status, color = get_check_light(label, val)
            self.assertEqual(status, 'pass', f'Failed on {label}: {val}')
            self.assertEqual(color, GREEN, f'Failed color on {label}: {val}')

        # Failed cases -> RED
        for label, val in [
            ('PadPilot 登入啟動', '未設定'),
            ('PadPilot 登入啟動', '未啟用'),
            ('PadPilot 登入啟動', '設定異常（執行檔或程式路徑不存在）'),
            ('背景服務', '未回應／尚未啟動'),
            ('BetterDisplay 安裝', '未在標準應用程式位置找到'),
            ('BetterDisplay 控制介面', '未找到'),
            ('虛擬備援螢幕', '未找到：PadPilotVirtual'),
            ('Sidecar 配對', '尚未配對'),
            ('BetterDisplay 登入啟動', '未啟用'),
            ('BetterDisplay 登入啟動', '未登錄（請到系統設定 → 一般 → 登入項目確認）'),
        ]:
            status, color = get_check_light(label, val)
            self.assertEqual(status, 'fail', f'Failed on {label}: {val}')
            self.assertEqual(color, RED, f'Failed color on {label}: {val}')

        # Pending cases -> ORANGE
        for label, val in [
            ('macOS 自動登入', '已設定：testuser'),
            ('macOS 自動登入', '未設定'),
            ('FileVault', '未開啟'),
            ('FileVault', '已開啟；重新開機後需先解鎖磁碟'),
            ('BetterDisplay 登入啟動', '尚未驗證'),
            ('PadPilot 登入啟動', '尚未檢查'),
            ('BetterDisplay 登入啟動', '未知／受系統限制（請檢查登入項目）'),
            ('BetterDisplay 登入啟動', '未知（系統查詢逾時或無權限）'),
            ('FileVault', '未知（無法查詢）'),
            ('虛擬備援螢幕', '未知（識別查詢失敗）'),
            ('需人工確認', 'Mac 與 iPad 使用相同 Apple Account、雙重認證、Wi-Fi／藍牙／接力與信任此電腦。'),
            ('滑鼠與鍵盤', '若游標跑進 iPad 原生畫面，請在顯示器 → 進階關閉通用控制的跨裝置移動。'),
        ]:
            status, color = get_check_light(label, val)
            self.assertEqual(status, 'pending', f'Failed on {label}: {val}')
            self.assertEqual(color, ORANGE, f'Failed color on {label}: {val}')

    def test_render_checks_cards_titles_and_default_items(self):
        import tkinter as tk
        from core.gui import SettingsWindow, GREEN, ORANGE
        root = tk.Tk()
        try:
            with patch.object(SettingsWindow, 'search'), patch.object(SettingsWindow, '_check_external_sync'):
                app = SettingsWindow(root)
                app.display({'config': Config(), 'actual': {}, 'fresh': True, 'identifiers': [], 'status': {}})
                app.select_tab('diagnostics')

                # Card 2: system_checks
                host2 = app.diagnostic_hosts['system_checks']
                labels_card2 = [w.cget('text') for w in host2.winfo_children()[0].body.winfo_children()
                                if w.winfo_class() == 'Label' or isinstance(w, tk.Label)]
                # Header title in top frame
                top2 = host2.winfo_children()[0].body.winfo_children()[0]
                top2_labels = [w.cget('text') for w in top2.winfo_children() if isinstance(w, tk.Label)]
                card2_title = top2_labels[0]
                self.assertEqual(card2_title, '啟動與必要設定偵測')
                self.assertNotIn('不需帳號密碼', card2_title)
                self.assertNotIn('不需要帳號密碼', card2_title)

                # Card 3: authenticated_checks
                host3 = app.diagnostic_hosts['authenticated_checks']
                top3 = host3.winfo_children()[0].body.winfo_children()[0]
                top3_labels = [w.cget('text') for w in top3.winfo_children() if isinstance(w, tk.Label)]
                card3_title = top3_labels[0]
                self.assertEqual(card3_title, '啟動與必要設定偵測 — 需要使用者帳號密碼')
                self.assertNotIn('需要系統驗證', card3_title)

                # Default item in Card 3 before authentication
                card3_body_children = host3.winfo_children()[0].body.winfo_children()
                # Find check item rows in card3
                rows3 = [w for w in card3_body_children if isinstance(w, tk.Frame) and w != top3]
                self.assertTrue(len(rows3) >= 1)
                row_labels = [c.cget('text') for c in rows3[0].winfo_children() if isinstance(c, tk.Label)]
                row_colors = [c.cget('fg') for c in rows3[0].winfo_children() if isinstance(c, tk.Label)]
                self.assertIn('●', row_labels)
                self.assertIn(ORANGE, row_colors)
                self.assertIn('BetterDisplay 登入啟動：尚未驗證', row_labels)

                # Simulate refreshing authenticated checks
                app.task = lambda work, complete: complete(work())
                with patch('core.diagnostics.collect_authenticated_checks',
                           return_value=[('BetterDisplay 登入啟動', '已啟用')]):
                    app.refresh_diagnostic('authenticated_checks')

                # After verification, check item should show verified result with green light
                card3_body_children_after = host3.winfo_children()[0].body.winfo_children()
                top3_after = card3_body_children_after[0]
                rows3_after = [w for w in card3_body_children_after if isinstance(w, tk.Frame) and w != top3_after]
                self.assertTrue(len(rows3_after) >= 1)
                row_labels_after = [c.cget('text') for c in rows3_after[0].winfo_children() if isinstance(c, tk.Label)]
                row_colors_after = [c.cget('fg') for c in rows3_after[0].winfo_children() if isinstance(c, tk.Label)]
                self.assertIn('BetterDisplay 登入啟動：已啟用', row_labels_after)
                self.assertIn(GREEN, row_colors_after)
        finally:
            root.destroy()

    def test_paired_ipad_controls_layout_and_setting_button_boundary(self):
        import tkinter as tk
        from core.gui import SettingsWindow
        root = tk.Tk()
        try:
            cfg = Config.from_dict({
                'ipad': {'name': 'iPad pro m2',
                         'sidecar_uuid': '11111111-1111-4111-8111-111111111111',
                         'usb_serial': 'USB123'},
                'paired_ipads': [{
                    'name': 'iPad pro m2',
                    'sidecar_uuid': '11111111-1111-4111-8111-111111111111',
                    'usb_serial': 'USB123'
                }]
            })
            with patch.object(SettingsWindow, 'search'), patch.object(SettingsWindow, '_check_external_sync'):
                app = SettingsWindow(root)
                root.geometry('840x500')
                app.display({'config': cfg, 'actual': {}, 'fresh': True, 'identifiers': [], 'status': {}})
                root.update()

                def descendants(widget):
                    for child in widget.winfo_children():
                        yield child
                        yield from descendants(child)

                names = ['作為副螢幕', '設為主螢幕', '中斷連線', '重新連線']
                controls = [w for w in descendants(root) if w.winfo_class() == 'TButton' and w.cget('text') in names]
                exp_btns = [w for w in descendants(root) if w.winfo_class() == 'TButton' and '設定' in w.cget('text')]
                ctrl_lbls = [w for w in descendants(root) if w.winfo_class() == 'Label' and w.cget('text') == '控制']
                usb_lbls = [w for w in descendants(root) if w.winfo_class() == 'Label' and 'USB 序號' in w.cget('text')]

                self.assertEqual(len(controls), 4)
                self.assertEqual(len(exp_btns), 1)
                self.assertEqual(len(ctrl_lbls), 1)
                self.assertEqual(len(usb_lbls), 1)

                exp_btn = exp_btns[0]
                ctrl_lbl = ctrl_lbls[0]
                usb_lbl = usb_lbls[0]

                # 1. Controls are on the same row
                self.assertEqual(len({w.winfo_rooty() for w in controls}), 1)
                # 2. '控制' label is vertically aligned with the control buttons in the same row
                self.assertLessEqual(abs(ctrl_lbl.winfo_rooty() - controls[0].winfo_rooty()), 6)
                # 3. '設定' button is vertically aligned with 'USB 序號' in the same row
                self.assertLessEqual(abs(exp_btn.winfo_rooty() - usb_lbl.winfo_rooty()), 6)
                # 4. None of the control buttons intrude into the vertical plane of the '設定' button
                for w in controls:
                    right_edge = w.winfo_rootx() + w.winfo_width()
                    self.assertLessEqual(right_edge, exp_btn.winfo_rootx())
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
