#!/usr/bin/env python3
"""Render real Tk widgets at the minimum width without controlling hardware."""
import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import Config
from core.gui import SettingsWindow


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


def main():
    cfg = Config.from_dict({'ipad': {'name': 'iPad pro m2',
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
            names = ['作為副螢幕', '設為主螢幕', '中斷連線', '重新連線']
            controls = [w for w in descendants(root) if w.winfo_class() == 'TButton' and w.cget('text') in names]
            assert len(controls) == 4
            assert len({w.winfo_rooty() for w in controls}) == 1
            for w in controls:
                assert w.winfo_rootx() >= root.winfo_rootx()
                assert w.winfo_rootx() + w.winfo_width() <= root.winfo_rootx() + root.winfo_width()
                assert not w.instate(['disabled'])
                assert w.cget('command')
            app.select_tab('diagnostics')
            root.update()
            assert not any(w.winfo_class() in ('Entry', 'TEntry') for w in descendants(app.scroll_frame))
            assert app.log_text.winfo_exists()
            assert set(app.diagnostic_hosts) == {'decision', 'system_checks', 'authenticated_checks', 'logs'}
            refreshes = [w for w in descendants(app.scroll_frame)
                         if w.winfo_class() == 'TButton' and w.cget('text') == '重新整理']
            assert len(refreshes) == 3
            app.toggle_logs()
            root.update()
            assert not any(w.winfo_class() == 'Text' for w in descendants(app.scroll_frame))
            app.toggle_logs()
            root.update()
            assert app.log_text.winfo_exists()
            print('PASS: 840px controls in one row; diagnostics has no search entry; logs collapse and expand.')
    finally:
        root.destroy()


if __name__ == '__main__':
    main()
