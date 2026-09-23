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
        cfg = Config(mode=OperationMode.AUTOMATIC, auto_detect_ipad=False, ipad=IpadConfig(name='自訂標籤', sidecar_uuid='SESSION'))
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
             patch.object(engine, '_export_status'), patch('core.state_engine.StateEngine._wait'):
            engine._run_transition()
        bd.set_main_display.assert_called_once_with('DISPLAY')

    def test_session_connected_without_display_is_not_offline(self):
        cfg = Config(mode=OperationMode.AUTOMATIC, auto_detect_ipad=False, ipad=IpadConfig(name='Label', sidecar_uuid='SESSION'))
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
        cfg = Config(mode=OperationMode.AUTOMATIC, auto_detect_ipad=False, ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
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
        cfg = Config(mode=OperationMode.AUTOMATIC, auto_detect_ipad=False, ipad=IpadConfig(name='iPad', sidecar_uuid='SESSION'))
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
        cli = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))
        function = cli['cmd_action']
        with patch.dict(function.__globals__, {'send_daemon_cmd': lambda *a, **kw: 'ERROR: failed'}):
            with self.assertRaises(RuntimeError):
                function(argparse.Namespace(action='disconnect_ipad'))


    def test_cli_accepts_both_custom_path_and_reset_from_gui(self):
        cli = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))
        submit = MagicMock()
        # Parser, stdin decoding and dispatcher are exercised together.
        with patch.dict(cli['submit_settings'].__globals__, {'submit_settings': submit}), \
             patch('sys.argv', ['sidecarswitch-cli', 'change-settings', 'set_betterdisplaycli_path']):
            for payload in ('{"path": null}', '{"path": "/custom/BetterDisplay"}'):
                with patch('sys.stdin', io.StringIO(payload)):
                    cli['main']()
                self.assertEqual(submit.call_args.args[0], 'set_betterdisplaycli_path')


    def test_autostart_failure_is_not_reported_as_cli_success(self):
        cli = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))
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
        self.assertEqual([call.args[0] for call in command.call_args_list], [
            ['/usr/sbin/sysadminctl', '-autologin', 'status'], ['/usr/bin/fdesetup', 'status']])
        self.assertNotIn('BetterDisplay 登入啟動', [label for label, _ in checks])

    @patch('core.diagnostics.autostart_status', return_value='notRegistered')
    def test_automatic_login_uses_live_status_instead_of_residual_username(self, _startup):
        from core.diagnostics import collect_system_checks
        from core.gui import get_check_light, GREEN, RED, ORANGE
        for output, code, expected, color in [
            ('Automatic login is OFF.', 0, '已停用', RED),
            ('Automatic login user: testuser', 0, '已設定：testuser', GREEN),
            ('Automatic login is disabled by your system administrator.', 0, '已停用', RED),
            ('Automatic login is disabled because FileVault is enabled.', 0, '已停用', RED),
            ('Automatic login user: ', 0, '未知（無法查詢）', ORANGE),
            ('Unsupported option', 0, '未知（無法查詢）', ORANGE),
            ('Automatic login user: testuser', 1, '未知（無法查詢）', ORANGE),
            ('', 0, '未知（無法查詢）', ORANGE),
            (subprocess.TimeoutExpired('sysadminctl', 5), 0, '未知（無法查詢）', ORANGE),
        ]:
            with self.subTest(output=output, code=code):
                result = (output if isinstance(output, Exception) else
                          subprocess.CompletedProcess([], code, '',
                              '2026-09-11 13:51:43.722 sysadminctl[123:456] ' + output if output else ''))
                with patch('core.diagnostics.read_plist', return_value={'autoLoginUser': 'old-user'}) as read, \
                     patch('core.diagnostics.is_daemon_running', return_value=True), \
                     patch('core.diagnostics.BetterDisplayCLI.resolve_cli_path', return_value='/mock/cli'), \
                     patch('core.diagnostics.subprocess.run', side_effect=[
                         result, subprocess.CompletedProcess([], 0, 'FileVault is Off.', '')]) as run:
                    checks = dict(collect_system_checks(Config(), {}))
                self.assertEqual(checks['macOS 自動登入'], expected)
                self.assertEqual(get_check_light('macOS 自動登入', expected)[1], color)
                self.assertEqual(run.call_args_list[0].kwargs['stdin'], subprocess.DEVNULL)
                self.assertNotIn('/Library/Preferences/com.apple.loginwindow.plist',
                                 [str(call.args[0]) for call in read.call_args_list])


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
            ('SidecarSwitch 登入啟動', '已設定（登入後啟用）'),
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
            ('SidecarSwitch 登入啟動', '未設定'),
            ('SidecarSwitch 登入啟動', '未啟用'),
            ('SidecarSwitch 登入啟動', '設定異常（執行檔或程式路徑不存在）'),
            ('背景服務', '未回應／尚未啟動'),
            ('BetterDisplay 安裝', '未在標準應用程式位置找到'),
            ('BetterDisplay 控制介面', '未找到'),
            ('虛擬備援螢幕', '未找到：SidecarSwitchVirtual'),
            ('Sidecar 配對', '尚未配對'),
            ('BetterDisplay 登入啟動', '未啟用'),
            ('BetterDisplay 登入啟動', '未登錄（請到系統設定 → 一般 → 登入項目確認）'),
        ]:
            status, color = get_check_light(label, val)
            self.assertEqual(status, 'fail', f'Failed on {label}: {val}')
            self.assertEqual(color, RED, f'Failed color on {label}: {val}')

        # Grade these states for unattended startup display readiness.
        for label, val, expected in [
            ('macOS 自動登入', '已設定：testuser', ('pass', GREEN)),
            ('macOS 自動登入', '已啟用', ('pass', GREEN)),
            ('macOS 自動登入', '未設定', ('fail', RED)),
            ('macOS 自動登入', '已停用', ('fail', RED)),
            ('macOS 自動登入', '未啟用', ('fail', RED)),
            ('FileVault', '未開啟', ('pass', GREEN)),
            ('FileVault', '已開啟', ('fail', RED)),
            ('FileVault', '已開啟；重新開機後需先解鎖磁碟', ('fail', RED)),
        ]:
            self.assertEqual(get_check_light(label, val), expected)

        # Pending cases -> ORANGE
        for label, val in [
            ('macOS 自動登入', '未知（無法讀取系統設定）'),
            ('macOS 自動登入', '尚未檢查'),
            ('FileVault', '尚未檢查'),
            ('FileVault', 'unexpected response'),
            ('BetterDisplay 登入啟動', '尚未驗證'),
            ('SidecarSwitch 登入啟動', '尚未檢查'),
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


    def test_native_payload_diagnostics_and_logs_require_explicit_requests(self):
        from core.gui import build_gui_payload
        view = {'config': Config(), 'config_error': '', 'actual': {}, 'status': {},
                'fresh': True, 'scanned': False, 'consistency_state': 'CONSISTENT', 'identifiers': []}
        with patch('core.gui.read_view', return_value=view) as read, \
             patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value=None), \
             patch('core.gui.get_log_file_path') as log_path, \
             patch('core.diagnostics.collect_system_checks', return_value=[('FileVault', '已開啟')]) as general, \
             patch('core.diagnostics.collect_authenticated_checks', return_value=[('BetterDisplay 登入啟動', '已啟用')]) as auth:
            payload = build_gui_payload()
            read.assert_called_once_with(scan=False)
            general.assert_not_called()
            auth.assert_not_called()
            log_path.return_value.open.assert_not_called()
            self.assertNotIn('logs', payload)
            self.assertNotIn('authenticated_checks', payload)
            payload = build_gui_payload(diagnostics=True)
            general.assert_called_once()
            auth.assert_not_called()
            self.assertEqual(payload['system_checks'][0]['state'], 'fail')
            self.assertTrue(payload['system_checks'][0]['help_url'].endswith('#filevault'))
            payload = build_gui_payload(admin_checks=True)
            auth.assert_called_once()
            self.assertEqual(general.call_count, 1)
            self.assertEqual(payload['authenticated_checks'][0]['state'], 'pass')
            self.assertNotIn('system_checks', payload)

    def test_native_logs_tail_is_bounded_and_missing_file_is_not_created(self):
        import tempfile
        from core.gui import build_gui_payload
        view = {'config': Config(), 'config_error': '', 'actual': {}, 'status': {},
                'fresh': True, 'scanned': False, 'consistency_state': 'CONSISTENT', 'identifiers': []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sidecarswitch.log'
            with patch('core.gui.read_view', return_value=view), \
                 patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value=None), \
                 patch('core.gui.get_log_file_path', return_value=path):
                self.assertIn('尚無日誌', build_gui_payload(logs=True)['logs'])
                self.assertFalse(path.exists())
                path.write_text('\n'.join(f'2026-09-11 10:00:00 [INFO] [test] line {i}' for i in range(1000)))
                lines = build_gui_payload(logs=True)['logs'].splitlines()
                self.assertEqual(len(lines), 400)
                self.assertTrue(lines[0].endswith('line 600'))
                self.assertTrue(lines[-1].endswith('line 999'))
                path.write_bytes(b'X' * (300 * 1024) + b'\nlast valid line\n')
                self.assertEqual(build_gui_payload(logs=True)['logs'], 'last valid line')


if __name__ == '__main__':
    unittest.main()
