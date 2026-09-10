#!/usr/bin/env python3
"""Render real Tk widgets at the minimum width without controlling hardware."""
import sys
import copy
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import Config
from core import __version__
from core.gui import SettingsWindow


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    cfg = Config.from_dict({'auto_detect_ipad': False, 'ipad': {'name': 'iPad pro m2',
        'sidecar_uuid': '11111111-1111-4111-8111-111111111111', 'usb_serial': 'USB123'}})
    view = {'config': cfg, 'actual': {}, 'fresh': True, 'identifiers': [], 'status': {},
            'system_checks': [('登入啟動', '已設定')]}
    root = tk.Tk()
    try:
        with patch.object(SettingsWindow, 'search'), patch.object(SettingsWindow, '_check_external_sync'):
            app = SettingsWindow(root)
            root.geometry('840x500')
            app.display(view)
            root.update()
            version_label = app.version_label
            assert version_label.cget('text') == f'v{__version__}'
            assert version_label.winfo_ismapped()
            assert version_label.winfo_rootx() + version_label.winfo_reqwidth() <= app.sidebar.winfo_rootx() + app.sidebar.winfo_width()
            names = ['作為副螢幕', '設為主螢幕', '中斷連線', '重新連線']
            controls = [w for w in descendants(root) if w.winfo_class() == 'TButton' and w.cget('text') in names]
            exp_btns = [w for w in descendants(root) if w.winfo_class() == 'TButton' and '設定' in w.cget('text')]
            ctrl_lbls = [w for w in descendants(root) if w.winfo_class() == 'Label' and w.cget('text') == '控制']
            usb_lbls = [w for w in descendants(root) if w.winfo_class() == 'Label' and 'USB 序號' in w.cget('text')]
            assert len(controls) == 4
            assert len({w.winfo_rooty() for w in controls}) == 1
            if exp_btns and usb_lbls:
                exp_btn = exp_btns[0]
                usb_lbl = usb_lbls[0]
                assert abs(exp_btn.winfo_rooty() - usb_lbl.winfo_rooty()) <= 6
            if exp_btns:
                exp_btn = exp_btns[0]
            if ctrl_lbls:
                ctrl_lbl = ctrl_lbls[0]
                assert abs(ctrl_lbl.winfo_rooty() - controls[0].winfo_rooty()) <= 6
            for w in controls:
                assert w.winfo_rootx() >= root.winfo_rootx()
                assert w.winfo_rootx() + w.winfo_width() <= root.winfo_rootx() + root.winfo_width()
                if exp_btns:
                    assert w.winfo_rootx() + w.winfo_width() <= exp_btn.winfo_rootx()
                assert not w.instate(['disabled'])
                assert w.cget('command')
            # Heartbeats must preserve actual widgets, focus, drafts and scrolling.
            app.toggle_profile_expand(cfg.ipad.sidecar_uuid)
            root.update()
            entry = next(w for w in descendants(root) if w.winfo_class() == 'Entry')
            entry.delete(0, 'end')
            entry.insert(0, '未儲存的名稱')
            entry.icursor(3)
            entry.focus_force()
            root.update()
            children = app.scroll_frame.winfo_children()
            old_y = app.canvas.yview()
            for revision in range(1, 4):
                heartbeat = copy.deepcopy(view)
                heartbeat.update(status_revision=revision, hardware_snapshot_age=revision)
                heartbeat['actual']['timestamp'] = revision
                heartbeat['status'] = {'timestamp': revision, 'status_revision': revision,
                                       'actual': heartbeat['actual']}
                app.display(heartbeat)
                root.update()
                assert app.version_label is version_label
                assert app.scroll_frame.winfo_children() == children
                assert entry.get() == '未儲存的名稱' and entry.index('insert') == 3
                assert root.focus_get() == entry
                assert app.canvas.yview() == old_y
                assert app._last_status_revision == revision
            stale = copy.deepcopy(heartbeat)
            stale['fresh'] = False
            app.display(stale)
            assert not entry.winfo_exists(), 'Freshness changes must still update the UI'
            app.display(heartbeat)
            app.select_tab('diagnostics')
            root.update()
            assert not any(w.winfo_class() in ('Entry', 'TEntry') for w in descendants(app.scroll_frame))
            assert app.log_text.winfo_exists()
            assert set(app.diagnostic_hosts) == {'decision', 'system_checks', 'authenticated_checks', 'logs'}
            refreshes = [w for w in descendants(app.scroll_frame)
                         if w.winfo_class() == 'TButton' and w.cget('text') == '重新整理']
            assert len(refreshes) == 3
            retained = {section: app.diagnostic_hosts[section].winfo_children()
                        for section in ('system_checks', 'authenticated_checks', 'logs')}
            log_text = app.log_text
            log_text.yview_moveto(0.25)
            root.update()
            log_top = log_text.index('@0,0')
            changed = copy.deepcopy(heartbeat)
            changed['status']['runtime'] = {'last_error': '驗證錯誤更新'}
            app.display(changed)
            root.update()
            assert app.log_text is log_text and log_text.index('@0,0') == log_top
            assert all(app.diagnostic_hosts[s].winfo_children() == widgets
                       for s, widgets in retained.items())
            assert any(w.winfo_class() == 'Label' and w.cget('text') == '驗證錯誤更新'
                       for w in descendants(app.diagnostic_hosts['decision']))
            decision = app.diagnostic_hosts['decision'].winfo_children()
            app.toggle_logs()
            root.update()
            assert not any(w.winfo_class() == 'Text' for w in descendants(app.scroll_frame))
            app.toggle_logs()
            root.update()
            assert app.log_text.winfo_exists()
            assert app.diagnostic_hosts['decision'].winfo_children() == decision
            app.select_tab('settings')
            root.update()
            from unittest.mock import MagicMock
            app.change = MagicMock()
            toggles = [w for w in descendants(app.scroll_frame)
                       if w.winfo_class() == 'TButton' and w.cget('text') in ('啟用', '停用')]
            assert len(toggles) == 2
            assert all(not w.winfo_ismapped() for w in toggles)
            advanced = next(w for w in descendants(app.scroll_frame)
                            if w.winfo_class() == 'TButton' and w.cget('text') == '▸ 進階選項')
            advanced.invoke()
            root.update()
            assert all(w.winfo_ismapped() for w in toggles)
            advanced.invoke()
            root.update()
            assert all(not w.winfo_ismapped() for w in toggles)
            advanced.invoke()
            root.update()
            for button in toggles:
                assert button.winfo_rootx() + button.winfo_width() <= root.winfo_rootx() + root.winfo_width()
                button.invoke()
            assert app.change.call_args_list[0].args == ('set_usb_event_wakeup', {'enabled': False})
            assert app.change.call_args_list[1].args == ('set_auto_detect_ipad', {'enabled': True})
            cfg.auto_detect_ipad = True
            app.display(dict(heartbeat, config=cfg))
            app.select_tab('paired')
            root.update()
            controls = [w for w in descendants(app.scroll_frame)
                        if w.winfo_class() == 'TButton' and w.cget('text') in names]
            assert len(controls) == 4 and all(not w.instate(['disabled']) for w in controls)
            app.control_ipad = MagicMock()
            for button, action in zip(controls, ('use_ipad_secondary', 'use_ipad_main', 'disconnect_ipad', 'reconnect_sidecar')):
                button.invoke()
                app.control_ipad.assert_called_with(cfg.ipad.to_dict(), action)
            cfg.ipad = type(cfg.ipad)()
            app.display(dict(heartbeat, config=cfg))
            root.update()
            controls = [w for w in descendants(app.scroll_frame)
                        if w.winfo_class() == 'TButton' and w.cget('text') in names]
            assert len(controls) == 4 and all(w.instate(['disabled']) for w in controls)
            print('PASS: 840px layout; heartbeat preserves widgets/focus/drafts/scroll; freshness and errors update; diagnostics and logs refresh independently; USB/discovery toggles dispatch correctly; designated pairing controls work with discovery enabled; other pairings stay disabled.')
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
