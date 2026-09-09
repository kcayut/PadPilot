"""Modern Apple-style Card UI for PadPilot settings, display topology, and pairing.

Zero external dependencies; pure Python standard library (tkinter + ttk).
"""
from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.betterdisplay import BetterDisplayCLI
from core.config import Config, get_config_file_path, get_status_file_path, read_status
from core.detector import DisplayDetector
from core.logger import get_log_file_path
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
    'automatic': '無實體螢幕時自動連線 iPad 並設為主螢幕；有實體螢幕時以實體為主，已連線的 iPad 保持為副螢幕。',
    'manual_only': '自動化程序暫停，不主動連線或斷開，完全由使用者自 Menu Bar 手動操控。',
    'prefer_ipad': '即使已接上實體螢幕，依然優先連線 iPad 並將其作為主要顯示器。'
}


def short_id(value: str) -> str:
    return value[:8] + '…' + value[-6:] if len(value) > 20 else value or '未設定'


def get_sync_signatures() -> tuple:
    """Return lightweight tuple of (st_ino, st_mtime_ns, st_size) for config and status files."""
    sigs = []
    for p in (get_config_file_path(), get_status_file_path()):
        try:
            st = p.stat()
            sigs.append((str(p), st.st_ino, st.st_mtime_ns, st.st_size))
        except OSError:
            sigs.append((str(p), 0, 0, 0))
    return tuple(sigs)


def read_view(scan: bool = False) -> dict:
    """Read-only view of configuration and hardware status."""
    path = get_config_file_path()
    cfg = Config()
    if path.exists():
        try:
            cfg = Config.from_dict(json.loads(path.read_text()))
        except Exception:
            cfg = Config()
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

    status_cfg_rev = int(status.get('config_revision', 0))
    cfg_rev = int(cfg.revision)
    if status_cfg_rev == cfg_rev:
        consistency = "CONSISTENT"
    elif status_cfg_rev < cfg_rev:
        consistency = "APPLYING_CONFIG"
    else:
        consistency = "REVISION_CONFLICT"

    hw_stamp = actual.get('timestamp', time.time())
    hw_age = max(0.0, time.time() - hw_stamp) if isinstance(hw_stamp, (int, float)) else 0.0

    return {
        'config': cfg,
        'actual': actual,
        'fresh': fresh,
        'identifiers': identifiers,
        'scanned': scan,
        'status': status,
        'consistency_state': consistency,
        'status_revision': int(status.get('status_revision', 0)),
        'config_revision': cfg_rev,
        'status_config_revision': status_cfg_rev,
        'hardware_snapshot': actual,
        'hardware_snapshot_age': hw_age,
        'evaluation_state': status.get('evaluation_state', 'idle'),
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
    app = getattr(parent, '_padpilot_app', None)
    if app is not None:
        app.modal_depth += 1
    try:
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
    finally:
        if app is not None:
            app.modal_depth = max(0, app.modal_depth - 1)


class Card(tk.Frame):
    """Modern macOS-style white container with a 1px soft border."""
    def __init__(self, parent, bg=CARD_BG, border=CARD_BORDER, padx=12, pady=8, **kw):
        super().__init__(parent, bg=bg, highlightbackground=border, highlightcolor=border,
                         highlightthickness=1, bd=0, **kw)
        self.body = tk.Frame(self, bg=bg)
        self.body.pack(fill='both', expand=True, padx=padx, pady=pady)


class SettingsWindow:
    def __init__(self, root: tk.Tk, page: str = 'paired'):
        self.root = root
        self.root._padpilot_app = self
        self.readonly = False
        valid_tabs = {'paired', 'search', 'settings', 'displays', 'virtual', 'diagnostics'}
        self.current_tab = page if page in valid_tabs else 'paired'
        self.view = {'config': Config(), 'actual': {}, 'identifiers': [], 'fresh': False, 'status': {}}
        self.busy = False
        self.modal_depth = 0
        self.dirty_fields = {}
        self._sync_in_progress = False
        self._sync_pending = False
        self._last_sync_sig = get_sync_signatures()
        self._last_config_revision = 0
        self._last_status_revision = 0
        self.results = queue.Queue()
        self.buttons = []
        self.nav_widgets = {}
        self.profiles = {}
        self.expanded_profiles = set()
        self.candidates = {}
        self.virtuals = {}
        self.usbs = []
        self.selected_profile_key = None
        self.selected_candidate = None
        self.selected_virtual = None
        self.log_filter_var = tk.StringVar(value='全部')
        self.logs_expanded = True

        # Window setup: font sizes reduced by 2 points across the board
        root.title('PadPilot — 螢幕與配對管理')
        root.geometry('960x620')
        root.minsize(840, 500)
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
            ('diagnostics', '🩺', '狀態與診斷'),
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
            canvas_width = self.canvas.winfo_width()
            canvas_height = self.canvas.winfo_height()
            if canvas_width <= 1 or canvas_height <= 1:
                return

            height = max(self.scroll_frame.winfo_reqheight(), canvas_height)
            dimensions = (canvas_width, height)
            if dimensions != getattr(self, '_scroll_dimensions', None):
                self._scroll_dimensions = dimensions
                self.canvas.itemconfig(self.canvas_window, width=canvas_width, height=height)
                self.canvas.configure(scrollregion=(0, 0, canvas_width, height))
            if height <= canvas_height:
                self.canvas.yview_moveto(0.0)

        self._update_scrollregion = _update_scrollregion
        self.scroll_frame.bind('<Configure>', lambda e: _update_scrollregion())
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scroll_frame, anchor='nw')

        def _on_canvas_resize(event):
            _update_scrollregion()

        self.canvas.bind('<Configure>', _on_canvas_resize)
        self.canvas.pack(fill='both', expand=True)

        # Smooth, responsive mousewheel handling
        def _on_mousewheel(event):
            if not self.canvas.winfo_exists():
                return
            if isinstance(getattr(event, 'widget', None), tk.Text):
                return
            try:
                # Check pointer position to ensure mouse is within PadPilot window
                x, y = self.root.winfo_pointerxy()
                rx = self.root.winfo_rootx()
                ry = self.root.winfo_rooty()
                rw = self.root.winfo_width()
                rh = self.root.winfo_height()
                if not (rx <= x <= rx + rw and ry <= y <= ry + rh):
                    return

                req_h = self.scroll_frame.winfo_reqheight()
                canvas_height = self.canvas.winfo_height()

                # If content fits completely inside the window, NEVER scroll!
                if req_h <= canvas_height:
                    self.canvas.yview_moveto(0.0)
                    return

                # Ensure scrollregion reflects true content height
                sr = self.canvas.cget('scrollregion')
                if sr:
                    try:
                        sr_parts = [int(float(v)) for v in sr.split()]
                        if len(sr_parts) >= 4 and sr_parts[3] < req_h:
                            _update_scrollregion()
                    except (IndexError, ValueError):
                        pass

                delta = getattr(event, 'delta', 0)
                if not delta:
                    return

                # Calculate smooth step based on delta
                if abs(delta) >= 120:
                    step = -int(delta / 120) * 2
                else:
                    val = int(delta)
                    if val == 0:
                        val = 1 if delta > 0 else -1
                    step = max(-4, min(4, -val))

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

        # FocusIn check: only top-level root window gaining focus
        self.root.bind('<FocusIn>', self._on_focus_in)
        # Periodic background check (schedule earliest after 300ms)
        self.root.after(300, self._auto_sync_tick)

    def _on_focus_in(self, event):
        if event.widget is self.root:
            self._check_external_sync()

    def _auto_sync_tick(self):
        if not getattr(self, 'root', None) or not self.root.winfo_exists():
            return
        try:
            self._check_external_sync()
        finally:
            if self.root.winfo_exists():
                self.root.after(300, self._auto_sync_tick)

    def _check_external_sync(self):
        if getattr(self, '_sync_in_progress', False):
            self._sync_pending = True
            return
        if getattr(self, 'busy', False) or getattr(self, 'one_shot', False):
            return
        if getattr(self, 'modal_depth', 0) > 0:
            return

        curr_sig = get_sync_signatures()
        if curr_sig == getattr(self, '_last_sync_sig', None):
            return

        self._sync_in_progress = True
        self._sync_pending = False
        self._last_sync_sig = curr_sig

        try:
            new_view = read_view(scan=False)
            new_cfg_rev = new_view.get('config', Config()).revision
            new_stat_rev = new_view.get('status_revision', 0)

            # Skip redundant re-render if both revisions are identical to last displayed
            if (new_cfg_rev == getattr(self, '_last_config_revision', 0) and
                new_stat_rev == getattr(self, '_last_status_revision', 0) and
                hasattr(self, 'view') and self.view):
                return

            self._last_config_revision = new_cfg_rev
            self._last_status_revision = new_stat_rev
            self.display(new_view, preserve_scroll=True)
        except Exception as e:
            pass
        finally:
            self._sync_in_progress = False
            if self._sync_pending:
                self._sync_pending = False
                self.root.after_idle(self._check_external_sync)

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
            'diagnostics': ('狀態與診斷', '檢視系統即時決策狀態、狀態機轉換與運行日誌'),
        }
        t, st = titles.get(tab_id, ('PadPilot', ''))
        self.title_label.configure(text=t)
        self.subtitle_label.configure(text=st)

        self.render_current_tab(preserve_scroll=False)
        if tab_id == 'diagnostics' and not self.view.get('system_checks') and not self.busy:
            self.root.after_idle(self.search)
        if hasattr(self, '_update_scrollregion'):
            self.root.after_idle(self._update_scrollregion)

    def make_badge(self, parent, text: str, bg: str, fg: str) -> tk.Label:
        return tk.Label(parent, text=f" {text} ", font=('Helvetica Neue', 9, 'bold'),
                        bg=bg, fg=fg, padx=4, pady=1)

    def render_current_tab(self, preserve_scroll: bool = False):
        # Reset dynamic buttons while preserving persistent ones
        self.buttons = [self.refresh_btn]

        old_y = 0.0
        if preserve_scroll and hasattr(self, 'canvas') and self.canvas.winfo_exists():
            try:
                old_y = self.canvas.yview()[0]
            except Exception:
                old_y = 0.0

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
        elif self.current_tab == 'diagnostics':
            self.render_diagnostics_tab()

        self.canvas.update_idletasks()
        if hasattr(self, '_update_scrollregion'):
            self._update_scrollregion()

        if preserve_scroll and old_y > 0.0:
            self.canvas.yview_moveto(min(old_y, 1.0))
        else:
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
            kid = p.get('sidecar_uuid') or key
            is_expanded = kid in getattr(self, 'expanded_profiles', set())

            # Compact card
            card = Card(self.scroll_frame, padx=14, pady=8)
            card.pack(fill='x', padx=18, pady=4)

            # Upper header: Left info (Title, UUID, USB) and Right action column (刪除配對 + 設定/收合)
            header_box = tk.Frame(card.body, bg=CARD_BG)
            header_box.pack(fill='x')

            info_col = tk.Frame(header_box, bg=CARD_BG)
            info_col.pack(side='left', fill='x', expand=True)

            action_col = tk.Frame(header_box, bg=CARD_BG)
            action_col.pack(side='right', anchor='ne', padx=(10, 0))

            # Action buttons vertically stacked on the right
            del_btn = ttk.Button(
                action_col, text='刪除配對',
                command=lambda k=key: self.delete_selected(k),
                style='Danger.TButton'
            )
            del_btn.pack(fill='x', pady=(0, 4))
            self.buttons.append(del_btn)

            exp_btn = ttk.Button(
                action_col, text='收合 ▲' if is_expanded else '設定 ▼',
                command=lambda k=kid: self.toggle_profile_expand(k),
                style='Secondary.TButton'
            )
            exp_btn.pack(fill='x')
            self.buttons.append(exp_btn)

            # Info Line 1: Name & Badges
            top_line = tk.Frame(info_col, bg=CARD_BG)
            top_line.pack(fill='x')

            # Downward arrow toggle
            arrow_icon = '▼' if is_expanded else '▶'
            arrow_lbl = tk.Label(top_line, text=f"{arrow_icon} ", font=('Helvetica Neue', 10),
                                 fg=BLUE, bg=CARD_BG, cursor='hand2')
            arrow_lbl.pack(side='left', padx=(0, 2))
            arrow_lbl.bind('<Button-1>', lambda e, k=kid: self.toggle_profile_expand(k))

            tk.Label(top_line, text='📱', font=('Helvetica Neue', 13), bg=CARD_BG).pack(side='left', padx=(0, 4))
            name_lbl = tk.Label(top_line, text=p.get('name', '未命名 iPad'), font=('Helvetica Neue', 11, 'bold'),
                                fg=TEXT_PRIMARY, bg=CARD_BG, cursor='hand2')
            name_lbl.pack(side='left')
            name_lbl.bind('<Button-1>', lambda e, k=kid: self.toggle_profile_expand(k))

            if is_target:
                self.make_badge(top_line, '★ 主要管理 iPad (自動接管)', BLUE, '#ffffff').pack(side='left', padx=(6, 2))

            if status == '已連線':
                self.make_badge(top_line, '● 已連線', GREEN_BG, GREEN_FG).pack(side='left', padx=2)
            elif status == '僅 USB 已接上':
                self.make_badge(top_line, '⚡ 僅 USB 接上', ORANGE_BG, ORANGE_FG).pack(side='left', padx=2)
            elif status == '已偵測到 Sidecar':
                self.make_badge(top_line, '📡 偵測到 Sidecar', BLUE_TINT, BLUE).pack(side='left', padx=2)
            else:
                self.make_badge(top_line, '○ 離線未連線', '#f2f2f7', TEXT_TERTIARY).pack(side='left', padx=2)

            controls = tk.Frame(card.body, bg=CARD_BG)
            controls.pack(fill='x', pady=(6, 2))
            tk.Label(controls, text='控制', font=('Helvetica Neue', 10, 'bold'),
                     fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w')
            row = tk.Frame(controls, bg=CARD_BG)
            row.pack(fill='x', pady=(3, 0))
            for col, (title, action) in enumerate((('作為副螢幕', 'use_ipad_secondary'),
                    ('設為主螢幕', 'use_ipad_main'), ('中斷連線', 'disconnect_ipad'),
                    ('重新連線', 'reconnect_sidecar'))):
                row.columnconfigure(col, weight=1, uniform='controls')
                button = ttk.Button(row, text=title, width=9, style='Secondary.TButton',
                                    command=lambda a=action, pr=p: self.control_ipad(pr, a))
                button.grid(row=0, column=col, sticky='ew', padx=(0, 4 if col < 3 else 0))
                if is_target and p.get('sidecar_uuid') and not self.readonly:
                    self.buttons.append(button)
                else:
                    button.state(['disabled'])
            if not is_target:
                tk.Label(controls, text='請先在「設定」中設為主要管理 iPad。',
                         fg=TEXT_SECONDARY, bg=CARD_BG, font=('Helvetica Neue', 9)).pack(anchor='w')

            # Info Line 2: Sidecar UUID
            uuid_str = p.get('sidecar_uuid') or '未設定'
            tk.Label(card.body, text=f"Sidecar UUID: {uuid_str}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG, anchor='w').pack(fill='x', pady=(4, 0))

            # Info Line 3: USB 序號
            usb_str = p.get('usb_serial') or '未設定'
            usb_suffix = ' (目前已接上 USB)' if any(u.get('serial') == p.get('usb_serial') for u in self.view['actual'].get('usb_devices', [])) else ''
            tk.Label(card.body, text=f"USB 序號:      {usb_str}{usb_suffix}", font=('Menlo', 9),
                     fg=TEXT_SECONDARY, bg=CARD_BG, anchor='w').pack(fill='x', pady=(1, 0))

            # Expanded settings drawer
            if is_expanded:
                tk.Frame(card.body, bg='#e5e5ea', height=1).pack(fill='x', pady=(8, 8))

                edit_box = tk.Frame(card.body, bg=CARD_BG)
                edit_box.pack(fill='x')

                # Row 1: 自訂名稱 + [ 更新名稱 ] 按鈕
                r1 = tk.Frame(edit_box, bg=CARD_BG)
                r1.pack(fill='x', pady=2)
                tk.Label(r1, text='自訂名稱：', font=('Helvetica Neue', 10),
                         fg=TEXT_SECONDARY, bg=CARD_BG, width=12, anchor='w').pack(side='left')
                draft_field = f"name.{kid}"
                draft = self.dirty_fields.get(draft_field)
                initial_name = draft['value'] if draft else p.get('name', '')
                name_var = tk.StringVar(value=initial_name)

                def on_name_edit(*_args, df=draft_field, nv=name_var, orig=p.get('name', '')):
                    curr = nv.get()
                    if curr != orig:
                        self.dirty_fields[df] = {'value': curr, 'base_revision': self.view['config'].revision}
                    elif df in self.dirty_fields:
                        del self.dirty_fields[df]

                name_var.trace_add('write', on_name_edit)
                name_entry = tk.Entry(
                    r1, textvariable=name_var, font=('Helvetica Neue', 10),
                    bg='#ffffff', fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
                    selectbackground=BLUE, selectforeground='#ffffff',
                    highlightbackground='#d1d1d6', highlightthickness=1, relief='flat'
                )
                name_entry.pack(side='left', fill='x', expand=True, padx=(0, 6))
                up_name_btn = ttk.Button(
                    r1, text='更新名稱',
                    command=lambda pr=p, nv=name_var: self.update_profile_name(pr, nv.get()),
                    style='Secondary.TButton'
                )
                up_name_btn.pack(side='right')
                self.buttons.append(up_name_btn)

                # Row 2: 對應 USB + [ 更新 USB 設定 ] 按鈕
                r2 = tk.Frame(edit_box, bg=CARD_BG)
                r2.pack(fill='x', pady=2)
                tk.Label(r2, text='對應 USB：', font=('Helvetica Neue', 10),
                         fg=TEXT_SECONDARY, bg=CARD_BG, width=12, anchor='w').pack(side='left')
                usb_options = ['略過 / 未綁定 USB'] + [
                    f"{u.get('product_name') or u.get('name')} · {u['serial']}" for u in self.usbs
                ]
                usb_cb = ttk.Combobox(r2, state='readonly', values=usb_options, style='TCombobox')
                pre_idx = 0
                if p.get('usb_serial'):
                    for i, u in enumerate(self.usbs):
                        if u.get('serial') == p.get('usb_serial'):
                            pre_idx = i + 1
                            break
                usb_cb.current(pre_idx)
                usb_cb.pack(side='left', fill='x', expand=True, padx=(0, 6))
                up_usb_btn = ttk.Button(
                    r2, text='更新 USB 設定',
                    command=lambda pr=p, ucb=usb_cb: self.update_profile_usb(pr, ucb.current()),
                    style='Secondary.TButton'
                )
                up_usb_btn.pack(side='right')
                self.buttons.append(up_usb_btn)

                # Row 3: 設為主要管理 iPad
                r3 = tk.Frame(edit_box, bg=CARD_BG)
                r3.pack(fill='x', pady=(4, 2))
                tk.Label(r3, text='主力管理：', font=('Helvetica Neue', 10),
                         fg=TEXT_SECONDARY, bg=CARD_BG, width=12, anchor='w').pack(side='left')
                if is_target:
                    self.make_badge(r3, '✓ 目前已是主要管理 iPad（無實體外接螢幕時自動連線接管）', BLUE_TINT, BLUE).pack(side='left')
                else:
                    tgt_btn = ttk.Button(
                        r3, text='設為主要管理 iPad',
                        command=lambda k=key: self.select_target(k),
                        style='Accent.TButton'
                    )
                    tgt_btn.pack(side='left', padx=(0, 6))
                    self.buttons.append(tgt_btn)
                    tk.Label(r3, text='（當 Mac 未接實體外接螢幕時，系統將自動連線此 iPad 作為主顯示器）',
                             font=('Helvetica Neue', 9), fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left')

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

            if prev:
                # 已配對裝置：不再保留設定功能，顯示狀態與跳轉提示
                tip_box = tk.Frame(card.body, bg=CARD_BG)
                tip_box.pack(fill='x', pady=(4, 0))
                tk.Label(
                    tip_box,
                    text='✓ 此裝置已完成配對。若需自訂名稱、對應 USB 或設為主力 iPad，請至「已配對 iPad」分頁設定。',
                    font=('Helvetica Neue', 9), fg=TEXT_SECONDARY, bg=CARD_BG, justify='left'
                ).pack(side='left')
                go_paired_btn = ttk.Button(
                    tip_box, text='前往「已配對 iPad」設定 →',
                    command=lambda: self.select_tab('paired'),
                    style='Secondary.TButton'
                )
                go_paired_btn.pack(side='right')
                self.buttons.append(go_paired_btn)
            else:
                # 新發現未配對裝置：提供配對設定欄位
                tk.Frame(card.body, bg='#f2f2f7', height=1).pack(fill='x', pady=(4, 6))

                # Row 1: 自訂名稱
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
                    fg=TEXT_PRIMARY,
                    insertbackground=TEXT_PRIMARY,
                    selectbackground=BLUE,
                    selectforeground='#ffffff',
                    highlightbackground='#d1d1d6',
                    highlightthickness=1,
                    relief='flat'
                )
                name_entry.pack(side='left', fill='x', expand=True)

                # Row 2: 對應 USB
                f_row2 = tk.Frame(card.body, bg=CARD_BG)
                f_row2.pack(fill='x', pady=2)
                tk.Label(f_row2, text='對應 USB：', font=('Helvetica Neue', 10),
                         fg=TEXT_SECONDARY, bg=CARD_BG, width=10, anchor='w').pack(side='left')
                usb_options = ['略過 / 未綁定 USB'] + [
                    f"{u.get('product_name') or u.get('name')} · {u['serial']}" for u in self.usbs
                ]
                usb_cb = ttk.Combobox(f_row2, state='readonly', values=usb_options, style='TCombobox')
                usb_cb.current(0)
                usb_cb.pack(side='left', fill='x', expand=True)

                # Bottom action row
                act_row = tk.Frame(card.body, bg=CARD_BG)
                act_row.pack(fill='x', pady=(6, 0))

                act_var = tk.BooleanVar(value=False)
                chk = ttk.Checkbutton(act_row, text='設為主要管理 iPad（無螢幕時自動接管）',
                                      variable=act_var, style='TCheckbutton')
                chk.pack(side='left')

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
        tk.Label(s_row, text='（隨 macOS 登入背景自動執行）', font=('Helvetica Neue', 9),
                 fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=2)

        if not self.readonly:
            toggle_btn = ttk.Button(
                s_row,
                text='切換為停用' if cfg.autostart_on_login else '切換為啟用',
                command=self.toggle_autostart_action,
                style='Secondary.TButton' if cfg.autostart_on_login else 'Accent.TButton'
            )
            toggle_btn.pack(side='right')
            self.buttons.append(toggle_btn)

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
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(anchor='w', pady=(0, 6))

        # BetterDisplay CLI 區塊
        bd_row = tk.Frame(g4.body, bg=CARD_BG)
        bd_row.pack(fill='x', pady=2)

        resolved_cli = BetterDisplayCLI.resolve_cli_path(cfg.betterdisplaycli_path)
        is_custom = bool(cfg.betterdisplaycli_path)

        bd_left = tk.Frame(bd_row, bg=CARD_BG)
        bd_left.pack(side='left', fill='x', expand=True)

        tk.Label(bd_left, text='BetterDisplay CLI：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        cli_display_text = resolved_cli if resolved_cli else '未找到可用的 BetterDisplay CLI'
        tk.Label(bd_left, text=cli_display_text, font=('Menlo', 9),
                 fg=TEXT_PRIMARY if resolved_cli else RED, bg=CARD_BG).pack(side='left', padx=(2, 6))

        if resolved_cli:
            status_text = '手動指定' if is_custom else '自動偵測'
            status_bg = ORANGE_BG if is_custom else BLUE_TINT
            status_fg = ORANGE_FG if is_custom else BLUE
            self.make_badge(bd_left, status_text, status_bg, status_fg).pack(side='left')
        else:
            self.make_badge(bd_left, '未找到', RED_BG, RED).pack(side='left')

        if not self.readonly:
            bd_btn_frame = tk.Frame(bd_row, bg=CARD_BG)
            bd_btn_frame.pack(side='right')

            manual_btn = ttk.Button(
                bd_btn_frame,
                text='手動設定',
                command=self.set_betterdisplay_cli_action,
                style='Secondary.TButton'
            )
            manual_btn.pack(side='left', padx=(0, 4))
            self.buttons.append(manual_btn)

            reset_btn = ttk.Button(
                bd_btn_frame,
                text='恢復預設',
                command=self.reset_betterdisplay_cli_action,
                style='Secondary.TButton',
                state='normal' if is_custom else 'disabled'
            )
            reset_btn.pack(side='left')
            self.buttons.append(reset_btn)

        # 設定檔位置
        cfg_row = tk.Frame(g4.body, bg=CARD_BG)
        cfg_row.pack(fill='x', pady=(4, 0))
        tk.Label(cfg_row, text='設定檔位置：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        tk.Label(cfg_row, text=str(get_config_file_path()),
                 font=('Menlo', 9), fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left', padx=2)

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
            is_connected = str(d.get('displayID', '0')).isdecimal() and int(d.get('displayID', 0)) > 0

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

    def render_diagnostics_tab(self):
        self.diagnostic_hosts = {}
        for section in ('decision', 'system_checks', 'authenticated_checks', 'logs'):
            host = tk.Frame(self.scroll_frame, bg=BG)
            host.pack(fill='x')
            self.diagnostic_hosts[section] = host
        self.render_decision_card()
        self.render_checks_card('system_checks')
        self.render_checks_card('authenticated_checks')
        self.render_logs_card()

    def render_decision_card(self):
        status = self.view.get('status') or {}
        actual = self.view.get('actual') or {}
        desired = status.get('desired') or {}
        runtime = status.get('runtime') or {}
        details = status.get('status_details') or {}
        fresh = self.view.get('fresh', False)

        # Card 1: 決策與系統診斷 (Decision & System Diagnostics)
        diag_card = Card(self.diagnostic_hosts['decision'], padx=12, pady=6)
        diag_card.pack(fill='x', padx=18, pady=(0, 4))

        top_r = tk.Frame(diag_card.body, bg=CARD_BG)
        top_r.pack(fill='x', pady=(0, 2))
        tk.Label(top_r, text='🩺 自動化決策與狀態機', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        # Action buttons on right
        act_box = tk.Frame(top_r, bg=CARD_BG)
        act_box.pack(side='right')

        ref_btn = ttk.Button(
            act_box, text='重新整理',
            command=lambda: self.refresh_diagnostic('decision'),
            style='Secondary.TButton'
        )
        ref_btn.pack(side='left')
        self.buttons.append(ref_btn)

        # Decision metrics
        consistency = self.view.get('consistency_state', 'CONSISTENT')
        d_role = desired.get('target_display_role') or details.get('desired_role') or '未知'
        if consistency == 'APPLYING_CONFIG':
            d_sat = '切換中…'
            d_reason = '套用新設定中…（等待背景服務評估）'
        elif consistency == 'REVISION_CONFLICT':
            d_sat = '不同步'
            d_reason = '⚠️ 設定檔版本與背景服務狀態不一致，正在重新整理…'
        else:
            d_sat = details.get('actual_role_satisfied') or ('已滿足' if actual.get('sidecar_connected') else '評估中')
            d_reason = desired.get('reason') or details.get('reason') or '尚無背景決策資訊'
        t_state = runtime.get('transition_state') or 'IDLE'
        last_err = runtime.get('last_error') or '無'
        cooldown = runtime.get('cooldown_until', 0)
        is_cooldown = isinstance(cooldown, (int, float)) and cooldown > time.time()

        r1 = tk.Frame(diag_card.body, bg=CARD_BG)
        r1.pack(fill='x', pady=1)
        tk.Label(r1, text='期望目標：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        self.make_badge(r1, d_role, BLUE_TINT, BLUE).pack(side='left', padx=2)

        tk.Label(r1, text='實際狀態：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left', padx=(8, 0))
        self.make_badge(r1, d_sat if (fresh or consistency == 'APPLYING_CONFIG') else '資料待更新',
                        GREEN_BG if ('Satisfied' in d_sat or '滿足' in d_sat) else ORANGE_BG,
                        GREEN_FG if ('Satisfied' in d_sat or '滿足' in d_sat) else ORANGE_FG).pack(side='left', padx=2)

        tk.Label(r1, text='狀態機轉換：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left', padx=(8, 0))
        self.make_badge(r1, t_state, '#f2f2f7', TEXT_SECONDARY).pack(side='left', padx=2)

        if is_cooldown:
            self.make_badge(r1, '⚠️ 冷卻保護中', RED_BG, RED).pack(side='left', padx=2)

        # Decision reason
        r2 = tk.Frame(diag_card.body, bg=CARD_BG)
        r2.pack(fill='x', pady=(2, 1))
        tk.Label(r2, text='決策依據：', font=('Helvetica Neue', 10, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        tk.Label(r2, text=d_reason, font=('Helvetica Neue', 10),
                 fg=TEXT_SECONDARY, bg=CARD_BG, justify='left', wraplength=480).pack(side='left', padx=2)

        # Errors if any
        if last_err and last_err != '無':
            r3 = tk.Frame(diag_card.body, bg=CARD_BG)
            r3.pack(fill='x', pady=1)
            tk.Label(r3, text='最近錯誤：', font=('Helvetica Neue', 10, 'bold'),
                     fg=RED, bg=CARD_BG).pack(side='left')
            tk.Label(r3, text=last_err, font=('Helvetica Neue', 10),
                     fg=RED, bg=CARD_BG, wraplength=480, justify='left').pack(side='left', padx=2)

    def render_checks_card(self, section):
        authenticated = section == 'authenticated_checks'
        card = Card(self.diagnostic_hosts[section], padx=12, pady=8)
        card.pack(fill='x', padx=18, pady=(0, 6))
        top = tk.Frame(card.body, bg=CARD_BG)
        top.pack(fill='x')
        title = '啟動與必要設定偵測 — 需要系統驗證' if authenticated else '啟動與必要設定偵測 — 不需帳號密碼'
        tk.Label(top, text=title, font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')
        refresh = ttk.Button(top, text='重新整理', style='Secondary.TButton',
                             command=lambda: self.refresh_diagnostic(section))
        refresh.pack(side='right')
        self.buttons.append(refresh)
        if authenticated:
            note = tk.Label(card.body, text='查詢登入項目時，macOS 可能要求輸入管理員帳號與密碼。'
                            '請在系統驗證視窗輸入；PadPilot 不會收集或儲存密碼。只有按此區重新整理才會查詢。',
                            font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg=CARD_BG,
                            anchor='w', justify='left', wraplength=500)
            note.pack(fill='x', pady=(5, 3))
        checks = self.view.get(section) or [('偵測', '尚未檢查；請按此區「重新整理」')]
        for label, value in checks:
            line = tk.Label(card.body, text=f'{label}：{value}', anchor='w', justify='left',
                            font=('Helvetica Neue', 10), fg=TEXT_PRIMARY, bg=CARD_BG)
            line.pack(fill='x', pady=2)
            line.bind('<Configure>', lambda e, w=line: w.configure(wraplength=max(100, e.width - 8)))

    def render_logs_card(self):
        # Card 2: 系統運行日誌 (System Logs) - expands to fill remaining space
        log_card = Card(self.diagnostic_hosts['logs'], padx=12, pady=6)
        log_card.pack(fill='both', expand=True, padx=18, pady=(0, 4))

        l_top = tk.Frame(log_card.body, bg=CARD_BG)
        l_top.pack(fill='x', pady=(0, 4))

        tk.Label(l_top, text='📜 系統運行日誌 (padpilot.log)', font=('Helvetica Neue', 11, 'bold'),
                 fg=TEXT_PRIMARY, bg=CARD_BG).pack(side='left')

        toggle = ttk.Button(l_top, text='收合 ▲' if self.logs_expanded else '展開 ▼',
                            command=self.toggle_logs, style='Secondary.TButton')
        toggle.pack(side='right')
        self.buttons.append(toggle)
        if not self.logs_expanded:
            return
        l_tools = tk.Frame(log_card.body, bg=CARD_BG)
        l_tools.pack(fill='x', pady=(0, 4))

        # Filter combobox
        tk.Label(l_tools, text='篩選：', font=('Helvetica Neue', 9),
                 fg=TEXT_SECONDARY, bg=CARD_BG).pack(side='left')
        filter_cb = ttk.Combobox(
            l_tools, textvariable=self.log_filter_var, state='readonly',
            values=['全部', '僅 WARNING / ERROR', '僅 ERROR', '僅 INFO'],
            width=14, style='TCombobox'
        )
        filter_cb.pack(side='left', padx=(0, 6))
        filter_cb.bind('<<ComboboxSelected>>', lambda e: self.refresh_logs())

        reload_log_btn = ttk.Button(l_tools, text='🔄 刷新日誌', command=self.refresh_logs, style='Secondary.TButton')
        reload_log_btn.pack(side='left', padx=(0, 4))
        self.buttons.append(reload_log_btn)

        open_ext_btn = ttk.Button(l_tools, text='外部開啟', command=self.open_external_log, style='Secondary.TButton')
        open_ext_btn.pack(side='left')
        self.buttons.append(open_ext_btn)

        # Log Text Box (Dark console theme with syntax colors)
        log_frame = tk.Frame(log_card.body, bg='#1a1b20', highlightbackground='#2d2f36',
                             highlightthickness=1)
        log_frame.pack(fill='both', expand=True, pady=(2, 0))

        self.log_text = tk.Text(
            log_frame, bg='#1a1b20', fg='#f2f2f7',
            font=('Menlo', 9), wrap='word', height=12, width=1, borderwidth=0, highlightthickness=0
        )
        log_scroll = ttk.Scrollbar(log_frame, orient='vertical', command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side='left', fill='both', expand=True, padx=8, pady=6)
        log_scroll.pack(side='right', fill='y')

        # Tag styles for high-contrast syntax highlighting
        self.log_text.tag_configure('time', foreground='#717887')
        self.log_text.tag_configure('info', foreground='#30d158', font=('Menlo', 9, 'bold'))
        self.log_text.tag_configure('warning', foreground='#ff9f0a', font=('Menlo', 9, 'bold'))
        self.log_text.tag_configure('error', foreground='#ff453a', font=('Menlo', 9, 'bold'))
        self.log_text.tag_configure('module', foreground='#64d2ff')
        self.log_text.tag_configure('msg', foreground='#f2f2f7')

        self.refresh_logs()

    def toggle_logs(self):
        self.logs_expanded = not self.logs_expanded
        self.render_current_tab(preserve_scroll=True)

    def refresh_logs(self):
        if not hasattr(self, 'log_text') or not self.log_text.winfo_exists():
            return
        log_path = get_log_file_path()
        if not log_path.exists():
            self.log_text.configure(state='normal')
            self.log_text.delete('1.0', 'end')
            self.log_text.insert('end', '尚無日誌檔案。\n', 'time')
            self.log_text.configure(state='disabled')
            return

        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()[-200:]
        except Exception as e:
            self.log_text.configure(state='normal')
            self.log_text.delete('1.0', 'end')
            self.log_text.insert('end', f'無法讀取日誌：{e}\n', 'error')
            self.log_text.configure(state='disabled')
            return

        filter_val = self.log_filter_var.get()

        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', 'end')

        pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+\[([A-Z]+)\]\s+\[(.*?)\]\s+(.*)$')

        matched_count = 0
        for line in lines:
            line_str = line.rstrip('\n')

            m = pattern.match(line_str)
            if m:
                ts, lvl, mod, msg = m.groups()
                lvl_upper = lvl.upper()
                if filter_val == '僅 WARNING / ERROR' and lvl_upper not in ('WARNING', 'ERROR'):
                    continue
                if filter_val == '僅 ERROR' and lvl_upper != 'ERROR':
                    continue
                if filter_val == '僅 INFO' and lvl_upper != 'INFO':
                    continue

                self.log_text.insert('end', ts + ' ', 'time')
                self.log_text.insert('end', f'[{lvl_upper}] ', lvl.lower())
                self.log_text.insert('end', f'[{mod}] ', 'module')
                self.log_text.insert('end', msg + '\n', 'msg')
                matched_count += 1
            else:
                if filter_val == '全部':
                    self.log_text.insert('end', line_str + '\n', 'msg')
                    matched_count += 1

        if matched_count == 0:
            self.log_text.insert('end', '（查無符合篩選條件的日誌紀錄）\n', 'time')

        self.log_text.see('end')
        self.log_text.configure(state='disabled')

    def open_external_log(self):
        log_path = get_log_file_path()
        if log_path.exists():
            subprocess.run(['open', str(log_path)])

    def display(self, view: dict, preserve_scroll: bool = True):
        # Preserve identifiers if view was loaded without full scan
        if not view.get('scanned') and not view.get('identifiers') and hasattr(self, 'view') and self.view.get('identifiers'):
            view['identifiers'] = self.view['identifiers']

        for section in ('system_checks', 'authenticated_checks'):
            if section not in view and hasattr(self, 'view'):
                view[section] = self.view.get(section, [])
        self.view = view
        cfg = view['config']
        actual = view.get('actual', {})

        # Update sidebar summary labels
        mode_text = MODES.get(cfg.mode.value, cfg.mode.value)
        consistency = view.get('consistency_state', 'CONSISTENT')
        if consistency == 'APPLYING_CONFIG':
            self.side_mode_label.configure(text=f"模式：{mode_text} (套用中…)")
        else:
            self.side_mode_label.configure(text=f"模式：{mode_text}")

        target_name = cfg.ipad.name or '尚未指定'
        self.side_target_label.configure(text=f"主力：{target_name}")

        self.profiles = {pairing_key(p.to_dict()): p.to_dict() for p in cfg.paired_ipads}
        self.candidates = {d['uuid']: d for d in actual.get('sidecar_devices', []) if d.get('uuid')}
        if view.get('identifiers'):
            self.virtuals = {str(i): d for i, d in enumerate(view.get('identifiers', [])) if is_virtual_device(d)}
        elif view.get('scanned') or not hasattr(self, 'virtuals'):
            self.virtuals = {}
        self.usbs = [u for u in actual.get('usb_devices', []) if u.get('serial')]

        errors = actual.get('discovery_errors', {})
        if errors:
            self.notice.configure(text='部分狀態未知：' + '；'.join(errors.values()))
        elif consistency == 'APPLYING_CONFIG':
            self.notice.configure(text='正在套用新設定至硬體…')
        elif consistency == 'REVISION_CONFLICT':
            self.notice.configure(text='⚠️ 設定版本不同步，正在重新整理…')
        else:
            ts = time.strftime('%H:%M:%S')
            count = len(self.profiles)
            self.notice.configure(text=f"更新於 {ts} · {count} 台已配對")

        self.render_current_tab(preserve_scroll=preserve_scroll)
        self._last_sync_sig = get_sync_signatures()
        self._last_config_revision = cfg.revision
        self._last_status_revision = view.get('status_revision', 0)

    def task(self, work, complete):
        if self.busy:
            return
        self.busy = True
        button_states = [(b, b.instate(['disabled'])) for b in self.buttons]
        for button, _disabled in button_states:
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
            for button, was_disabled in button_states:
                try:
                    button.state(['disabled'] if was_disabled else ['!disabled'])
                except Exception:
                    pass
            if ok:
                complete(value)
            else:
                if 'CONFIG_CONFLICT' in str(value):
                    self.notice.configure(text='⚠️ 設定已被其他來源修改，請確認最新設定。')
                    messagebox.showwarning('設定衝突', '此設定已被其他來源（如 Menu Bar 或 CLI）修改。\n\n您輸入的內容已保留，請檢視最新狀態後再次儲存。', parent=self.root)
                else:
                    self.notice.configure(text='操作未完成；請檢查錯誤後重試。')
                    messagebox.showerror('PadPilot', value, parent=self.root)
                if getattr(self, 'one_shot', False):
                    self.root.destroy()

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, poll)

    def search(self):
        diagnostics = self.current_tab == 'diagnostics'
        def work():
            from core.autostart import is_daemon_running
            if is_daemon_running():
                self.run_action('refresh')
            view = read_view(scan=True)
            if diagnostics:
                from core.diagnostics import collect_system_checks
                view['system_checks'] = collect_system_checks(view['config'], view['actual'])
            return view
        self.task(work, self.display)

    def refresh_diagnostic(self, section):
        if section not in ('decision', 'system_checks', 'authenticated_checks'):
            return
        def work():
            if section == 'authenticated_checks':
                from core.diagnostics import collect_authenticated_checks
                return collect_authenticated_checks()
            if section == 'system_checks':
                from core.diagnostics import collect_system_checks
                view = read_view(scan=True)
                return collect_system_checks(view['config'], view['actual'])
            from core.autostart import is_daemon_running
            if is_daemon_running():
                self.run_action('refresh')
            return read_view()

        def complete(result):
            if section == 'decision':
                self.view.update(result)
                self._last_sync_sig = get_sync_signatures()
                self._last_config_revision = result['config'].revision
                self._last_status_revision = result.get('status_revision', 0)
            else:
                self.view[section] = result
            if self.current_tab == 'diagnostics':
                for widget in self.diagnostic_hosts[section].winfo_children():
                    widget.destroy()
                self.buttons = [button for button in self.buttons if button.winfo_exists()]
                if section == 'decision':
                    self.render_decision_card()
                else:
                    self.render_checks_card(section)
                self._update_scrollregion()
            self.notice.configure(text='此卡片已更新於 ' + time.strftime('%H:%M:%S'))
        self.task(work, complete)

    @staticmethod
    def run_action(action):
        result = subprocess.run([sys.executable, str(ROOT / 'bin/padpilot-cli'), 'action', action],
                                capture_output=True, text=True, timeout=70)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or '操作失敗')
        return result.stdout.strip()

    def control_ipad(self, profile, action):
        if self.readonly or self.busy:
            return
        if profile != self.view['config'].ipad.to_dict():
            return
        def work():
            current = read_view()
            if current['config'].ipad.to_dict() != profile:
                raise RuntimeError('控制目標已變更，請重新整理後再操作。')
            message = self.run_action(action)
            return message, read_view(scan=True)
        def complete(result):
            message, view = result
            self.display(view)
            self.notice.configure(text=message)
        self.task(work, complete)

    def change(self, action: str, payload: dict):
        if self.readonly or self.busy:
            return

        def work():
            message = send_change(action, payload)
            return message, read_view(scan=True)

        def complete(result):
            message, view = result
            if action == 'save_pairing' and 'ipad' in payload:
                kid = payload['ipad'].get('sidecar_uuid') or pairing_key(payload['ipad'])
                self.dirty_fields.pop(f"name.{kid}", None)
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
                capture_output=True, text=True, timeout=70
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
            if not ok:
                raise RuntimeError(msg)
            return msg, read_view(scan=False)

        def complete(result):
            msg, view = result
            self.display(view)
            self.notice.configure(text=msg)

        self.task(work, complete)

    def reset_betterdisplay_cli_action(self):
        if self.readonly or self.busy:
            return
        cfg = self.view['config']
        if not cfg.betterdisplaycli_path:
            messagebox.showinfo('PadPilot', '目前已經是預設自動偵測狀態。', parent=self.root)
            return
        if not confirm(self.root, '恢復預設 CLI 路徑?', '將清除手動指定的路徑，改為由系統自動探測 BetterDisplay CLI。'):
            return
        self.change('set_betterdisplaycli_path', {'path': None})

    def set_betterdisplay_cli_action(self):
        if self.readonly or self.busy:
            return
        cfg = self.view['config']
        current_val = cfg.betterdisplaycli_path or BetterDisplayCLI.resolve_cli_path(None) or ''

        self.modal_depth += 1
        dialog = tk.Toplevel(self.root)
        dialog.title('手動設定 BetterDisplay CLI 路徑')
        dialog.configure(background='#ffffff')
        dialog.resizable(False, False)
        if self.root.state() != 'withdrawn':
            dialog.transient(self.root)

        is_closed = False

        def close_dialog():
            nonlocal is_closed
            if not is_closed:
                is_closed = True
                self.modal_depth = max(0, self.modal_depth - 1)
                dialog.destroy()

        dialog.protocol('WM_DELETE_WINDOW', close_dialog)

        box = tk.Frame(dialog, bg='#ffffff', padx=22, pady=18)
        box.pack(fill='both', expand=True)

        tk.Label(box, text='⚙️ 手動指定 BetterDisplay CLI', font=('Helvetica Neue', 12, 'bold'),
                 fg=TEXT_PRIMARY, bg='#ffffff').pack(anchor='w', pady=(0, 6))
        tk.Label(box, text='請輸入或選擇 betterdisplaycli 執行檔，或 BetterDisplay.app 應用程式路徑：',
                 font=('Helvetica Neue', 10), fg=TEXT_SECONDARY, bg='#ffffff', justify='left').pack(anchor='w', pady=(0, 10))

        entry_frame = tk.Frame(box, bg='#ffffff')
        entry_frame.pack(fill='x', pady=(0, 16))

        path_var = tk.StringVar(value=current_val)
        entry = ttk.Entry(entry_frame, textvariable=path_var, width=48, font=('Menlo', 10))
        entry.pack(side='left', fill='x', expand=True, padx=(0, 8))

        def browse():
            chosen = filedialog.askopenfilename(
                parent=dialog,
                title='選擇 BetterDisplay CLI 或 App',
                filetypes=[('All Executables/Apps', '*')]
            )
            if chosen:
                path_var.set(chosen)
                entry.focus()

        browse_btn = ttk.Button(entry_frame, text='瀏覽…', command=browse, style='Secondary.TButton')
        browse_btn.pack(side='right')

        btn_row = tk.Frame(box, bg='#ffffff')
        btn_row.pack(fill='x')

        def save():
            raw_path = path_var.get().strip()
            if not raw_path:
                messagebox.showerror('無效路徑', '請輸入或選擇有效的路徑，或點擊「恢復預設」以使用自動偵測。', parent=dialog)
                return
            resolved = BetterDisplayCLI.resolve_cli_path(raw_path)
            if not resolved:
                messagebox.showerror('無效路徑', f'指定路徑不存在或無執行權限：\n{raw_path}', parent=dialog)
                return
            close_dialog()
            self.change('set_betterdisplaycli_path', {'path': raw_path})

        save_btn = ttk.Button(btn_row, text='儲存', command=save, style='Accent.TButton')
        save_btn.pack(side='right', padx=(8, 0))

        cancel_btn = ttk.Button(btn_row, text='取消', command=close_dialog, style='Secondary.TButton')
        cancel_btn.pack(side='right')

        dialog.bind('<Return>', lambda e: save())
        dialog.bind('<Escape>', lambda e: close_dialog())
        dialog.grab_set()
        entry.focus()

    def toggle_profile_expand(self, key_id: str):
        if not hasattr(self, 'expanded_profiles'):
            self.expanded_profiles = set()
        if key_id in self.expanded_profiles:
            self.expanded_profiles.remove(key_id)
        else:
            self.expanded_profiles.add(key_id)
        self.render_current_tab()

    def update_profile_name(self, profile: dict, new_name: str):
        if self.busy or not profile:
            return
        new_name = new_name.strip()
        old_name = profile.get('name', '')
        if not new_name:
            messagebox.showerror('名稱不可為空', '請輸入有效的裝置名稱。', parent=self.root)
            return
        if new_name == old_name:
            messagebox.showinfo('名稱未變更', f'裝置名稱已經是「{new_name}」，未作任何變更。', parent=self.root)
            return
        detail = f"是否將名稱由：\n{old_name}\n\n更改成：\n{new_name}"
        if not confirm(self.root, '確定更新裝置名稱?', detail):
            return
        is_target = (profile == self.view['config'].ipad.to_dict())
        payload = {
            'ipad': {
                'name': new_name,
                'sidecar_uuid': profile.get('sidecar_uuid', ''),
                'usb_serial': profile.get('usb_serial', '')
            },
            'activate': is_target
        }
        kid = profile.get('sidecar_uuid') or pairing_key(profile)
        draft = self.dirty_fields.get(f"name.{kid}")
        if draft and isinstance(draft, dict) and 'base_revision' in draft:
            payload['__expected_revision__'] = draft['base_revision']
        self.change('save_pairing', payload)

    def update_profile_usb(self, profile: dict, usb_index: int):
        if self.busy or not profile:
            return
        old_serial = profile.get('usb_serial', '') or '未設定'
        new_serial = self.usbs[usb_index - 1]['serial'] if (0 < usb_index <= len(self.usbs)) else ''
        new_display = new_serial or '略過 / 未綁定'
        if new_serial == profile.get('usb_serial', ''):
            messagebox.showinfo('USB 設定未變更', f'USB 序號已是「{old_serial}」，未作任何變更。', parent=self.root)
            return
        detail = f"裝置：{profile.get('name', '')}\n\n是否將 USB 序號由：\n原設定：{old_serial}\n變更為：{new_display}"
        if not confirm(self.root, '確定更新 USB 設定?', detail):
            return
        is_target = (profile == self.view['config'].ipad.to_dict())
        payload = {
            'ipad': {
                'name': profile.get('name', '').strip(),
                'sidecar_uuid': profile.get('sidecar_uuid', ''),
                'usb_serial': new_serial
            },
            'activate': is_target
        }
        self.change('save_pairing', payload)

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


def run_gui(page='paired', delete=None, select=None):
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
