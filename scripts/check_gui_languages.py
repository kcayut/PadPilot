#!/usr/bin/env python3
"""Exercise real widgets in every language without changing config or hardware."""
import copy
import sys
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.config import Config
from core import __version__
from core.gui import GITHUB_URL, SettingsWindow, confirm, get_documentation_url, get_troubleshooting_url
from core.i18n import LANGUAGES, set_language, tr
from scripts.check_gui_layout import descendants


def main():
    cfg = Config.from_dict({'ipad': {'name': '我的 iPad', 'sidecar_uuid': '11111111-1111-4111-8111-111111111111', 'usb_serial': 'USB123'}})
    view = {'config': cfg, 'actual': {'sidecar_devices': [{'uuid': '22222222-2222-4222-8222-222222222222', 'name': 'New iPad'}], 'online_displays': [{'name':'Display', 'width':1920, 'height':1080, 'is_main':True}]}, 'fresh': True, 'identifiers': [{'name':'PadPilotVirtual','deviceType':'VirtualScreen','displayID':'7'}], 'status': {}}
    root = tk.Tk()
    try:
        with patch.object(SettingsWindow, 'search'), patch.object(SettingsWindow, '_check_external_sync'):
            app = SettingsWindow(root, page='about')
            assert app.current_tab == 'about'
            root.geometry('840x500')
            app.change = MagicMock()
            for language in (*LANGUAGES, 'zh-Hant'):
                current = copy.deepcopy(view)
                current['config'].language = language
                app.display(current)
                root.update()
                assert root.title() == tr('PadPilot — 螢幕與配對管理')
                assert not any(w.winfo_class() == 'Label' and w.cget('text') == f'v{__version__}'
                               for w in descendants(app.sidebar))
                with patch('core.gui.webbrowser.open') as open_document:
                    for label, path in [('📖 使用說明', 'README.md'), ('🩺 疑難排解', 'docs/TROUBLESHOOTING.md')]:
                        link = next(w for w in descendants(app.sidebar)
                                    if w.winfo_class() == 'Label' and w.cget('text') == tr(label))
                        link.event_generate('<Button-1>')
                        root.update()
                        open_document.assert_called_with(get_documentation_url(path, language))
                for tab in ('paired', 'search', 'settings', 'displays', 'virtual', 'diagnostics', 'about'):
                    app.advanced_expanded = False
                    app.select_tab(tab)
                    if tab == 'settings':
                        next(w for w in descendants(app.scroll_frame)
                             if w.winfo_class() == 'TButton' and w.cget('text') == '▸ ' + tr('進階選項')).invoke()
                    if tab == 'paired':
                        app.expanded_profiles.add(cfg.ipad.sidecar_uuid)
                        app.render_current_tab()
                    root.update()
                    assert app.scroll_frame.winfo_children()
                    for w in descendants(app.scroll_frame):
                        if w.winfo_class() in ('Label', 'TButton', 'TCheckbutton'):
                            if language == 'en':
                                label = str(w.cget('text')).replace('我的 iPad', '')
                                assert not any('\u4e00' <= c <= '\u9fff' for c in label), label
                            right = w.winfo_rootx() + w.winfo_reqwidth()
                            if right > root.winfo_rootx() + root.winfo_width() + 2:
                                raise AssertionError((language, tab, w.cget('text'), 'overflows window'))
                    if tab == 'settings':
                        picker = app.header_language_picker
                        assert picker.get() == LANGUAGES[language]
                        picker.current(list(LANGUAGES.keys()).index('en'))
                        picker.event_generate('<<ComboboxSelected>>')
                        root.update()
                        assert app.change.call_args.args == ('set_language', {'language': 'en'})
                    if tab == 'about':
                        assert app.title_label.cget('text') == tr('關於')
                        assert app.version_label.cget('text') == f'v{__version__}'
                        assert app.version_label.winfo_ismapped()
                        nav = app.nav_widgets['about'][1]
                        assert nav.winfo_rooty() + nav.winfo_height() <= app.refresh_btn.winfo_rooty()
                        with patch('core.gui.webbrowser.open') as open_link:
                            app.github_button.invoke()
                            open_link.assert_called_once_with(GITHUB_URL)
                            open_link.reset_mock()
                            assert set(app.donation_buttons) == {'Buy Me a Coffee', 'PayPal'}
                            for button in app.donation_buttons.values():
                                assert button.instate(['disabled']) and not button.cget('command')
                                button.invoke()
                            open_link.assert_not_called()
                        # A future recipient URL enables only its own button; never open a real payment page here.
                        for provider in ('Buy Me a Coffee', 'PayPal'):
                            with patch.dict('core.gui.DONATION_URLS', {provider: 'https://example.com/support'}), \
                                 patch('core.gui.webbrowser.open') as open_link:
                                app.render_current_tab()
                                button = app.donation_buttons[provider]
                                assert not button.instate(['disabled'])
                                button.invoke()
                                open_link.assert_called_once_with('https://example.com/support')
                                assert all(b.instate(['disabled']) for name, b in app.donation_buttons.items()
                                           if name != provider)
                app.view['system_checks'] = [('BetterDisplay 控制介面', '未啟用')]
                app.select_tab('diagnostics')
                root.update()
                with patch('core.gui.webbrowser.open') as open_document:
                    link = next(w for w in descendants(app.diagnostic_hosts['system_checks'])
                                if w.winfo_class() == 'Label' and w.cget('text') == tr('說明 ↗'))
                    link.event_generate('<Button-1>')
                    root.update()
                    open_document.assert_called_with(get_troubleshooting_url('BetterDisplay 控制介面', language))
                def dismiss():
                    dialogs = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
                    buttons = [w for w in descendants(dialogs[0]) if w.winfo_class() == 'TButton']
                    assert {w.cget('text') for w in buttons} == {tr('是'), tr('否')}
                    next(w for w in buttons if w.cget('text') == tr('否')).invoke()
                root.after(100, dismiss)
                assert not confirm(root, tr('確定刪除配對?'), tr('配對紀錄已變更或不存在，請重新開啟清單。'))
            print('PASS: all languages, seven tabs, About version/GitHub/donation placeholders, localized document/help links, saved selection, settings dispatch, and confirmation dialogs.')
    finally:
        root.destroy()
        set_language('zh-Hant')


if __name__ == '__main__':
    main()
