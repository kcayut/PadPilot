"""Tests for dual revision tracking, single writer architecture, and UI synchronization protocol."""

import io
import json
import runpy
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import Config, load_config, save_config
from core.models import (
    ActualState,
    DesiredState,
    DisplayInfo,
    DisplayRole,
    IpadConfig,
    OperationMode,
    StatusSnapshot,
    pairing_key,
)
from core.settings import ConflictError, apply_change
from core.state_engine import StateEngine

import copy

ROOT = Path(__file__).resolve().parents[1]
DAEMON = runpy.run_path(str(ROOT / "bin/padpilotd"))
CLI = runpy.run_path(str(ROOT / "bin/padpilot-cli"))
MENU = runpy.run_path(str(ROOT / "core/menu.py"))


class SyncProtocolTests(unittest.TestCase):
    """Test suite covering the 5 multi-process sync and concurrency invariants."""

    def setUp(self):
        self.config = Config(
            revision=1,
            mode=OperationMode.AUTOMATIC,
            ipad=IpadConfig(name="iPad Pro", sidecar_uuid="uuid-1234", usb_serial="usb-1234"),
            paired_ipads=[IpadConfig(name="iPad Pro", sidecar_uuid="uuid-1234", usb_serial="usb-1234")],
        )

    # 1. Watchdog evaluate unchanged does not increment status revision or write
    def test_watchdog_evaluate_unchanged_does_not_increment_status_revision_or_write(self):
        detector = MagicMock()
        bd_cli = MagicMock()
        engine = StateEngine(self.config, detector, bd_cli)

        dummy_actual = ActualState(
            physical_displays=[DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False)],
            sidecar_connected=False,
            sidecar_available=False,
            main_display=DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False),
        )
        detector.observe.return_value = (dummy_actual, (("disp-1",), False))

        with patch("core.state_engine.write_atomic_status") as mock_write_status, \
             patch("subprocess.run") as mock_subproc:

            # 1st evaluation: meaningful content exported, revision starts at 0 -> 1
            engine.evaluate(trigger="periodic")
            self.assertEqual(engine.status_revision, 1)
            self.assertEqual(mock_write_status.call_count, 1)

            # 2nd evaluation with identical state (watchdog tick)
            engine.evaluate(trigger="periodic")
            # Must NOT increment status_revision and must NOT write status.json again
            self.assertEqual(engine.status_revision, 1)
            self.assertEqual(mock_write_status.call_count, 1)

            # 3rd evaluation: meaningful change occurs (e.g. Sidecar connects)
            changed_actual = ActualState(
                physical_displays=[DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False)],
                sidecar_connected=True,
                sidecar_available=True,
                main_display=DisplayInfo(display_id="disp-1", name="Dell 4K", is_builtin=False, is_sidecar=False),
            )
            detector.observe.return_value = (changed_actual, (("disp-1",), True))

            engine.evaluate(trigger="event")
            # Must increment status_revision and write status.json
            self.assertEqual(engine.status_revision, 2)
            self.assertEqual(mock_write_status.call_count, 2)

    def test_mode_change_exports_new_snapshot_without_launching_menu_processes(self):
        detector, bd = MagicMock(), MagicMock()
        engine = StateEngine(self.config, detector, bd)
        actual = ActualState(physical_displays=[DisplayInfo(1, 'Monitor')],
                             main_display=DisplayInfo(1, 'Monitor'))
        detector.observe.return_value = (actual, (('Monitor',), False))
        with patch('core.state_engine.write_atomic_status') as write, patch('subprocess.Popen') as launch:
            engine.evaluate()
            self.assertEqual(write.call_count, 1)
            engine.config.mode = OperationMode.MANUAL_ONLY
            engine.config.revision += 1
            engine.runtime.mode = OperationMode.MANUAL_ONLY
            engine.evaluate()
            self.assertEqual(write.call_count, 2)
            self.assertEqual(write.call_args.args[0].config_revision, engine.config.revision)
            launch.assert_not_called()

    # 2. Inconsistent revision snapshot does not mix stale reasons
    def test_inconsistent_revision_snapshot_does_not_mix_stale_reasons(self):
        from core.gui import SettingsWindow, read_view

        cfg = Config(revision=5, mode=OperationMode.MANUAL_ONLY)
        # Status snapshot is still at older config_revision=4
        stale_status = StatusSnapshot(
            timestamp=time.time(),
            mode="automatic",
            icon="green",
            actual={"sidecar_connected": False},
            desired={"target_display_role": "ipad_main", "reason": "Old automatic reasoning"},
            runtime={},
            configured_ipad={},
            summary_text="All good",
            status_details={"desired_role": "ipad_main", "reason": "Old automatic reasoning"},
            paired_ipads=[],
            config_revision=4,
            status_revision=10,
            topology_generation=0,
            evaluation_state="idle",
        )

        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = json.dumps(cfg.to_dict())

        with patch("core.gui.get_config_file_path", return_value=mock_path), \
             patch("core.gui.read_status", return_value=stale_status.to_dict()):
            view = read_view(scan=False)

        # Inconsistency protocol must flag APPLYING_CONFIG
        self.assertEqual(view["consistency_state"], "APPLYING_CONFIG")
        self.assertEqual(view["config_revision"], 5)
        self.assertEqual(view["status_config_revision"], 4)
        self.assertEqual(view["status_revision"], 10)

        # In GUI render: verify stale reason is NOT displayed
        app = SettingsWindow.__new__(SettingsWindow)
        app.logs_expanded = True
        app.view = view
        app.dirty_fields = {}
        app.expanded_profiles = set()
        app.buttons = []
        app.scroll_frame = MagicMock()
        app.search = MagicMock()
        app.make_badge = MagicMock(return_value=MagicMock())
        app.log_filter_var = MagicMock()
        app.refresh_logs = MagicMock()

        with patch("tkinter.Frame", return_value=MagicMock()), \
             patch("tkinter.Label") as mock_label, \
             patch("tkinter.Text", return_value=MagicMock()), \
             patch("tkinter.ttk.Combobox", return_value=MagicMock()), \
             patch("tkinter.ttk.Scrollbar", return_value=MagicMock()), \
             patch("core.gui.Card", return_value=MagicMock()):
            app.render_diagnostics_tab()

            # Check all text passed to tk.Label
            rendered_texts = [call.kwargs.get("text", "") for call in mock_label.call_args_list if "text" in call.kwargs]
            # Old stale reason must NOT appear
            self.assertNotIn("Old automatic reasoning", rendered_texts)
            # Applying state must be communicated
            self.assertTrue(any("套用新設定中" in txt for txt in rendered_texts))

    # 3. Coalescing single flight prevents duplicate render
    def test_coalescing_single_flight_prevents_duplicate_render(self):
        from core.gui import SettingsWindow

        app = SettingsWindow.__new__(SettingsWindow)
        app.logs_expanded = True
        app.busy = False
        app.one_shot = False
        app.modal_depth = 0
        app._sync_in_progress = False
        app._sync_pending = False
        app._last_sync_sig = None
        app._last_config_revision = 0
        app._last_status_revision = 0
        app.root = MagicMock()
        app.display = MagicMock()

        sig1 = (1001, 2001, 500)

        mock_view = {
            "config": Config(revision=2),
            "status_revision": 3,
            "consistency_state": "CONSISTENT",
        }

        # Simulate sync already in progress when FocusIn or timer fires
        app._sync_in_progress = True
        app._check_external_sync()

        # Must mark sync as pending and return immediately without running display
        self.assertTrue(app._sync_pending)
        app.display.assert_not_called()

        # Now first sync finishes
        app._sync_in_progress = False

        with patch("core.gui.get_sync_signatures", return_value=sig1), \
             patch("core.gui.read_view", return_value=mock_view):

            # When _check_external_sync runs normally
            app._check_external_sync()
            self.assertEqual(app.display.call_count, 1)

            # A subsequent immediate call with identical signature must NOT re-render
            app._check_external_sync()
            self.assertEqual(app.display.call_count, 1)

    # 4. Active entry editing preserves text while status updates
    def test_active_entry_editing_preserves_text_while_status_updates(self):
        from core.gui import SettingsWindow

        app = SettingsWindow.__new__(SettingsWindow)
        app.logs_expanded = True
        app.root = MagicMock()
        app.busy = False
        app.readonly = False
        app.buttons = []
        app.usbs = []
        app.scroll_frame = MagicMock()
        app.profiles = {pairing_key(self.config.ipad.to_dict()): self.config.ipad.to_dict()}
        app.dirty_fields = {}
        app.expanded_profiles = {"uuid-1234"}
        app.make_badge = MagicMock(return_value=MagicMock())
        app.view = {
            "config": self.config,
            "consistency_state": "CONSISTENT",
            "status_revision": 1,
            "fresh": True,
            "actual": {"sidecar_devices": [], "usb_devices": [], "discovery_errors": {}},
        }

        # User is actively typing "Draft New iPad Name" in the field
        kid = "uuid-1234"
        app.dirty_fields[f"name.{kid}"] = {"value": "Draft New iPad Name", "base_revision": 1}

        with patch("tkinter.Frame", return_value=MagicMock()), \
             patch("tkinter.Label", return_value=MagicMock()), \
             patch("tkinter.Entry", return_value=MagicMock()), \
             patch("tkinter.StringVar") as mock_string_var, \
             patch("core.gui.Card", return_value=MagicMock()):

            app.render_paired_tab()

            # Verify StringVar was initialized with the dirty draft value, NOT the config value
            var_calls = [call.kwargs.get("value") for call in mock_string_var.call_args_list if "value" in call.kwargs]
            self.assertIn("Draft New iPad Name", var_calls)
            self.assertNotIn("iPad Pro", var_calls)

    # 5. Optimistic concurrency rejects stale expected revision
    def test_optimistic_concurrency_rejects_stale_expected_revision(self):
        cls = DAEMON["PadPilotDaemon"]
        daemon = cls.__new__(cls)
        daemon.config = Config(revision=5, mode=OperationMode.AUTOMATIC)
        daemon.detector = MagicMock()
        daemon.engine = MagicMock()

        # 1. Daemon direct method check: stale expected_revision=4 against revision=5
        with patch.dict(cls.handle_client_cmd.__globals__, {"save_config": MagicMock()}):
            with self.assertRaises(ConflictError) as ctx:
                daemon.apply_config_change("set_mode", {"mode": "manual_only"}, expected_revision=4)
            self.assertIn("CONFIG_CONFLICT", str(ctx.exception))

            # 2. Daemon JSON IPC response check
            req = {
                "id": "req-1",
                "command": "set_mode",
                "params": {"mode": "manual_only"},
                "expected_revision": 4,
            }
            resp_str = daemon.handle_client_cmd(json.dumps(req))
            resp = json.loads(resp_str)
            self.assertFalse(resp["ok"])
            self.assertEqual(resp["error"], "CONFIG_CONFLICT")
            self.assertEqual(resp["config_revision"], 5)

            # 3. Success when expected_revision matches
            req["expected_revision"] = 5
            resp_str = daemon.handle_client_cmd(json.dumps(req))
            resp = json.loads(resp_str)
            self.assertTrue(resp["ok"])
            self.assertEqual(resp["config_revision"], 6)

        # 4. CLI submit_settings check: offline mutation conflict
        with patch.dict(CLI["submit_settings"].__globals__, {
            "send_daemon_cmd": MagicMock(return_value="Daemon is not running. (Socket not found)"),
            "load_config": MagicMock(return_value=Config(revision=8)),
            "save_config": MagicMock(),
        }):
            with self.assertRaises(RuntimeError) as ctx:
                CLI["submit_settings"]("set_mode", {"mode": "manual_only"}, expected_revision=7)
            self.assertIn("CONFIG_CONFLICT", str(ctx.exception))

    def test_menu_reads_fresh_config_and_rejects_mixed_revisions(self):
        config = Config(auto_detect_ipad=False, revision=2, mode=OperationMode.MANUAL_ONLY,
                        ipad=IpadConfig(name='New iPad Name'))
        status = {'config_revision': 2, 'timestamp': time.time(), 'actual': {'sidecar_devices': []},
                  'status_details': {'reason': 'Do not expose stale reasoning'}}
        for status_rev, expected in ((2, '運作中'), (1, '套用設定中…'), (3, '同步狀態重新讀取中…')):
            status['config_revision'] = status_rev
            rows = MENU['render'](status, config.to_dict(), True)['items']
            titles = [r['title'] for r in rows]
            self.assertIn('模式：僅手動｜' + expected, titles)
            self.assertIn('目前目標：New iPad Name', titles)
            modes = [r for r in rows if r['args'][:1] == ['set-mode'] and r['checked']]
            self.assertEqual([r['args'] for r in modes], [['set-mode', 'manual_only']])
            self.assertFalse(any('Do not expose' in title for title in titles))
            if status_rev != 2:
                self.assertFalse(any(r['enabled'] and r['args'][:1] == ['action']
                                     for r in rows if r['args'] != ['action', 'refresh']))

    # 9. Rename inactive iPad increments revision and saves without display transition
    def test_rename_inactive_ipad_increments_revision_and_saves_without_display_transition(self):
        cls = DAEMON["PadPilotDaemon"]
        daemon = cls.__new__(cls)
        daemon.config_lock = threading.Lock()
        u1 = "00000000-0000-0000-0000-000000000001"
        u2 = "00000000-0000-0000-0000-000000000002"
        daemon.config = Config(
            revision=1,
            ipad=IpadConfig(name="Main iPad", sidecar_uuid=u1, usb_serial="USB-MAIN"),
            paired_ipads=[
                IpadConfig(name="Main iPad", sidecar_uuid=u1, usb_serial="USB-MAIN"),
                IpadConfig(name="Old Second iPad", sidecar_uuid=u2, usb_serial="USB-SECOND"),
            ],
        )
        daemon.detector = MagicMock()
        daemon.engine = MagicMock()

        mock_save = MagicMock()
        with patch.dict(cls.apply_config_change.__globals__, {
            "save_config": mock_save,
        }):
            needs_transition, new_cfg = daemon.apply_config_change(
                "save_pairing",
                {
                    "ipad": {"name": "New Second iPad Name", "sidecar_uuid": u2, "usb_serial": "USB-SECOND"},
                    "activate": False,
                },
            )

            # Display transition must NOT be triggered
            self.assertFalse(needs_transition)
            # Revision must be incremented
            self.assertEqual(new_cfg.revision, 2)
            # Config must be saved
            self.assertEqual(mock_save.call_count, 1)
            saved_cfg = mock_save.call_args[0][0]
            self.assertEqual(saved_cfg.revision, 2)
            self.assertEqual(saved_cfg.paired_ipads[1].name, "New Second iPad Name")

    # 10. GUI daemon-owned change does not send duplicate client notification
    def test_gui_daemon_owned_change_does_not_send_duplicate_client_notification(self):
        from core.gui import SettingsWindow
        app = MagicMock(spec=SettingsWindow)
        app.readonly = False
        app.busy = False
        app.view = {"config": Config(revision=1, mode=OperationMode.AUTOMATIC)}
        app.root = MagicMock()
        app.notice = MagicMock()
        app.display = MagicMock()
        app.dirty_fields = {}

        with patch("core.gui.confirm", return_value=True), \
             patch("subprocess.run") as mock_subproc, \
             patch("core.gui.read_view", return_value={"config": Config(revision=2, mode=OperationMode.MANUAL_ONLY)}), \
             patch("subprocess.Popen") as mock_launch:

            mock_subproc.return_value = MagicMock(returncode=0, stdout="OK: 設定已更新", stderr="")

            SettingsWindow.set_mode(app, "manual_only")

            # Check task work was submitted
            task_call = app.task.call_args
            self.assertIsNotNone(task_call)
            work_fn, complete_fn = task_call[0]

            msg, view = work_fn()
            complete_fn((msg, view))

            # The GUI reads the updated snapshot; no separate menu process is launched.
            mock_launch.assert_not_called()

    # 11. Semantic config equality ignores revision and timestamp
    def test_semantic_config_equality_ignores_revision_and_timestamp(self):
        c1 = Config(revision=1, updated_at=100.0, mode=OperationMode.AUTOMATIC)
        c2 = Config(revision=2, updated_at=200.0, mode=OperationMode.AUTOMATIC)
        # Equality ignores revision and updated_at
        self.assertTrue(c1.content_equals(c2))
        self.assertEqual(c1.semantic_dict(), c2.semantic_dict())

        # Change in mode is detected
        c3 = Config(revision=1, updated_at=100.0, mode=OperationMode.MANUAL_ONLY)
        self.assertFalse(c1.content_equals(c3))

        # Change in paired iPads is detected
        c4 = copy.deepcopy(c1)
        c4.paired_ipads.append(IpadConfig(name="iPad Air", sidecar_uuid="uuid-999"))
        self.assertFalse(c1.content_equals(c4))

        # Non-Config comparison returns False safely
        self.assertFalse(c1.content_equals({"revision": 1}))


if __name__ == "__main__":
    unittest.main()
