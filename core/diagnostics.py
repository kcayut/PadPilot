"""Read-only startup checks; inaccessible system settings remain unknown."""
import os
import plistlib
import re
import subprocess
from pathlib import Path

from core.autostart import get_launch_agent_plist_path, is_daemon_running
from core.betterdisplay import BetterDisplayCLI


def read_plist(path):
    try:
        with Path(path).open('rb') as stream:
            return plistlib.load(stream)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None


def command(args, timeout=5):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def betterdisplay_login_status(output, uid):
    if output is None:
        return '未知（系統查詢逾時或無權限）'
    sections = re.split(r'(?m)^.*Records for UID (\d+).*$', output)
    records = next((sections[i + 1] for i in range(1, len(sections), 2)
                    if sections[i] == str(uid)), None)
    if records is None:
        return '未知（未取得目前使用者的登入項目）'
    matches = [block for block in re.split(r'(?m)^\s*#\d+:', records)
               if re.search(r'Bundle Identifier:\s*pro\.betterdisplay\.BetterDisplay\s*$', block, re.M)]
    if not matches:
        return '未登錄（請到系統設定 → 一般 → 登入項目確認）'
    states = []
    for block in matches:
        disposition = re.search(r'Disposition:\s*\[([^]]+)\]', block)
        states.append(set(v.strip() for v in disposition[1].split(',')) if disposition else set())
    if any({'enabled', 'allowed'} <= state for state in states):
        return '已啟用'
    if all('disabled' in state for state in states):
        return '未啟用'
    return '未知／受系統限制（請檢查登入項目）'


def collect_system_checks(cfg, actual):
    plist = get_launch_agent_plist_path()
    agent = read_plist(plist)
    if not plist.exists():
        startup = '未設定'
    elif agent is None:
        startup = '未知（無法讀取啟動設定）'
    else:
        enabled = bool(agent.get('RunAtLoad') or agent.get('KeepAlive')) and not agent.get('Disabled', False)
        startup = '已設定（登入後啟用）' if enabled else '未啟用'
        args = agent.get('ProgramArguments') or []
        if not args or not all(Path(p).exists() for p in args[:2]):
            startup = '設定異常（執行檔或程式路徑不存在）'
    applications = [Path('/Applications/BetterDisplay.app'), Path.home() / 'Applications/BetterDisplay.app']
    installed = any(p.is_dir() for p in applications)
    login = read_plist('/Library/Preferences/com.apple.loginwindow.plist')
    automatic = ('未知（無法讀取系統設定）' if login is None else
                 '已設定：' + str(login['autoLoginUser']) if login.get('autoLoginUser') else '未設定')
    vault = command(['/usr/bin/fdesetup', 'status'])
    vault_state = ('已開啟；重新開機後需先解鎖磁碟' if vault and 'FileVault is On' in vault else
                   '未開啟' if vault and 'FileVault is Off' in vault else '未知（無法查詢）')
    checks = [
        ('PadPilot 登入啟動', startup),
        ('背景服務', '執行中' if is_daemon_running() else '未回應／尚未啟動'),
        ('BetterDisplay 安裝', '已安裝' if installed else '未在標準應用程式位置找到'),
        ('BetterDisplay 控制介面', '可用' if BetterDisplayCLI.resolve_cli_path(cfg.betterdisplaycli_path) else '未找到'),
        ('macOS 自動登入', automatic),
        ('FileVault', vault_state),
        ('虛擬備援螢幕', '未知（識別查詢失敗）' if actual.get('discovery_errors', {}).get('identifiers') else
         '已設定' if actual.get('virtual_display_exists') else '未找到：' + cfg.virtual_display_name),
        ('Sidecar 配對', '已設定 UUID' if cfg.ipad.sidecar_uuid else '尚未配對'),
        ('需人工確認', 'Mac 與 iPad 使用相同 Apple Account、雙重認證、Wi-Fi／藍牙／接力與信任此電腦。'),
        ('滑鼠與鍵盤', '若游標跑進 iPad 原生畫面，請在顯示器 → 進階關閉通用控制的跨裝置移動。'),
    ]
    return checks


def collect_authenticated_checks():
    """Only called by the explicit authentication-card refresh button.

    macOS may ask for authorization while accessing background login items.
    Credentials are handled by macOS, never collected by PadPilot.
    """
    output = command(['/usr/bin/sfltool', 'dumpbtm'], timeout=120)
    return [('BetterDisplay 登入啟動', betterdisplay_login_status(output, os.getuid()))]
