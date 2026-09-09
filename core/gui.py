"""Modern Apple-style Card UI for PadPilot settings, display topology, and pairing.

Zero external dependencies; pure Python standard library (tkinter + ttk).
"""
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

# macOS System Color Palette & Design Tokens
BG = '#f2f2f7'            # macOS System Gray 6 (Window Background)
SIDEBAR_BG = '#ebebf0'    # macOS Sidebar Background
SIDEBAR_BORDER = '#d8d8de'
CARD_BG = '#ffffff'       # Clean White Card
CARD_BORDER = '#e5e5ea'   # Subtle 1px Card Border
TEXT_PRIMARY = '#1c1c1e'  # Deep Charcoal Text (Always visible on white!)
TEXT_SECONDARY = '#636366'# Medium Gray Text
TEXT_TERTIARY = '#8e8e93' # Light Gray Text
BLUE = '#0071e3'          # Apple System Blue
BLUE_HOVER = '#005bb5'
BLUE_TINT = '#e8f2ff'
GREEN = '#34c759'         # Apple System Green
GREEN_BG = '#eaf8ee'
GREEN_FG = '#1e7e34'
ORANGE_BG = '#fff4e5'
ORANGE_FG = '#b25e00'
RED = '#ff3b30'           # Apple System Red
RED_BG = '#feeceb'
RED_BORDER = '#ffd2d0'

MODES = {
    'automatic': '自動模式',
    'manual_only': '僅手動模式',
    'prefer_ipad': '偏好 iPad 模式'
}
MODE_DESCS = {
    'automatic': '無實體螢幕時自動連線 iPad 並設為主螢幕；接有實體螢幕時保持安靜不干涉。',
    'manual_only': '自動化程序暫停，不主動連線或斷開，完全由使用者自 Menu Bar 手動操控。',
    'prefer_ipad': '即使已接上實體螢幕，依然優先連線 iPad 並將其作為主要顯示器。'
}


def short_id(value: str) -> str:
    return value[:8] + '…' + value[-6:] if len(value) > 20 else value or '未設定'


def read_view(scan: bool = False) -> dict:
    """Read-only view of configuration and hardware status."""
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
    return {
        'config': cfg,
        'actual': actual,
        'fresh': fresh,
        'identifiers': identifiers,
        'scanned': scan,
        'status': status
    }


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
    result = subprocess.run(
        [sys.executable, str(ROOT / 'bin/padpilot-cli'), 'change-settings', action],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=70
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '設定更新失敗')
    return result.stdout.strip()


def confirm(parent: tk.Tk, question: str, detail: str) -> bool:
    """Explicit macOS-style confirmation dialog; closing or Escape always means No."""
    dialog = tk.Toplevel(parent)
    dialog.title('PadPilot')
    dialog.configure(background='#ffffff')
    dialog.resizable(False, False)
    if parent.state() != 'withdrawn':
        dialog.transient(parent)
    answer = False

    def finish(value=False):
        nonlocal answer
        answer = value
        dialog.destroy()

    box = tk.Frame(dialog, bg='#ffffff', padx=22, pady=18)
    box.pack(fill='both', expand=True)

    # Icon + Title row
    title_row = tk.Frame(box, bg='#ffffff')
    title_row.pack(fill='x', anchor='w')
    is_danger = '刪除' in question
    icon_text = '⚠️' if is_danger else '📱'
    tk.Label(title_row, text=icon_text, font=('Helvetica Neue', 16), bg='#ffffff').pack(
        side='left', padx=(0, 8))
    tk.Label(title_row, text=question, font=('Helvetica Neue', 12, 'bold'),
             fg=TEXT_PRIMARY, bg='#ffffff').pack(side='left', anchor='w')

    # Detail message
    tk.Label(box, text=detail, wraplength=400, font=('Helvetica Neue', 10),
             fg=TEXT_SECONDARY, bg='#ffffff', justify='left').pack(
        anchor='w', fill='x', pady=(8, 16))

    # Action buttons
    row = tk.Frame(box, bg='#ffffff')
    row.pack(fill='x')

    yes_btn = ttk.Button(row, text='是', command=lambda: finish(True),
                         style='Danger.TButton' if is_danger else 'Accent.TButton')
    yes_btn.pack(side='right', padx=(8, 0))

    no_btn = ttk.Button(row, text='否', command=finish, style='Secondary.TButton')
    no_btn.pack(side='right')
    no_btn.focus_set()

    dialog.bind('<Escape>', lambda _: finish())
    no_btn.bind('<Return>', lambda _: finish())
    yes_btn.bind('<Return>', lambda _: finish(True))
    dialog.protocol('WM_DELETE_WINDOW', finish)
    dialog.update_idletasks()
    width, height = 460, max(175, dialog.winfo_reqheight() + 10)
    dialog.geometry(
        f'{width}x{height}+{(dialog.winfo_screenwidth()-width)//2}+{(dialog.winfo_screenheight()-height)//2}'
    )
    dialog.wait_visibility()
    dialog.grab_set()
    parent.wait_window(dialog)
    return answer


class Card(tk.Frame):
    """Modern macOS-style white container with a 1px soft border."""
    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, padx=12, pady=8, **kw):
        super().__init__(parent, bg=bg, highlightbackground=border, highlightcolor=border,
                         highlightthickness=1, bd=0, **kw)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill='both', expand=True, padx=padx, pady=pady)


class SettingsWindow:
    def __init__(self, root: tk.Tk, page: str = 'wizard'):
        self.root = root
        self.readonly = (page == 'settings')
        self.current_tab = 'settings' if self.readonly else 'paired'
        self.view = {'config': Config(), 'actual': {}, 'identifiers': [], 'fresh': False, 'status': {}}
        self.busy = False
        self.results = queue.Queue()
        self.buttons = []
        self.nav_widgets = {}
        self.profiles = {}
        self.candidates = {}
        self.virtuals = {}
        self.usbs = []
        self.selected_profile_key = None
        self.selected_candidate = None
        self.selected_virtual = None

        # Window setup: font sizes reduced by 2 points across the board
        root.title('PadPilot — 設定總覽' if self.readonly else 'PadPilot — 螢幕與配對管理')
        root.geometry('940x580')
        root.minsize(820, 480)
        root.configure(background=BG)

        # Style setup
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Helvetica Neue', 10), foreground=TEXT_PRIMARY, background=BG)

        # Accent Button (10pt bold)
        style.configure('Accent.TButton', background=BLUE, foreground='#ffffff',
                        borderwidth=0, focuscolor='', padding=(10, 4),
                        font=('Helvetica Neue', 10, 'bold'))
        style.map('Accent.TButton',
                  background=[('pressed', '#004899'), ('active', BLUE_HOVER), ('disabled', '#e5e5ea')],
                  foreground=[('disabled', '#a1a1a6')])

        # Secondary Button (10pt regular)
        style.configure('Secondary.TButton', background='#ffffff', foreground=TEXT_PRIMARY,
                        borderwidth=1, bordercolor='#d1d1d6', lightcolor='#ffffff', darkcolor='#ffffff',
                        focuscolor='', padding=(8, 4), font=('Helvetica Neue', 10))
        style.map('Secondary.TButton',
                  background=[('pressed', '#e5e5ea'), ('active', '#f5f5f7'), ('disabled', '#f2f2f7')],
                  foreground=[('disabled', '#a1a1a6')])

        # Danger Button (10pt bold)
        style.configure('Danger.TButton', background=RED_BG, foreground=RED,
                        borderwidth=1, bordercolor=RED_BORDER, lightcolor=RED_BG, darkcolor=RED_BG,
                        focuscolor='', padding=(8, 4), font=('Helvetica Neue', 10, 'bold'))
        style.map('Danger.TButton',
                  background=[('pressed', '#fbc5c2'), ('active', '#fdd3d0'), ('disabled', '#f5f5f7')],
                  foreground=[('disabled', '#a1a1a6')])

        # Progressbar & Combobox & Checkbutton
        style.configure('TProgressbar', background=BLUE, troughcolor='#e5e5ea', borderwidth=0)
        style.configure('TCombobox', padding=3, background='#ffffff', font=('Helvetica Neue', 10))
        style.configure('TCheckbutton', background=CARD_BG, font=('Helvetica Neue', 10))

        # Main horizontal split: Sidebar (Left) + Content (Right)
        self.main_container = tk.Frame(root, bg=BG)
        self.main_container.pack(fill='both', expand=True)

        self.build_sidebar()
        self.build_main_content()

    def build_sidebar(self):
        self.sidebar = tk.Frame(self.main_container, bg=SIDEBAR_BG, width=190)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)

        # Right divider for sidebar
        tk.Frame(self.main_container, bg=SIDEBAR_BORDER, width=1).pack(side='left', fill='y')

        # App Brand Header (13pt bold)
        header_box = tk.Frame(self.sidebar, bg=SIDEBAR_BG, padx=12, pady=14)
        header_box.pack(fill='x')
        tk.Label(header_box, text='📱 PadPilot', font=('Helvetica Neue', 13, 'bold'),
                 fg=TEXT_PRIMARY, bg=SIDEBAR_BG).pack(anchor='w')
        tk.Label(header_box, text='智慧顯示器管理系統', font=('Helvetica Neue', 9),
                 fg=TEXT_SECONDARY, bg=SIDEBAR_BG).pack(anchor='w', pady=(1, 0))

        # Divider
        tk.Frame(self.sidebar, bg=SIDEBAR_BORDER, height=1).pack(fill='x', padx=10, pady=(0, 6))

        # Navigation menu
        self.nav_box = tk.Frame(self.sidebar, bg=SIDEBAR_BG, padx=6)
        self.nav_box.pack(fill='x')

        self.nav_items = [
            ('paired', '📱', '已配對 iPad'),
            ('search', '🔍', '搜尋新裝置'),
            ('settings', '⚙️', '運作與偏好'),
            ('displays', '🖥️', '連線螢幕狀態'),
            ('virtual', '◻️', '虛擬備援螢幕'),
        ]

        for tab_id, icon, label in self.nav_items:
            item_frame = tk.Frame(self.nav_box, bg=SIDEBAR_BG, cursor='hand2')
            item_frame.pack(fill='x', pady=2)

            lbl = tk.Label(item_frame, text=f" {icon}  {label}", font=('Helvetica Neue', 10),
                           fg=TEXT_PRIMARY, bg=SIDEBAR_BG, anchor='w', padx=8, pady=5)
            lbl.pack(fill='x')

            def make_handler(tid):
                return lambda e: self.select_tab(tid)
            item_frame.bind('<Button-1>', make_handler(tab_id))
            lbl.bind('<Button-1>', make_handler(tab_id))

            def make_hover(frm, l, tid):
                def on_enter(e):
                    if self.current_tab != tid:
                        frm.configure(bg='#e1e1e6')
                        l.configure(bg='#e1e1e6')
                def on_leave(e):
                    if self.current_tab != tid:
                        frm.configure(bg=SIDEBAR_BG)
                        l.configure(bg=SIDEBAR_BG)
                return on_enter, on_leave

            ent, lev = make_hover(item_frame, lbl, tab_id)
            item_frame.bind('<Enter>', ent)
            item_frame.bind('<Leave>', lev)
            lbl.bind('<Enter>', ent)
            lbl.bind('<Leave>', lev)

            self.nav_widgets[tab_id] = (item_frame, lbl)

        # Bottom status in sidebar
        bottom_box = tk.Frame(self.sidebar, bg=SIDEBAR_BG, padx=10, pady=10)
        bottom_box.pack(side='bottom', fill='x')

        # Status mini card
        self.sidebar_status_card = Card(bottom_box, bg='#ffffff', border=CARD_BORDER, padx=8, pady=6)
        self.sidebar_status_card.pack(fill='x', pady=(0, 6))
        self.side_mode_label = tk.Label(self.sidebar_status_card.body, text='模式：讀取中…',
                                        font=('Helvetica Neue', 9), fg=TEXT_SECONDARY, bg='#ffffff', anchor='w')
        self.side_mode_label.pack(fill='x')
        self.side_target_label = tk.Label(self.sidebar_status_card.body, text='主力：讀取中…',
                                          font=('Helvetica Neue', 9), fg=TEXT_SECONDARY, bg='#ffffff', anchor='w')
        self.side_target_label.pack(fill='x', pady=(1, 0))

        # Quick refresh button
        self.refresh_btn = ttk.Button(bottom_box, text='🔄 重新整理狀態', command=self.search,
                                      style='Secondary.TButton')
        self.refresh_btn.pack(fill='x')
        self.buttons.append(self.refresh_btn)

    def build_main_content(self):
        self.content_area = tk.Frame(self.main_container, bg=BG)
        self.content_area.pack(side='right', fill='both', expand=True)

        # Header area
        self.header_frame = tk.Frame(self.content_area, bg=BG, padx=18, pady=10)
        self.header_frame.pack(fill='x')

        self.title_label = tk.Label(self.header_frame, text='已配對 iPad',
                                    font=('Helvetica Neue', 14, 'bold'), fg=TEXT_PRIMARY, bg=BG)
        self.title_label.pack(anchor='w')

        self.subtitle_label = tk.Label(self.header_frame, text='管理已配對至 PadPilot 的 iPad 設備清單',
                                       font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=BG)
        self.subtitle_label.pack(anchor='w', pady=(1, 0))

        # Canvas without visible scrollbar, gentle 15px step increment
        self.canvas = tk.Canvas(self.content_area, bg=BG, highlightthickness=0, bd=0, yscrollincrement=15)
        self.scroll_frame = tk.Frame(self.canvas, bg=BG)

        def _update_scrollregion():
            if not self.canvas.winfo_exists():
                return
            bbox = self.canvas.bbox('all')
            if not bbox:
                return
            content_height = bbox[3] - bbox[1]
            canvas_height = self.canvas.winfo_height()
            if content_height <= canvas_height + 5:
                self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), max(canvas_height, 1)))
                self.canvas.yview_moveto(0.0)
            else:
                self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), bbox[3]))

        self.scroll_frame.bind('<Configure>', lambda e: _update_scrollregion())
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor='nw')

        def _on_canvas_resize(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)
            _update_scrollregion()

        self.canvas.bind('<Configure>', _on_canvas_resize)
        self.canvas.pack(fill='both', expand=True)

        # Gentle Mousewheel binding: only scrolls when content actually exceeds canvas height
        def _on_mousewheel(event):
            if not self.canvas.winfo_exists():
                return
            try:
                x, y = self.root.winfo_pointerxy()
                cx = self.content_area.winfo_rootx()
                cy = self.content_area.winfo_rooty()
                cw = self.content_area.winfo_width()
                ch = self.content_area.winfo_height()
                if not (cx <= x <= cx + cw and cy <= y <= cy + ch):
                    return

                bbox = self.canvas.bbox('all')
                if not bbox:
                    return
                content_height = bbox[3] - bbox[1]
                canvas_height = self.canvas.winfo_height()

                # If content fits completely inside the window, NEVER scroll!
                if content_height <= canvas_height + 5:
                    self.canvas.yview_moveto(0.0)
                    return

                delta = event.delta
                if not delta:
                    return

                # Normalise to a gentle 1-step (15px) or 2-step (30px) movement
                step = -2 if delta > 0 else 2 if abs(delta) >= 120 else (-1 if delta > 0 else 1)

                # Boundary protection
                y_range = self.canvas.yview()
                if step < 0 and y_range[0] <= 0.001:
                    self.canvas.yview_moveto(0.0)
                    return
                if step > 0 and y_range[1] >= 0.999:
                    return

                self.canvas.yview_scroll(step, 'units')
            except Exception:
                pass

        self.root.bind_all('<MouseWheel>', _on_mousewheel)

        # Bottom footer bar
        self.footer = tk.Frame(self.content_area, bg=BG, padx=18, pady=6)
        self.footer.pack(side='bottom', fill='x')

        self.notice = tk.Label(self.footer, text='正在讀取…', font=('Helvetica Neue', 10),
                               fg=TEXT_SECONDARY, bg=BG)
        self.notice.pack(side='left')

        # Progressbar: Hidden when idle, only packed during task()
        self.progress = ttk.Progressbar(self.footer, length=90, mode='indeterminate', style='TProgressbar')

        self.select_tab(self.current_tab)

    def select_tab(self, tab_id: str):
        self.current_tab = tab_id
        for tid, (frm, lbl) in self.nav_widgets.items():
            if tid == tab_id:
                frm.configure(bg=BLUE)
                lbl.configure(bg=BLUE, fg='#ffffff', font=('Helvetica Neue', 10, 'bold'))
            else:
                frm.configure(bg=SIDEBAR_BG)
                lbl.configure(bg=SIDEBAR_BG, fg=TEXT_PRIMARY, font=('Helvetica Neue', 10))

        titles = {
            'paired': ('已配對 iPad', '管理已記錄的 iPad 裝置，指定無螢幕時的自動接管主力'),
            'search': ('搜尋與配對', '自動探測附近的 Sidecar 設備與 USB 連線進行配對'),
            'settings': ('運作與偏好設定', '檢視與即時切換運作模式、登入啟動狀態與防護參數'),
            'displays': ('目前連線螢幕', '檢視當前上線的實體螢幕、Sidecar 與虛擬備援螢幕'),
            'virtual': ('虛擬備援螢幕', '選擇並指定 BetterDisplay 虛擬螢幕作為無頭備援'),
        }
        t, st = titles.get(tab_id, ('PadPilot', ''))
        if self.readonly:
            st += '（唯讀模式）'
        self.title_label.configure(text=t)
        self.subtitle_label.configure(text=st)

        self.render_current_tab()

    def make_badge(self, parent, text: str, bg: str, fg: str) -> tk.Label:
        return tk.Label(parent, text=f" {text} ", font=('Helvetica Neue', 9, 'bold'),
                        bg=bg, fg=fg, padx=4, pady=1)

    def render_current_tab(self):
        # Reset dynamic buttons while preserving persistent ones
        self.buttons = [self.refresh_btn]

        # Clear scroll_frame
        for widget in self.scroll_frame.winfo_children():
            widget.destroy()

        if self.current_tab == 'paired':
            self.render_paired_tab()
        elif self.current_tab == 'search':
            self.render_search_tab()
        elif self.current_tab == 'settings':
            self.render_settings_tab()
        elif self.current_tab == 'displays':
            self.render_displays_tab()
        elif self.current_tab == 'virtual':
            self.render_virtual_tab()

        self.canvas.yview_moveto(0)

    def render_paired_tab(self):
        cfg = self.view['config']

        if not self.profiles:
            card = Card(self.scroll_frame, padx=16, pady=14)
            card.pack(fill='x', padx=18, pady=8)
            tk.Label(card.body, text='📱', font=('Helvetica Neue', 24), bg=CARD_BG).pack(pady=(2, 2))
            tk.Label(card.body, text='尚未配對任何 iPad', font=('Helvetica Neue', 12, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack()
            tk.Label(card.body, text='請前往「搜尋新裝置」尋找身旁的 iPad 並完成配對設定。',
                     font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=CARD_BG).pack(pady=(2, 10))
            if not self.readonly:
                go_btn = ttk.Button(card.body, text='前往搜尋新裝置',
                                    command=lambda: self.select_tab('search'),
                                    style='Accent.TButton')
                go_btn.pack(pady=(0, 2))
                self.buttons.append(go_btn)
            return

        for key, p in self.profiles.items():
            is_target = (p == cfg.ipad.to_dict())
            status = device_status(p, self.view)

            # Compact card
            card = Card(self.scroll_frame, padx=14, pady=8)
            card.pack(fill='x', padx=18, pady=4)

            # Line 1: Name & Badges on Left, Action Buttons on Right
            top_row = tk.Frame(card.body, bg=CARD_BG)
            top_row.pack(fill='x')

            left_top = tk.Frame(top_row, bg=CARD_BG)
            left_top.pack(side='left', fill='x', expand=True)

            tk.Label(left_top, text='📱', font=('Helvetica Neue', 13), bg=CARD_BG).pack(side='left', padx=(0, 4))
            tk.Label(left_top, text=p.get('name', '未命名 iPad'), font=('Helvetica Neue', 11, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

            if is_target:
                self.make_badge(left_top, '★ 主力 iPad (自動接管)', BLUE, '#ffffff').pack(side='left', padx=(6, 2))

            if status == '已連線':
                self.make_badge(left_top, '● 已連線', GREEN_BG, GREEN_FG).pack(side='left', padx=2)
            elif status == '僅 USB 已接上':
                self.make_badge(left_top, '⚡ 僅 USB 接上', ORANGE_BG, ORANGE_FG).pack(side='left', padx=2)
            elif status == '已偵測到 Sidecar':
                self.make_badge(left_top, '📡 偵測到 Sidecar', BLUE_TINT, BLUE).pack(side='left', padx=2)
            else:
                self.make_badge(left_top, '○ 離線未連線', '#f2f2f7', TEXT_TERTIARY).pack(side='left', padx=2)

            # Line 1 Right: Action buttons
            if not self.readonly:
                act_box = tk.Frame(top_row, bg=CARD_BG)
                act_box.pack(side='right')

                if not is_target:
                    tgt_btn = ttk.Button(
                        act_box, text='設為主力 iPad',
                        command=lambda k=key: self.select_target(k),
                        style='Accent.TButton'
                    )
                    tgt_btn.pack(side='left', padx=(0, 4))
                    self.buttons.append(tgt_btn)
                else:
                    ready_lbl = tk.Label(act_box, text='✓ 目前主力接管中', font=('Helvetica Neue', 10),
                                         fg=BLUE, bg=CARD_BG)
                    ready_lbl.pack(side='left', padx=(0, 4))

                del_btn = ttk.Button(
                    act_box, text='刪除配對',
                    command=lambda k=key: self.delete_selected(k),
                    style='Danger.TButton'
                )
                del_btn.pack(side='left')
                self.buttons.append(del_btn)

            # Line 2: Sidecar UUID on its own separate line (never truncated!)
            uuid_str = p.get('sidecar_uuid') or '未設定'
            tk.Label(card.body, text=f"Sidecar UUID: {uuid_str}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG, anchor='w').pack(fill='x', pady=(4, 0))

            # Line 3: USB 序號 on its own separate line (never truncated!)
            usb_str = p.get('usb_serial') or '未設定'
            usb_suffix = ' (目前已接上 USB)' if any(u.get('serial') == p.get('usb_serial') for u in self.view['actual'].get('usb_devices', [])) else ''
            tk.Label(card.body, text=f"USB 序號:      {usb_str}{usb_suffix}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG, anchor='w').pack(fill='x', pady=(1, 0))

    def render_search_tab(self):
        # Instruction Card
        info_card = Card(self.scroll_frame, padx=12, pady=8)
        info_card.pack(fill='x', padx=18, pady=(0, 6))

        top_r = tk.Frame(info_card.body, bg=CARD_BG)
        top_r.pack(fill='x')
        tk.Label(top_r, text='💡 搜尋與配對須知', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        search_btn = ttk.Button(top_r, text='🔍 搜尋可配對裝置', command=self.search, style='Accent.TButton')
        search_btn.pack(side='right')
        self.buttons.append(search_btn)

        guidance = (
            '請確認 Mac 與 iPad 登入相同 Apple Account，且藍牙與 Wi-Fi 已開啟；'
            '建議以 USB-C 直連確保無頭開機時自動接管。'
        )
        tk.Label(info_card.body, text=guidance, font=('Helvetica Neue', 10),
                 fg=TEXT_SECONDARY, bg=CARD_BG, justify='left').pack(anchor='w', pady=(4, 0))

        # Discovered candidates header
        tk.Label(self.scroll_frame, text=f"可配對裝置 ({len(self.candidates)} 台)",
                 font=('Helvetica Neue', 11, 'bold'), fg=TEXT_PRIMARY, bg=BG).pack(anchor='w', padx=18, pady=(4, 2))

        if not self.candidates:
            empty_card = Card(self.scroll_frame, padx=12, pady=8)
            empty_card.pack(fill='x', padx=18, pady=3)
            tk.Label(empty_card.body, text='目前未偵測到 Sidecar 候選設備',
                     font=('Helvetica Neue', 11, 'bold'), fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w')
            tk.Label(empty_card.body,
                     text='若 iPad 已在身旁，請解鎖螢幕或在 macOS「控制中心 > 螢幕鏡像輸出」中確認是否能看到該 iPad。',
                     font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(2, 0))
            return

        for uuid, cand in self.candidates.items():
            card = Card(self.scroll_frame, padx=12, pady=8)
            card.pack(fill='x', padx=18, pady=4)

            # Line 1: Header + Badges
            c_top = tk.Frame(card.body, bg=CARD_BG)
            c_top.pack(fill='x')
            tk.Label(c_top, text='📱', font=('Helvetica Neue', 12), bg=CARD_BG).pack(side='left', padx=(0, 4))
            tk.Label(c_top, text=cand.get('name', '未命名裝置'), font=('Helvetica Neue', 11, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

            prev = next((p for p in self.profiles.values() if p.get('sidecar_uuid', '').upper() == uuid.upper()), {})
            if prev:
                self.make_badge(c_top, '已在此 Mac 配對', GREEN_BG, GREEN_FG).pack(side='right')
            else:
                self.make_badge(c_top, '新發現裝置', BLUE_TINT, BLUE).pack(side='right')

            # Line 2: Sidecar UUID
            tk.Label(card.body, text=f"Sidecar UUID: {uuid}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(3, 0))

            # Line 3: Currently linked USB serial
            cur_usb = prev.get('usb_serial') or '未綁定'
            tk.Label(card.body, text=f"目前關聯 USB:  {cur_usb}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(1, 4))

            tk.Frame(card.body, bg='#f2f2f7', height=1).pack(fill='x', pady=(4, 6))

            # Row 1: 自訂名稱 + [ 更新名稱 ] 按鈕
            f_row1 = tk.Frame(card.body, bg=CARD_BG)
            f_row1.pack(fill='x', pady=2)
            tk.Label(f_row1, text='自訂名稱：', font=('Helvetica Neue', 10),
                     fg=TEXT_SECONDARY, bg=CARD_BG, width=10, anchor='w').pack(side='left')
            name_var = tk.StringVar(value=cand.get('name', ''))
            name_entry = tk.Entry(
                f_row1,
                textvariable=name_var,
                font=('Helvetica Neue', 10),
                bg='#ffffff',
                fg=TEXT_PRIMARY,               # High contrast dark text!
                insertbackground=TEXT_PRIMARY, # Visible cursor!
                selectbackground=BLUE,
                selectforeground='#ffffff',
                highlightbackground='#d1d1d6',
                highlightthickness=1,
                relief='flat'
            )
            name_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))

            if not self.readonly:
                up_name_btn = ttk.Button(
                    f_row1, text='更新名稱',
                    command=lambda c=cand, nv=name_var: self.update_candidate_name(c, nv.get()),
                    style='Secondary.TButton'
                )
                up_name_btn.pack(side='right')
                self.buttons.append(up_name_btn)

            # Row 2: 對應 USB + [ 更新 USB 設定 ] 按鈕
            f_row2 = tk.Frame(card.body, bg=CARD_BG)
            f_row2.pack(fill='x', pady=2)
            tk.Label(f_row2, text='對應 USB：', font=('Helvetica Neue', 10),
                     fg=TEXT_SECONDARY, bg=CARD_BG, width=10, anchor='w').pack(side='left')
            usb_options = ['略過 / 保留原 USB 設定'] + [
                f"{u.get('product_name') or u.get('name')} · {u['serial']}" for u in self.usbs
            ]
            usb_cb = ttk.Combobox(f_row2, state='readonly', values=usb_options, style='TCombobox')
            # Pre-select matching USB if already paired
            pre_idx = 0
            if prev.get('usb_serial'):
                for i, u in enumerate(self.usbs):
                    if u.get('serial') == prev.get('usb_serial'):
                        pre_idx = i + 1
                        break
            usb_cb.current(pre_idx)
            usb_cb.pack(side='left', fill='x', expand=True, padx=(0, 6))

            if not self.readonly:
                up_usb_btn = ttk.Button(
                    f_row2, text='更新 USB 設定',
                    command=lambda c=cand, nv=name_var, ucb=usb_cb: self.update_candidate_usb(c, nv.get(), ucb.current()),
                    style='Secondary.TButton'
                )
                up_usb_btn.pack(side='right')
                self.buttons.append(up_usb_btn)

            # Bottom action row
            act_row = tk.Frame(card.body, bg=CARD_BG)
            act_row.pack(fill='x', pady=(6, 0))

            act_var = tk.BooleanVar(value=False)
            chk = ttk.Checkbutton(act_row, text='設為主要管理 iPad（無螢幕時自動接管）',
                                  variable=act_var, style='TCheckbutton')
            chk.pack(side='left')

            if not self.readonly:
                save_btn = ttk.Button(
                    act_row, text='完成配對並儲存全部',
                    command=lambda c=cand, n=name_var, u=usb_cb, a=act_var: self.save_candidate_card(
                        c, n.get(), u.current(), a.get()
                    ),
                    style='Accent.TButton'
                )
                save_btn.pack(side='right')
                self.buttons.append(save_btn)

    def render_settings_tab(self):
        cfg = self.view['config']

        # Group 1: 運作模式 (可互動切換)
        g1 = Card(self.scroll_frame, padx=12, pady=8)
        g1.pack(fill='x', padx=18, pady=(0, 6))

        g1_top = tk.Frame(g1.body, bg=CARD_BG)
        g1_top.pack(fill='x', pady=(0, 4))
        tk.Label(g1_top, text='⚙️ 運作模式 (Operation Mode)', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        if not self.readonly:
            tk.Label(g1_top, text='（點選卡片或按鈕即可即時切換）', font=('Helvetica Neue', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=4)

        for mode_key, title in MODES.items():
            is_active = (cfg.mode.value == mode_key)
            m_frame = tk.Frame(
                g1.body,
                bg='#f9fafc' if is_active else CARD_BG,
                highlightbackground=BLUE if is_active else '#e5e5ea',
                highlightthickness=1,
                padx=10, pady=6,
                cursor='hand2' if not self.readonly and not is_active else ''
            )
            m_frame.pack(fill='x', pady=2)

            row = tk.Frame(m_frame, bg='#f9fafc' if is_active else CARD_BG)
            row.pack(fill='x')

            tk.Label(row, text=title, font=('Helvetica Neue', 11, 'bold'),
                     fg=BLUE if is_active else TEXT_PRIMARY,
                     bg='#f9fafc' if is_active else CARD_BG).pack(side='left')

            if is_active:
                self.make_badge(row, '✓ 目前生效中', BLUE, '#ffffff').pack(side='right')
            elif not self.readonly:
                btn = ttk.Button(
                    row, text='切換為此模式',
                    command=lambda k=mode_key: self.set_mode(k),
                    style='Secondary.TButton'
                )
                btn.pack(side='right')
                self.buttons.append(btn)

            tk.Label(
                m_frame, text=MODE_DESCS.get(mode_key, ''), font=('Helvetica Neue', 10),
                fg=TEXT_SECONDARY, bg='#f9fafc' if is_active else CARD_BG, justify='left'
            ).pack(anchor='w', pady=(2, 0))

            if not self.readonly and not is_active:
                m_frame.bind('<Button-1>', lambda e, k=mode_key: self.set_mode(k))

        # Group 2: 開機與背景服務 (帶有互動 Toggle)
        g2 = Card(self.scroll_frame, padx=12, pady=8)
        g2.pack(fill='x', padx=18, pady=(0, 6))

        s_row = tk.Frame(g2.body, bg=CARD_BG)
        s_row.pack(fill='x')
        tk.Label(s_row, text='🚀 登入時自動啟動 PadPilot：', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        self.make_badge(s_row, '已啟用' if cfg.autostart_on_login else '已停用',
                        GREEN_BG if cfg.autostart_on_login else '#f2f2f7',
                        GREEN_FG if cfg.autostart_on_login else TEXT_SECONDARY).pack(side='left', padx=4)

        if not self.readonly:
            toggle_btn = ttk.Button(
                s_row,
                text='切換為停用' if cfg.autostart_on_login else '切換為啟用',
                command=self.toggle_autostart_action,
                style='Secondary.TButton' if cfg.autostart_on_login else 'Accent.TButton'
            )
            toggle_btn.pack(side='left', padx=6)
            self.buttons.append(toggle_btn)

        tk.Label(s_row, text='（隨 macOS 登入背景自動執行）', font=('Helvetica Neue', 9),
                 fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=2)

        # Group 3: 防護機制與保護參數
        g3 = Card(self.scroll_frame, padx=12, pady=8)
        g3.pack(fill='x', padx=18, pady=(0, 6))
        tk.Label(g3.body, text='🛡️ 防護機制與保護參數', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w', pady=(0, 4))

        params = [
            ('瞬斷防抖等待 (Debounce)', f"{cfg.debounce_seconds:.1f} 秒", '實體螢幕拔插瞬斷時的緩衝計時，未滿前不觸發切換'),
            ('最大重試次數 (Max Retries)', f"{cfg.max_retries} 次", 'Sidecar 連線異常時的自動重試上限'),
            ('重試間隔 (Retry Interval)', f"{cfg.retry_interval:.1f} 秒", '每次重試之間的等待秒數'),
            ('冷卻保護時間 (Cooldown)', f"{cfg.cooldown_seconds:.1f} 秒", '重試全數失敗後進入冷卻，防止連線風暴'),
            ('排除佔位名稱 (Ignore List)', '、'.join(cfg.ignore_list) or '無', '忽略特定佔位螢幕名稱（如 Generic Display）')
        ]
        for name, val, desc in params:
            p_row = tk.Frame(g3.body, bg=CARD_BG)
            p_row.pack(fill='x', pady=2)

            p_left = tk.Frame(p_row, bg=CARD_BG)
            p_left.pack(side='left', fill='x', expand=True)

            tk.Label(p_left, text=name, font=('Helvetica Neue', 10, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
            tk.Label(p_left, text=f" — {desc}", font=('Helvetica Neue', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=4)

            self.make_badge(p_row, val, BLUE_TINT, BLUE).pack(side='right')

        # Group 4: 系統路徑與整合
        g4 = Card(self.scroll_frame, padx=12, pady=8)
        g4.pack(fill='x', padx=18, pady=(0, 6))
        tk.Label(g4.body, text='📁 系統路徑與整合', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w', pady=(0, 2))
        tk.Label(g4.body, text=f"BetterDisplay CLI: {cfg.betterdisplaycli_path}",
                 font=('Menlo', 9), fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w')
        tk.Label(g4.body, text=f"設定檔位置: {get_config_file_path()}",
                 font=('Menlo', 9), fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(1, 0))

    def render_displays_tab(self):
        actual = self.view['actual']
        displays = actual.get('online_displays', [])

        if not self.view['fresh']:
            warn_card = Card(self.scroll_frame, padx=12, pady=8)
            warn_card.pack(fill='x', padx=18, pady=4)
            tk.Label(warn_card.body, text='⚠️ 螢幕資料待更新', font=('Helvetica Neue', 11, 'bold'),
                     fg=ORANGE_FG, bg=CARD_BG).pack(anchor='w')
            tk.Label(warn_card.body, text='上次偵測資料已超過 120 秒或尚未取得，請點擊左側「重新整理狀態」。',
                     font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(2, 0))
            return

        if not displays:
            empty_card = Card(self.scroll_frame, padx=12, pady=8)
            empty_card.pack(fill='x', padx=18, pady=4)
            tk.Label(empty_card.body, text='目前無任何上線顯示器',
                     font=('Helvetica Neue', 11, 'bold'), fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w')
            return

        for d in displays:
            card = Card(self.scroll_frame, padx=12, pady=6)
            card.pack(fill='x', padx=18, pady=3)

            top = tk.Frame(card.body, bg=CARD_BG)
            top.pack(fill='x')

            icon = '◻️' if d.get('is_virtual') else ('📱' if d.get('is_sidecar') else '🖥️')
            tk.Label(top, text=icon, font=('Helvetica Neue', 13), bg=CARD_BG).pack(side='left', padx=(0, 4))
            tk.Label(top, text=d.get('name', '未命名螢幕'), font=('Helvetica Neue', 11, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

            w, h = d.get('width', 0), d.get('height', 0)
            tk.Label(top, text=f"({w} × {h})", font=('Menlo', 10),
                     fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=6)

            b_box = tk.Frame(top, bg=CARD_BG)
            b_box.pack(side='right')

            if d.get('is_main'):
                self.make_badge(b_box, '主顯示器', BLUE, '#ffffff').pack(side='left', padx=2)
            else:
                self.make_badge(b_box, '延伸顯示器', '#f2f2f7', TEXT_SECONDARY).pack(side='left', padx=2)

            type_label = '虛擬螢幕' if d.get('is_virtual') else ('Sidecar' if d.get('is_sidecar') else '實體螢幕')
            self.make_badge(b_box, type_label, BLUE_TINT, BLUE).pack(side='left', padx=2)

    def render_virtual_tab(self):
        cfg = self.view['config']

        # Top Card: Explanation & Selection Dropdown
        info_card = Card(self.scroll_frame, padx=12, pady=8)
        info_card.pack(fill='x', padx=18, pady=(0, 6))

        top_r = tk.Frame(info_card.body, bg=CARD_BG)
        top_r.pack(fill='x')
        tk.Label(top_r, text='◻️ BetterDisplay 虛擬備援螢幕設定',
                 font=('Helvetica Neue', 11, 'bold'), fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        rescan_btn = ttk.Button(top_r, text='🔄 重新探測', command=self.search,
                                style='Secondary.TButton')
        rescan_btn.pack(side='right')
        self.buttons.append(rescan_btn)

        guidance = (
            '當未接外接螢幕且 Sidecar 連線斷線時，虛擬螢幕將作為無頭備援 Framebuffer，供遠端救援存取。'
        )
        tk.Label(info_card.body, text=guidance, font=('Helvetica Neue', 10),
                 fg=TEXT_SECONDARY, bg=CARD_BG, justify='left').pack(anchor='w', pady=(3, 6))

        # Explicit selection row (Dropdown to pick which screen is the virtual fallback!)
        v_names = [d.get('name') for d in self.virtuals.values() if d.get('name')]
        sel_row = tk.Frame(info_card.body, bg=CARD_BG)
        sel_row.pack(fill='x', pady=(4, 2))

        tk.Label(sel_row, text='選擇指定備援螢幕：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        cur_vname = cfg.virtual_display_name or (v_names[0] if v_names else '尚未指定')
        v_cb = ttk.Combobox(sel_row, state='readonly', values=v_names or ['未探測到虛擬螢幕'], style='TCombobox')
        if v_names:
            v_idx = v_names.index(cur_vname) if cur_vname in v_names else 0
            v_cb.current(v_idx)
        else:
            v_cb.current(0)
        v_cb.pack(side='left', fill='x', expand=True, padx=(4, 6))

        if not self.readonly and v_names:
            apply_v_btn = ttk.Button(
                sel_row, text='指定為備援螢幕',
                command=lambda cb=v_cb: self.set_virtual(cb.get()),
                style='Accent.TButton'
            )
            apply_v_btn.pack(side='right')
            self.buttons.append(apply_v_btn)

        # Virtual displays list
        if not self.virtuals:
            empty_card = Card(self.scroll_frame, padx=12, pady=8)
            empty_card.pack(fill='x', padx=18, pady=3)
            tk.Label(empty_card.body, text='未探測到任何 BetterDisplay 虛擬螢幕',
                     font=('Helvetica Neue', 11, 'bold'), fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w')
            tk.Label(empty_card.body,
                     text='請先在 BetterDisplay App 中建立至少一個虛擬顯示器（建議命名為 PadPilotVirtual）。',
                     font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=CARD_BG).pack(anchor='w', pady=(2, 0))
            return

        for key, d in self.virtuals.items():
            name = d.get('name')
            is_chosen = (name == cfg.virtual_display_name)
            is_connected = str(d.get('displayID', '0')).isdecimal() and int(d['displayID']) > 0

            card = Card(self.scroll_frame, padx=12, pady=6)
            card.pack(fill='x', padx=18, pady=3)

            top = tk.Frame(card.body, bg=CARD_BG)
            top.pack(fill='x')
            tk.Label(top, text='◻️', font=('Helvetica Neue', 12), bg=CARD_BG).pack(side='left', padx=(0, 4))
            tk.Label(top, text=name, font=('Helvetica Neue', 11, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

            b_box = tk.Frame(top, bg=CARD_BG)
            b_box.pack(side='right')
            if is_chosen:
                self.make_badge(b_box, '✓ 目前指定備援', BLUE, '#ffffff').pack(side='left', padx=2)
            if is_connected:
                self.make_badge(b_box, '已連接', GREEN_BG, GREEN_FG).pack(side='left', padx=2)
            else:
                self.make_badge(b_box, '未連接', '#f2f2f7', TEXT_TERTIARY).pack(side='left', padx=2)

            if not self.readonly and not is_chosen:
                set_btn = ttk.Button(
                    b_box, text='設為此備援',
                    command=lambda n=name: self.set_virtual(n),
                    style='Secondary.TButton'
                )
                set_btn.pack(side='left', padx=(6, 0))
                self.buttons.append(set_btn)

    def display(self, view: dict):
        self.view = view
        cfg, actual = view['config'], view['actual']

        # Update sidebar summary labels
        mode_text = MODES.get(cfg.mode.value, cfg.mode.value)
        self.side_mode_label.configure(text=f"模式：{mode_text}")
        target_name = cfg.ipad.name or '尚未指定'
        self.side_target_label.configure(text=f"主力：{target_name}")

        self.profiles = {pairing_key(p.to_dict()): p.to_dict() for p in cfg.paired_ipads}
        self.candidates = {d['uuid']: d for d in actual.get('sidecar_devices', []) if d.get('uuid')}
        self.virtuals = {str(i): d for i, d in enumerate(view.get('identifiers', [])) if is_virtual_device(d)}
        self.usbs = [u for u in actual.get('usb_devices', []) if u.get('serial')]

        errors = actual.get('discovery_errors', {})
        if errors:
            self.notice.configure(text='部分狀態未知：' + '；'.join(errors.values()))
        else:
            ts = time.strftime('%H:%M:%S')
            count = len(self.profiles)
            extra = ' · 本頁不提供變更操作' if self.readonly else ''
            self.notice.configure(text=f"更新於 {ts} · {count} 台已配對{extra}")

        self.render_current_tab()

    def task(self, work, complete):
        if self.busy:
            return
        self.busy = True
        for button in list(self.buttons):
            try:
                button.state(['disabled'])
            except Exception:
                pass
        self.progress.pack(side='right', padx=(10, 0))
        self.progress.start(10)
        self.notice.configure(text='處理中，請稍候…')

        def worker():
            try:
                self.results.put((True, work()))
            except Exception as error:
                self.results.put((False, str(error)))

        def poll():
            try:
                ok, value = self.results.get_nowait()
            except queue.Empty:
                self.root.after(100, poll)
                return
            self.busy = False
            self.progress.stop()
            self.progress.pack_forget()
            for button in list(self.buttons):
                try:
                    button.state(['!disabled'])
                except Exception:
                    pass
            if ok:
                complete(value)
            else:
                self.notice.configure(text='操作未完成；請檢查錯誤後重試。')
                messagebox.showerror('PadPilot', value, parent=self.root)
                if getattr(self, 'one_shot', False):
                    self.root.destroy()

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, poll)

    def search(self):
        self.task(lambda: read_view(scan=True), self.display)

    def change(self, action: str, payload: dict):
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

    def set_mode(self, mode_key: str):
        if self.readonly or self.busy:
            return
        cfg = self.view['config']
        if cfg.mode.value == mode_key:
            return
        target_name = MODES.get(mode_key, mode_key)
        desc = MODE_DESCS.get(mode_key, '')
        if not confirm(self.root, f'切換至{target_name}?', desc):
            return

        def work():
            res = subprocess.run(
                [sys.executable, str(ROOT / 'bin/padpilot-cli'), 'set-mode', mode_key],
                capture_output=True, text=True, timeout=20
            )
            if res.returncode != 0:
                raise RuntimeError(res.stderr.strip() or res.stdout.strip() or '切換模式失敗')
            return f"已成功切換為 {target_name}", read_view(scan=False)

        def complete(result):
            msg, view = result
            self.display(view)
            self.notice.configure(text=msg)

        self.task(work, complete)

    def toggle_autostart_action(self):
        if self.readonly or self.busy:
            return
        cfg = self.view['config']
        new_state = not cfg.autostart_on_login
        action_str = '啟用' if new_state else '停用'
        detail = f'設定為{action_str}後，每次開機登入 macOS 時將{"自動" if new_state else "不"}於背景執行 PadPilot 守護程序。'
        if not confirm(self.root, f'確定{action_str}登入時自動啟動?', detail):
            return

        def work():
            from core.autostart import toggle_autostart
            ok, msg = toggle_autostart()
            return msg, read_view(scan=False)

        def complete(result):
            msg, view = result
            self.display(view)
            self.notice.configure(text=msg)

        self.task(work, complete)

    def update_candidate_name(self, candidate, new_name):
        if self.readonly or self.busy or not candidate:
            return
        new_name = new_name.strip()
        old_name = candidate.get('name', '')
        if not new_name:
            messagebox.showerror('名稱不可為空', '請輸入有效的裝置名稱。', parent=self.root)
            return
        if new_name == old_name:
            messagebox.showinfo('名稱未變更', f'裝置名稱已經是「{new_name}」，未作任何變更。', parent=self.root)
            return
        detail = f"是否將名稱由：\n{old_name}\n\n更改成：\n{new_name}"
        if not confirm(self.root, '確定更新裝置名稱?', detail):
            return
        prev = next((p for p in self.profiles.values() if p.get('sidecar_uuid', '').upper() == candidate['uuid'].upper()), {})
        serial = prev.get('usb_serial', '')
        is_target = (prev == self.view['config'].ipad.to_dict())
        payload = {
            'ipad': {
                'name': new_name,
                'sidecar_uuid': candidate['uuid'],
                'usb_serial': serial
            },
            'activate': is_target
        }
        self.change('save_pairing', payload)

    def update_candidate_usb(self, candidate, name, usb_index):
        if self.readonly or self.busy or not candidate:
            return
        prev = next((p for p in self.profiles.values() if p.get('sidecar_uuid', '').upper() == candidate['uuid'].upper()), {})
        old_serial = prev.get('usb_serial', '') or '未設定'
        new_serial = self.usbs[usb_index - 1]['serial'] if (0 < usb_index <= len(self.usbs)) else ''
        new_display = new_serial or '略過 / 未綁定'
        if new_serial == prev.get('usb_serial', ''):
            messagebox.showinfo('USB 設定未變更', f'USB 序號已是「{old_serial}」，未作任何變更。', parent=self.root)
            return
        detail = f"裝置：{candidate.get('name', '')}\n\n是否將 USB 序號由：\n原設定：{old_serial}\n變更為：{new_display}"
        if not confirm(self.root, '確定更新 USB 設定?', detail):
            return
        is_target = (prev == self.view['config'].ipad.to_dict())
        payload = {
            'ipad': {
                'name': (name or candidate.get('name', '')).strip(),
                'sidecar_uuid': candidate['uuid'],
                'usb_serial': new_serial
            },
            'activate': is_target
        }
        self.change('save_pairing', payload)

    def delete_selected(self, key=None):
        if self.readonly or self.busy:
            return
        p = self.profiles.get(key) if key else (
            self.profiles.get(getattr(self, 'selected_profile_key', None))
            or (next(iter(self.profiles.values())) if self.profiles else None)
        )
        if not p:
            messagebox.showerror('PadPilot', '配對紀錄已變更或不存在，請重新開啟清單。', parent=self.root)
            if getattr(self, 'one_shot', False):
                self.root.destroy()
            return
        detail = f"裝置：{p['name']}\n僅刪除 PadPilot 的配對紀錄，不解除 Apple 系統配對。"
        if p == self.view['config'].ipad.to_dict():
            detail += '\n這是目前主力 iPad；刪除後改為僅手動模式，保留目前螢幕連線。'
        if confirm(self.root, '確定刪除配對?', detail):
            self.change('delete_pairing', {'key': pairing_key(p)})
        elif getattr(self, 'one_shot', False):
            self.root.destroy()

    def select_target(self, key=None):
        if self.readonly or self.busy:
            return
        p = self.profiles.get(key) if key else (
            self.profiles.get(getattr(self, 'selected_profile_key', None))
            or (next(iter(self.profiles.values())) if self.profiles else None)
        )
        if not p:
            messagebox.showerror('PadPilot', '找不到配對紀錄。', parent=self.root)
            if getattr(self, 'one_shot', False):
                self.root.destroy()
            return
        detail = f"裝置：{p['name']}\n當未接外接螢幕時，系統將自動連線此 iPad 並將其切換為主顯示器。\n（將清除原主力 iPad 的暫時覆寫）"
        if confirm(self.root, '指定為主要管理 iPad?', detail):
            self.change('save_pairing', {'ipad': p, 'activate': True})
        elif getattr(self, 'one_shot', False):
            self.root.destroy()

    def save_candidate_card(self, candidate, name, usb_index, activate):
        if self.readonly or self.busy:
            return
        if not candidate:
            return
        serial = self.usbs[usb_index - 1]['serial'] if (0 < usb_index <= len(self.usbs)) else ''
        payload = {
            'ipad': {
                'name': (name or candidate.get('name', '')).strip(),
                'sidecar_uuid': candidate['uuid'],
                'usb_serial': serial
            },
            'activate': bool(activate)
        }
        try:
            Config.from_dict(self.view['config'].to_dict()).remember_ipad(payload['ipad'], payload['activate'])
        except ValueError as error:
            messagebox.showerror('配對資料不完整', str(error), parent=self.root)
            return
        if payload['activate'] and not confirm(self.root, '指定為主要管理 iPad?', '當未接外接螢幕時，系統將自動連線並以此 iPad 作為主要顯示器。'):
            return
        self.change('save_pairing', payload)

    def save_candidate(self):
        """Fallback method for tests/CLI without card arguments."""
        if self.readonly or self.busy:
            return
        if not self.candidates:
            return
        cand = getattr(self, 'selected_candidate', None) or next(iter(self.candidates.values()))
        name = cand.get('name', '')
        self.save_candidate_card(cand, name, 0, False)

    def set_virtual(self, name=None):
        if self.readonly or self.busy:
            return
        d = None
        if name:
            d = next((v for v in self.virtuals.values() if v.get('name') == name), {'name': name})
        elif self.virtuals:
            d = getattr(self, 'selected_virtual', None) or next(iter(self.virtuals.values()))
        if not d:
            return
        if confirm(self.root, '指定為虛擬備援?',
                   f"螢幕：{d['name']}\n之後以此螢幕作為備援；依目前模式可能啟用它，不主動移除原有備援連線。"):
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
            if delete:
                app.delete_selected(delete)
            else:
                app.select_target(select)

        app.task(read_view, ready)
    else:
        app.search()
    root.mainloop()
