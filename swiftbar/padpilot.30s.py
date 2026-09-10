#!/usr/bin/env python3
"""<xbar.title>PadPilot Menu Bar Controller</xbar.title>
<xbar.version>v1.1</xbar.version>
<xbar.author>PadPilot</xbar.author>
<xbar.desc>Display manager with device lists and pairing wizard</xbar.desc>
<xbar.dependencies>python3,BetterDisplay</xbar.dependencies>
<swiftbar.hideAbout>true</swiftbar.hideAbout>
<swiftbar.hideRunInTerminal>true</swiftbar.hideRunInTerminal>
<swiftbar.hideLastUpdated>true</swiftbar.hideLastUpdated>
<swiftbar.hideDisablePlugin>true</swiftbar.hideDisablePlugin>
<swiftbar.hideSwiftBar>true</swiftbar.hideSwiftBar>
<swiftbar.refreshOnOpen>true</swiftbar.refreshOnOpen>
"""
from __future__ import annotations

import json
import re
import shlex
import time
import sys
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from core.i18n import LANGUAGES, set_language, tr
from core.autostart import daemon_pids
from core.models import pairing_key

CLI_PATH = PROJECT_ROOT / "bin" / "padpilot-cli"
APP_SUPPORT = Path.home() / "Library" / "Application Support" / "PadPilot"
STATUS_FILE_PRIMARY = APP_SUPPORT / "runtime" / "status.json"
STATUS_FILE_FALLBACK = Path("/tmp/PadPilot/runtime/status.json")
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.padpilot.daemon.plist"
MODES = {"automatic": "自動", "manual_only": "僅手動", "prefer_ipad": "偏好 iPad"}
UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def load_json(*paths: Path) -> dict:
    for path in paths:
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else {}
            except (OSError, ValueError):
                return {}
    return {}


def load_status() -> dict:
    return load_json(STATUS_FILE_PRIMARY, STATUS_FILE_FALLBACK)


def clean(value: object) -> str:
    # External names are labels, never SwiftBar syntax or executable arguments.
    text = ' '.join(str(value).split()).replace('|', '｜')
    text = ''.join(c for c in text if ord(c) >= 32 and ord(c) != 127)
    return text.lstrip('-') or tr('未知')


def item(title: str, depth: int = 0, args: tuple = (), *, terminal: bool = False,
         enabled: bool = True, checked: bool = False) -> None:
    params = ['ansi=false', 'emojize=false', 'symbolize=false']
    if enabled:
        params.append('color=#1c1c1e,#f2f2f7')
    if checked:
        params.append('checked=true')
    if args and enabled:
        params += [f'bash={shlex.quote(str(CLI_PATH))}']
        params += [f'param{i}={shlex.quote(str(value))}' for i, value in enumerate(args, 1)]
        params += [f'terminal={str(terminal).lower()}']
        params.append('refresh=true')
    elif args:
        params.append('color=#888888')
    print('--' * depth + clean(title) + ' | ' + ' '.join(params))


def separator(depth: int = 0) -> None:
    print('--' * depth + '---')


def same_device(a: dict, b: dict) -> bool:
    if a.get('sidecar_uuid') and b.get('sidecar_uuid'):
        return a['sidecar_uuid'].upper() == b['sidecar_uuid'].upper()
    if a.get('usb_serial') and b.get('usb_serial'):
        return a['usb_serial'] == b['usb_serial']
    return bool(a.get('name')) and a == b


def device_details(device: dict, depth: int = 2) -> None:
    if device.get('width') and device.get('height'):
        item(tr('解析度：{0} × {1}', device['width'], device['height']), depth)
    for key, label in (('uuid', tr('螢幕 UUID')), ('sidecar_uuid', 'Sidecar UUID'),
                       ('usb_serial', tr('USB 序號'))):
        if device.get(key):
            item(f"{label}：{device[key]}", depth)


def render(status: dict, config: dict, autostart: bool, now: float | None = None,
           *, service_running: bool | None = None) -> None:
    set_language(config.get('language'))
    now = time.time() if now is None else now
    actual = status.get('actual') or {}
    runtime = status.get('runtime') or {}
    details = status.get('status_details') or {}
    target = config.get('ipad', status.get('configured_ipad') or {})
    paired = list(config.get('paired_ipads', status.get('paired_ipads') or []))
    if any(target.values()) and not any(same_device(target, p) for p in paired):
        paired.append(target)
    auto_detect = config.get('auto_detect_ipad') is True
    if auto_detect:
        target = actual.get('resolved_ipad') or {}
    timestamp = actual.get('timestamp', status.get('timestamp', 0))
    fresh = isinstance(timestamp, (int, float)) and 0 <= now - timestamp <= 120
    errors = actual.get('discovery_errors') or {}
    if fresh and 'sidecar_devices' not in actual:
        errors = dict(errors, sidecar=tr('背景服務尚未提供裝置清單，請重新啟動'))
    cfg_rev = config.get('revision', 0)
    status_cfg_rev = status.get('config_revision', 0)
    is_applying = bool(status and status_cfg_rev < cfg_rev)
    is_out_of_sync = bool(status and status_cfg_rev > cfg_rev)

    mode = config.get('mode') or status.get('mode', 'automatic')
    known_target = bool(target.get('sidecar_uuid') or target.get('usb_serial'))
    controls = fresh and known_target and not (is_applying or is_out_of_sync) and (auto_detect or same_device(target, status.get('configured_ipad') or {}))
    main = actual.get('main_display') or {}
    icon = status.get('icon', '⏸️') if fresh else '⚠️'
    item(f'{icon} PadPilot')
    separator()
    item(tr('主螢幕：{0}', main.get('name') or tr('未偵測到')) + ('' if fresh else tr('（尚無最新狀態）')))
    if is_out_of_sync:
        state = tr('同步狀態重新讀取中…')
    elif is_applying:
        state = tr('套用設定中…')
    elif not fresh:
        state = tr('資料待更新')
    elif errors:
        state = tr('偵測異常')
    elif runtime.get('last_error'):
        state = tr('發生錯誤')
    elif runtime.get('transition_state', 'IDLE') != 'IDLE':
        state = tr('處理中')
    else:
        state = tr('運作中')
    item(tr('模式：{0}｜{1}', tr(MODES.get(mode, mode)), state))
    separator()
    item(tr('螢幕與裝置'))
    item(tr('目前可用'), 1)
    online = actual.get('online_displays', actual.get('physical_displays', []))
    visible = [d for d in online if not d.get('is_virtual')]
    sidecars = actual.get('sidecar_devices') or []
    if not fresh:
        item(tr('狀態未知；請重新整理或啟動背景服務'), 1)
    else:
        for d in visible:
            role = tr('主螢幕') if d.get('is_main') else tr('已連線')
            item(tr('{0} {1} — {2}', '📱' if d.get('is_sidecar') else '🖥️', d.get('name', tr('未知螢幕')), role), 1)
            item(tr('種類：') + ('Sidecar' if d.get('is_sidecar') else tr('實體螢幕')), 2)
            device_details(d)
        for d in sidecars:
            uuid = d.get('uuid', '')
            # Collapse only an unambiguous match to an already online display.
            matches = [x for x in visible if x.get('is_sidecar') and x.get('name') == d.get('name')]
            if len(matches) == 1 and sum(x.get('name') == d.get('name') for x in sidecars) == 1:
                continue
            item(tr('📱 {0} — 偵測到 Sidecar 目標', d.get('name', 'iPad')), 1)
            device_details({'sidecar_uuid': uuid})
        for usb in actual.get('usb_devices', []):
            if 'ipad' not in (usb.get('product_name') or usb.get('name') or '').lower():
                continue
            if any(p.get('usb_serial') and p['usb_serial'] == usb.get('serial') and
                   any(d.get('uuid', '').upper() == p.get('sidecar_uuid', '').upper() for d in sidecars)
                   for p in paired):
                continue
            item(tr('📱 {0} — 僅偵測到 USB', usb.get('product_name') or usb.get('name')), 1)
            device_details({'usb_serial': usb.get('serial')})
        if not visible and not sidecars:
            item(tr('未偵測到可用螢幕') if not errors else tr('裝置清單不完整；請查看診斷'), 1)
        if errors:
            item(tr('⚠ 部分查詢失敗，未列出不代表離線'), 1)
    separator(1)
    item(tr('已配對至 PadPilot'), 1)
    if not paired:
        item(tr('自動偵測中；不會儲存推定配對') if auto_detect else tr('尚未配對；請使用配對精靈'), 1)
    for p in paired:
        active = same_device(p, target)
        available = any(d.get('uuid', '').upper() == p.get('sidecar_uuid', '').upper()
                        for d in sidecars if d.get('uuid') and p.get('sidecar_uuid'))
        usb_present = any(p.get('usb_serial') and u.get('serial') == p['usb_serial']
                          for u in actual.get('usb_devices', []))
        connected = active and controls and actual.get('sidecar_connected')
        state = (tr('狀態未知') if not fresh else tr('已連線') if connected else
                 tr('偵測到 Sidecar 目標') if available else tr('僅偵測到 USB') if usb_present else
                 tr('狀態未知') if errors else tr('未偵測到'))
        item(tr('{0} — {1}', p.get('name') or tr('未命名 iPad'), state) + (tr('｜目前控制目標') if active else ''), 1, checked=active)
        device_details(p)
        key = pairing_key(p)
        item(tr('設為控制目標…'), 2, ('gui', 'wizard', '--select', key), enabled=not active)
        item(tr('刪除配對'), 2, ('gui', 'wizard', '--delete', key))
    separator(1)
    item(tr('虛擬備援'), 1)
    virtual_state = (tr('狀態未知') if not fresh or errors.get('identifiers') else
                     tr('已連接') if actual.get('virtual_display_connected') else
                     tr('已配置') if actual.get('virtual_display_exists') else tr('未配置'))
    item(f"◻️ {config.get('virtual_display_name') or details.get('virtual_display_name', 'PadPilotVirtual')} — {virtual_state}", 1)

    item(tr('iPad 控制'))
    item((tr('自動偵測目標：') if auto_detect else tr('目前目標：')) + (target.get('name') or tr('尚無目標')), 1)
    if not controls:
        item(tr('請接上唯一 iPad 並等待最新背景狀態') if auto_detect else tr('請先配對並取得最新背景狀態'), 1)
    for title, action in ((tr('作為副螢幕'), 'use_ipad_secondary'), (tr('設為主螢幕'), 'use_ipad_main'),
                          (tr('中斷連線'), 'disconnect_ipad'), (tr('重新連線'), 'reconnect_sidecar')):
        item(title, 1, ('action', action), enabled=controls)
    item(tr('運作模式'))
    for value, title in MODES.items():
        title = tr(title)
        item(title, 1, ('set-mode', value), checked=mode == value)
    item(tr('背景服務'))
    item(tr('登入時自動啟動'), 1, ('autostart', 'toggle'), checked=autostart)
    if service_running is True:
        item(tr('服務狀態：執行中'), 1)
        item(tr('停止背景服務（保留選單）'), 1, ('stop',))
    elif service_running is False:
        item(tr('服務狀態：已停止'), 1)
        item(tr('啟動背景服務'), 1, ('start',))
    else:
        item(tr('服務狀態：無法確認'), 1)
    separator()
    item('🌐 Language')
    active_lang = config.get('language') or 'zh-Hant'
    for lang_code, lang_name in LANGUAGES.items():
        item(lang_name, 1, ('set-language', lang_code), checked=active_lang == lang_code)
    item(tr('設定與配對'), args=('gui',))
    item(tr('狀態與診斷'), args=('gui', 'diagnostics'))
    separator()
    item(tr('重新整理螢幕狀態'), args=('action', 'refresh'))
    separator()
    item(tr('Exit'), args=('exit',))



def main() -> None:
    # SwiftBar hides a standard plugin when it exits successfully with no output.
    if (APP_SUPPORT / 'menu-hidden').exists() or Path('/tmp/PadPilot/menu-hidden').exists():
        return
    config = load_json(APP_SUPPORT / 'config.json', Path('/tmp/PadPilot/config.json'))
    try:
        service_running = bool(daemon_pids())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        service_running = None
    render(load_status(), config, PLIST_PATH.is_file(), service_running=service_running)


if __name__ == '__main__':
    main()
