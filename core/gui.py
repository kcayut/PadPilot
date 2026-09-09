"""Native desktop pairing and read-only settings; no web server or new packages."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from core.betterdisplay import BetterDisplayCLI
from core.config import Config, get_config_file_path, read_status
from core.detector import DisplayDetector
from core.models import pairing_key
from core.settings import is_virtual_device

ROOT = Path(__file__).resolve().parents[1]
MODES = {'automatic': '自動', 'manual_only': '僅手動', 'prefer_ipad': '偏好 iPad'}
BG, WHITE, INK, MUTED, BLUE = '#f3f5f9', '#ffffff', '#172b4d', '#607089', '#235fd3'


def short_id(value: str) -> str:
    return value[:8] + '…' + value[-6:] if len(value) > 20 else value or '未設定'


def read_view(scan: bool = False) -> dict:
    """Read-only, including when no configuration exists yet."""
    path = get_config_file_path()
    cfg = Config.from_dict(json.loads(path.read_text())) if path.exists() else Config()
    status = read_status() or {}
    actual = status.get('actual', {})
    stamp = actual.get('timestamp', 0)
    fresh = isinstance(stamp, (int, float)) and 0 <= time.time() - stamp <= 120
    identifiers = []
    if scan:
        bd = BetterDisplayCLI(cfg.betterdisplaycli_path)
        detector = DisplayDetector(cfg, bd)
        observed, _ = detector.observe()
        actual, fresh = observed.to_dict(), True
        identifiers = bd.get_display_identifiers()
        if bd.identifiers_error:
            actual['discovery_errors']['identifiers'] = bd.identifiers_error
    return {'config': cfg, 'actual': actual, 'fresh': fresh, 'identifiers': identifiers,
            'scanned': scan, 'status': status}


def device_status(device: dict, view: dict) -> str:
    actual, cfg = view['actual'], view['config']
    if not view['fresh']:
        return '狀態未知'
    if device == cfg.ipad.to_dict() and actual.get('sidecar_connected'):
        return '已連線'
    if any(device.get('sidecar_uuid') and d.get('uuid', '').upper() == device['sidecar_uuid'].upper()
           for d in actual.get('sidecar_devices', [])):
        return '已偵測到 Sidecar'
    if any(device.get('usb_serial') and u.get('serial') == device['usb_serial']
           for u in actual.get('usb_devices', [])):
        return '僅 USB 已接上'
    return '狀態未知' if actual.get('discovery_errors') else '未偵測到'


def send_change(action: str, payload: dict) -> str:
    result = subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'change-settings', action],
                            input=json.dumps(payload, ensure_ascii=False), text=True,
                            capture_output=True, timeout=70)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '設定更新失敗')
    return result.stdout.strip()


def confirm(parent: tk.Tk, question: str, detail: str) -> bool:
    """Explicit Chinese Yes/No; closing or Escape always means No."""
    dialog = tk.Toplevel(parent)
    dialog.title('PadPilot')
    dialog.configure(background=WHITE)
    dialog.resizable(False, False)
    if parent.state() != 'withdrawn':
        dialog.transient(parent)
    answer = False

    def finish(value=False):
        nonlocal answer
        answer = value
        dialog.destroy()

    box = ttk.Frame(dialog, style='Card.TFrame', padding=24)
    box.pack(fill='both', expand=True)
    ttk.Label(box, text=question, style='Section.TLabel').pack(anchor='w')
    ttk.Label(box, text=detail, wraplength=440, style='Card.TLabel', justify='left').pack(
        anchor='w', fill='x', pady=(12, 22))
    row = ttk.Frame(box, style='Card.TFrame')
    row.pack(fill='x')
    yes = ttk.Button(row, text='是', command=lambda: finish(True), style='Accent.TButton')
    yes.pack(side='right', padx=(10, 0))
    no = ttk.Button(row, text='否', command=finish)
    no.pack(side='right')
    no.focus_set()
    dialog.bind('<Escape>', lambda _: finish())
    no.bind('<Return>', lambda _: finish())
    yes.bind('<Return>', lambda _: finish(True))
    dialog.protocol('WM_DELETE_WINDOW', finish)
    dialog.update_idletasks()
    width, height = 500, max(210, dialog.winfo_reqheight())
    dialog.geometry(f'{width}x{height}+{(dialog.winfo_screenwidth()-width)//2}+{(dialog.winfo_screenheight()-height)//2}')
    dialog.wait_visibility()
    dialog.grab_set()
    parent.wait_window(dialog)
    return answer


class SettingsWindow:
    def __init__(self, root: tk.Tk, page: str = 'wizard'):
        self.root, self.readonly = root, page == 'settings'
        self.view = {'config': Config(), 'actual': {}, 'identifiers': [], 'fresh': False, 'status': {}}
        self.busy = False
        self.results = queue.Queue()
        self.buttons = []
        self.profiles, self.candidates, self.virtuals, self.usbs = {}, {}, {}, []
        root.title('PadPilot — 設定總覽' if self.readonly else 'PadPilot — 配對精靈')
        root.geometry('1020x660')
        root.minsize(840, 590)
        root.configure(background=BG)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Helvetica', 13), foreground=INK)
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG)
        style.configure('Card.TFrame', background=WHITE)
        style.configure('Card.TLabel', background=WHITE)
        style.configure('Title.TLabel', font=('Helvetica', 26, 'bold'), background=BG)
        style.configure('Section.TLabel', font=('Helvetica', 16, 'bold'), background=WHITE)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('TButton', padding=(15, 9), background=WHITE, borderwidth=1,
                        bordercolor='#dce3ef', lightcolor=WHITE, darkcolor=WHITE)
        style.configure('Accent.TButton', background=BLUE, foreground=WHITE)
        style.map('Accent.TButton', background=[('disabled', '#d9dfeb'), ('active', '#174aa9')],
                  foreground=[('disabled', '#7b8799')])
        style.configure('Treeview', rowheight=32, background=WHITE, fieldbackground=WHITE, borderwidth=0)
        style.configure('Treeview.Heading', font=('Helvetica', 12, 'bold'), background='#e9eef6', padding=9,
                        relief='flat', bordercolor='#e9eef6', lightcolor='#e9eef6', darkcolor='#e9eef6')
        style.map('Treeview', background=[('selected', '#dce9ff')], foreground=[('selected', INK)])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(18, 12), background='#e9eef6', borderwidth=0,
                        bordercolor=BG, lightcolor=BG, darkcolor=BG)
        style.map('TNotebook.Tab', background=[('selected', WHITE)], foreground=[('selected', BLUE)])
        outer = ttk.Frame(root, padding=(24, 20))
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='設定總覽' if self.readonly else '連接你的螢幕', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='唯讀檢視 · 設定、配對紀錄與目前連線' if self.readonly else
                  '管理已配對裝置、搜尋 iPad，並選擇你的虛擬備援螢幕。', style='Muted.TLabel').pack(anchor='w', pady=(5, 14))
        self.summary = ttk.Label(outer, text='正在讀取…', style='Muted.TLabel')
        self.summary.pack(anchor='w', pady=(0, 14))
        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        if self.readonly:
            page = self.tab('目前設定')
            self.settings_tree = self.table(page, [('key', '設定項目', 240), ('value', '目前值', 610)])
        paired = self.tab('已配對裝置')
        self.paired_tree = self.table(paired, [('name', '裝置名稱', 180), ('state', '狀態 / 目標', 185),
                                             ('uuid', 'Sidecar UUID', 290), ('usb', 'USB 序號', 240)])
        self.pair_detail = ttk.Label(paired, text='選擇一台裝置以查看完整識別資料。', style='Card.TLabel', wraplength=880)
        self.pair_detail.pack(anchor='w', pady=(10, 5))
        self.paired_tree.bind('<<TreeviewSelect>>', self.selection_changed)
        if not self.readonly:
            row = self.row(paired)
            self.select_button = self.button(row, '設為控制目標', self.select_target)
            self.delete_button = self.button(row, '刪除配對', self.delete_selected)
            self.search_page = self.tab('搜尋與配對')
            self.build_search()
            self.virtual_page = self.tab('虛擬備援')
            self.build_virtual()
        else:
            connected = self.tab('已連線螢幕')
            self.connected_tree = self.table(connected, [('name', '螢幕名稱', 260), ('type', '類型', 170),
                                                        ('role', '角色', 130), ('size', '解析度', 180)])
            ttk.Label(connected, text='此處列出本次查詢已上線的螢幕；Sidecar 候選裝置不算已連線。',
                      style='Card.TLabel').pack(anchor='w', pady=(12, 0))
        footer = ttk.Frame(outer)
        footer.pack(side='bottom', fill='x', pady=(14, 0), before=self.tabs)
        self.notice = ttk.Label(footer, text='正在讀取…', style='Muted.TLabel', wraplength=780)
        self.notice.pack(side='left')
        self.progress = ttk.Progressbar(footer, length=95, mode='indeterminate')
        self.progress.pack(side='right')
        self.selection_changed()

    def tab(self, title):
        frame = ttk.Frame(self.tabs, padding=18, style='Card.TFrame')
        self.tabs.add(frame, text=title)
        return frame

    def row(self, parent):
        row = ttk.Frame(parent, style='Card.TFrame')
        row.pack(fill='x', pady=(10, 0))
        return row

    def button(self, parent, text, command, accent=False):
        button = ttk.Button(parent, text=text, command=command,
                            style='Accent.TButton' if accent else 'TButton')
        button.pack(side='left', padx=(0, 10))
        self.buttons.append(button)
        return button

    def table(self, parent, columns, height=6):
        frame = ttk.Frame(parent, style='Card.TFrame')
        frame.pack(fill='both', expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', selectmode='browse', height=height)
        for key, label, width in columns:
            tree.heading(key, text=label)
            tree.column(key, width=width, minwidth=80, stretch=True)
        tree.grid(row=0, column=0, sticky='nsew')
        vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.tag_configure('odd', background='#f5f7fc')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def build_search(self):
        page = self.search_page
        row = self.row(page)
        self.button(row, '搜尋裝置', self.search, accent=True)
        ttk.Label(row, text='同一 Apple Account；開啟 Wi-Fi / 藍牙或接上 USB。', style='Card.TLabel').pack(side='left')
        self.candidate_tree = self.table(page, [('name', '可配對裝置', 240), ('state', '配對狀態', 160),
                                               ('uuid', 'Sidecar UUID', 450)], height=3)
        self.candidate_tree.bind('<<TreeviewSelect>>', self.choose_candidate)
        form = self.row(page)
        ttk.Label(form, text='裝置名稱', style='Card.TLabel').grid(row=0, column=0, sticky='w', pady=6)
        self.name = tk.StringVar()
        ttk.Entry(form, textvariable=self.name).grid(row=0, column=1, sticky='ew', padx=12)
        ttk.Label(form, text='對應 USB', style='Card.TLabel').grid(row=1, column=0, sticky='w', pady=6)
        self.usb_choice = ttk.Combobox(form, state='readonly', values=['略過 / 保留原 USB 設定'])
        self.usb_choice.current(0)
        self.usb_choice.grid(row=1, column=1, sticky='ew', padx=12)
        form.columnconfigure(1, weight=1)
        self.activate = tk.BooleanVar(value=False)
        ttk.Checkbutton(page, text='設為目前控制目標（可能依目前模式自動連線）', variable=self.activate).pack(anchor='w', pady=8)
        self.save_button = self.button(self.row(page), '儲存配對', self.save_candidate, accent=True)

    def build_virtual(self):
        page = self.virtual_page
        ttk.Label(page, text='選擇現有的虛擬螢幕作為無頭模式備援。', style='Section.TLabel').pack(anchor='w')
        ttk.Label(page, text='僅列出 BetterDisplay 確認的虛擬螢幕。此操作不會把實體螢幕轉為虛擬螢幕。',
                  style='Card.TLabel', wraplength=850).pack(anchor='w', pady=(8, 14))
        self.virtual_tree = self.table(page, [('name', '虛擬螢幕', 320), ('state', '連接狀態', 190),
                                             ('selected', '目前用途', 200)])
        self.virtual_tree.bind('<<TreeviewSelect>>', self.selection_changed)
        row = self.row(page)
        self.virtual_button = self.button(row, '指定為虛擬備援', self.set_virtual, accent=True)
        self.button(row, '重新搜尋', self.search)

    def fill(self, tree, rows):
        selection = tree.selection()
        tree.delete(*tree.get_children())
        for index, (key, values) in enumerate(rows):
            tree.insert('', 'end', iid=key, values=values, tags=('odd',) if index % 2 else ())
        if selection and tree.exists(selection[0]):
            tree.selection_set(selection[0])

    def display(self, view):
        self.view = view
        cfg, actual = view['config'], view['actual']
        self.summary.configure(text=f"模式  {MODES[cfg.mode.value]}     •     控制目標  {cfg.ipad.name or '尚未指定'}     •     虛擬備援  {cfg.virtual_display_name or '尚未指定'}")
        self.profiles = {pairing_key(p.to_dict()): p.to_dict() for p in cfg.paired_ipads}
        self.fill(self.paired_tree, [(key, (p['name'], device_status(p, view) + (' · 控制目標' if p == cfg.ipad.to_dict() else ''),
                                               short_id(p['sidecar_uuid']), short_id(p['usb_serial'])))
                                      for key, p in self.profiles.items()])
        if self.readonly:
            labels = {'mode': '運作模式', 'autostart_on_login': '登入時自動啟動', 'debounce_seconds': '防抖等待（秒）',
                      'max_retries': '最大重試次數', 'retry_interval': '重試間隔（秒）', 'cooldown_seconds': '冷卻時間（秒）',
                      'ignore_list': '忽略的名稱規則', 'virtual_display_name': '虛擬備援螢幕',
                      'betterdisplaycli_path': 'BetterDisplay CLI 路徑', 'swiftbar_plugin_id': 'Menu bar 外掛'}
            rows = []
            for key, value in cfg.to_dict().items():
                if key in ('ipad', 'paired_ipads'):
                    continue
                if key == 'mode': value = MODES.get(value, value)
                elif isinstance(value, bool): value = '是' if value else '否'
                elif isinstance(value, list): value = '、'.join(value) or '無'
                rows.append((key, (labels.get(key, key), value if value is not None else '自動偵測')))
            self.fill(self.settings_tree, rows)
            self.fill(self.connected_tree, [(str(i), (d['name'], '虛擬螢幕' if d.get('is_virtual') else 'Sidecar' if d.get('is_sidecar') else '實體螢幕',
                                                       '主螢幕' if d.get('is_main') else '副螢幕', f"{d.get('width', 0)} × {d.get('height', 0)}"))
                                                for i, d in enumerate(actual.get('online_displays', []))] if view['fresh'] else [])
        else:
            self.candidates = {d['uuid']: d for d in actual.get('sidecar_devices', []) if d.get('uuid')}
            self.fill(self.candidate_tree, [(key, (d['name'], '已配對' if any(p.get('sidecar_uuid', '').upper() == key.upper()
                         for p in self.profiles.values()) else '尚未配對', key)) for key, d in self.candidates.items()])
            self.usbs = [u for u in actual.get('usb_devices', []) if u.get('serial')]
            self.usb_choice.configure(values=['略過 / 保留原 USB 設定'] + [f"{u.get('product_name') or u.get('name')} · {u['serial']}" for u in self.usbs])
            self.usb_choice.current(0)
            self.virtuals = {str(i): d for i, d in enumerate(view['identifiers']) if is_virtual_device(d)}
            self.fill(self.virtual_tree, [(key, (d.get('name'), '已連接' if str(d.get('displayID', '0')).isdecimal() and int(d['displayID']) > 0 else '未連接',
                                                 '✓ 備援螢幕' if d.get('name') == cfg.virtual_display_name else ''))
                                          for key, d in self.virtuals.items()])
        errors = actual.get('discovery_errors', {})
        self.notice.configure(text=('部分狀態未知：' + '；'.join(errors.values())) if errors else
                              f"更新於 {time.strftime('%H:%M:%S')} · {len(self.profiles)} 台已配對" + (' · 本頁不提供變更操作' if self.readonly else ''))
        self.selection_changed()

    def selected(self, tree, records):
        selected = tree.selection()
        return records.get(selected[0]) if selected else None

    def selection_changed(self, _=None):
        p = self.selected(self.paired_tree, self.profiles)
        self.pair_detail.configure(text=f"Sidecar UUID：{p['sidecar_uuid'] or '未設定'}\nUSB 序號：{p['usb_serial'] or '未設定'}" if p else
                                   ('選擇一台裝置以查看完整識別資料。' if self.profiles else '尚無配對紀錄。'))
        if self.readonly:
            return
        for button, ready in ((self.delete_button, bool(p)),
                              (self.select_button, bool(p) and p != self.view['config'].ipad.to_dict()),
                              (self.save_button, bool(self.selected(self.candidate_tree, self.candidates))),
                              (self.virtual_button, bool(self.selected(self.virtual_tree, self.virtuals)))):
            button.state(['!disabled'] if ready and not self.busy else ['disabled'])

    def choose_candidate(self, _=None):
        device = self.selected(self.candidate_tree, self.candidates)
        self.name.set(device.get('name', '') if device else '')
        self.selection_changed()

    def task(self, work, complete):
        if self.busy:
            return
        self.busy = True
        for button in self.buttons: button.state(['disabled'])
        self.progress.start(12)
        self.notice.configure(text='處理中，請稍候…')

        def worker():
            try: self.results.put((True, work()))
            except Exception as error: self.results.put((False, str(error)))

        def poll():
            try: ok, value = self.results.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            self.busy = False
            self.progress.stop()
            for button in self.buttons: button.state(['!disabled'])
            self.selection_changed()
            if ok:
                complete(value)
            else:
                self.notice.configure(text='操作未完成；請檢查錯誤後重試。')
                messagebox.showerror('PadPilot', value, parent=self.root)
                if getattr(self, 'one_shot', False): self.root.destroy()

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, poll)

    def search(self):
        self.task(lambda: read_view(scan=True), self.display)

    def change(self, action, payload):
        if self.readonly or self.busy:
            return

        def work():
            message = send_change(action, payload)
            return message, read_view(scan=True)

        def complete(result):
            message, view = result
            if getattr(self, 'one_shot', False):
                self.root.destroy()
                return
            self.display(view)
            self.notice.configure(text=message)

        self.task(work, complete)

    def delete_selected(self, key=None):
        if self.readonly or self.busy: return
        p = self.profiles.get(key) if key else self.selected(self.paired_tree, self.profiles)
        if not p:
            messagebox.showerror('PadPilot', '配對紀錄已變更或不存在，請重新開啟清單。', parent=self.root)
            if getattr(self, 'one_shot', False): self.root.destroy()
            return
        detail = f"裝置：{p['name']}\n僅刪除 PadPilot 的配對紀錄，不解除 Apple 系統配對。"
        if p == self.view['config'].ipad.to_dict():
            detail += '\n這是目前控制目標；刪除後改為僅手動模式，保留目前螢幕連線。'
        if confirm(self.root, '確定刪除配對?', detail):
            self.change('delete_pairing', {'key': pairing_key(p)})
        elif getattr(self, 'one_shot', False):
            self.root.destroy()

    def select_target(self, key=None):
        if self.readonly or self.busy: return
        p = self.profiles.get(key) if key else self.selected(self.paired_tree, self.profiles)
        if not p:
            messagebox.showerror('PadPilot', '找不到配對紀錄。', parent=self.root)
            if getattr(self, 'one_shot', False): self.root.destroy()
            return
        if confirm(self.root, '設為目前控制目標?', f"裝置：{p['name']}\n將清除舊目標的暫時覆寫；依目前模式可能自動連線。"):
            self.change('save_pairing', {'ipad': p, 'activate': True})
        elif getattr(self, 'one_shot', False): self.root.destroy()

    def save_candidate(self):
        if self.readonly or self.busy: return
        d = self.selected(self.candidate_tree, self.candidates)
        if not d: return
        previous = next((p for p in self.profiles.values() if p.get('sidecar_uuid', '').upper() == d['uuid'].upper()), {})
        index = self.usb_choice.current()
        serial = self.usbs[index - 1]['serial'] if index > 0 else previous.get('usb_serial', '')
        payload = {'ipad': {'name': self.name.get().strip(), 'sidecar_uuid': d['uuid'], 'usb_serial': serial},
                   'activate': self.activate.get()}
        try:
            Config.from_dict(self.view['config'].to_dict()).remember_ipad(payload['ipad'], payload['activate'])
        except ValueError as error:
            messagebox.showerror('配對資料不完整', str(error), parent=self.root)
            return
        if payload['activate'] and not confirm(self.root, '儲存並設為控制目標?', '依目前模式可能自動連線至所選 iPad。'):
            return
        self.change('save_pairing', payload)

    def set_virtual(self):
        if self.readonly or self.busy: return
        d = self.selected(self.virtual_tree, self.virtuals)
        if d and confirm(self.root, '指定為虛擬備援?', f"螢幕：{d['name']}\n之後以此螢幕作為備援；依目前模式可能啟用它，不主動移除原有備援連線。"):
            self.change('set_virtual_display', {'name': d['name']})


def run_gui(page='wizard', delete=None, select=None):
    if page == 'settings' and (delete or select):
        raise ValueError('設定總覽是唯讀頁面')
    root = tk.Tk()
    app = SettingsWindow(root, page)
    if delete or select:
        root.withdraw()
        app.one_shot = True

        def ready(view):
            app.display(view)
            if delete: app.delete_selected(delete)
            else: app.select_target(select)

        app.task(read_view, ready)
    else:
        app.search()
    root.mainloop()
