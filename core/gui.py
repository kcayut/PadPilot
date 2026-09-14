"""Read-only presentation data and launcher for the native Swift settings window."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from core import __revision__, __version__
from core.betterdisplay import BetterDisplayCLI
from core.config import Config, get_config_file_path, get_status_file_path, read_status
from core.detector import DisplayDetector
from core.logger import get_log_file_path
from core.i18n import LANGUAGES, LANGUAGE_CODES, TRANSLATIONS, set_language, tr, tr_message
from core.models import OperationMode, pairing_key
from core.settings import is_virtual_device
from core.storage import read_private_json, UnsafePathError

ROOT = Path(__file__).resolve().parents[1]
GITHUB_URL = 'https://github.com/kcayut/PadPilot'
DONATION_URLS = {
    'PayPal': 'https://www.paypal.com/paypalme/oilstuck',
    'Ko-fi': 'https://ko-fi.com/kcayut',
}

GREEN = '#34c759'
ORANGE = '#ff9500'
RED = '#ff3b30'

MODES = {
    'manual_only': '僅手動模式',
    'automatic': '自動模式',
    'prefer_ipad': '偏好 iPad 模式'
}
MODE_DESCS = {
    'automatic': '無實體螢幕時自動連線 iPad 並設為主螢幕；有實體螢幕時以實體為主，已連線的 iPad 保持為副螢幕。',
    'manual_only': '平時只接受選單或全域快速鍵的手動要求；斷線後不自行重連。可另外啟用開機時的一次連線。',
    'prefer_ipad': '即使已接上實體螢幕，依然優先連線 iPad 並將其作為主要顯示器。'
}

def get_documentation_ref() -> str:
    if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', __revision__):
        return __revision__
    if (ROOT / '.git').exists():
        try:
            result = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'],
                                    capture_output=True, text=True, check=True, timeout=2)
            revision = result.stdout.strip()
            if re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', revision):
                return revision
        except (OSError, subprocess.SubprocessError):
            pass
    return f'v{__version__}'


# Keep links tied to the source loaded by this GUI, even if the checkout updates.
DOCUMENTATION_REF = get_documentation_ref()


def get_documentation_url(path: str, language: str) -> str:
    source = Path(path)
    suffix = {'zh-Hant': '', 'en': '.en', 'ja': '.ja'}.get(language, '.en')
    localized = source.with_name(f'{source.stem}{suffix}{source.suffix}').as_posix()
    return f'{GITHUB_URL}/blob/{quote(DOCUMENTATION_REF, safe="")}/{quote(localized)}'


def get_troubleshooting_url(label: str, language: str = 'zh-Hant') -> str:
    url = get_documentation_url('docs/TROUBLESHOOTING.md', language)
    lbl = (label or '').lower()
    if 'filevault' in lbl or '自動登入' in lbl:
        return f'{url}#filevault'
    if 'betterdisplay' in lbl:
        return f'{url}#betterdisplay'
    if '登入啟動' in lbl or '背景服務' in lbl:
        return f'{url}#autostart'
    if 'sidecar' in lbl:
        return f'{url}#sidecar-session'
    return url


def short_id(value: str) -> str:
    return value[:8] + '…' + value[-6:] if len(value) > 20 else value or tr('未設定')


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


def get_check_light(label: str, value: str) -> tuple[str, str]:
    """Determine the check indicator status and light color.

    Returns:
        tuple[str, str]: (status_type, hex_color)
        status_type is one of 'pass', 'fail', 'pending'.
    """
    val = (value or '').strip()
    lbl = (label or '').strip()

    # Explicit pending / unverified / manual checks / hints
    if any(k in val for k in ('尚未檢查', '尚未驗證', '未知', '評估中', '待確認')) or \
       any(k in lbl for k in ('人工確認', '滑鼠與鍵盤', '注意', '提示')):
        return 'pending', ORANGE

    # These two checks describe unattended startup display readiness.
    if lbl == 'FileVault' or lbl == 'macOS 自動登入':
        if ((lbl == 'FileVault' and val == '未開啟') or
                (lbl == 'macOS 自動登入' and (val == '已啟用' or val.startswith('已設定：')))):
            return 'pass', GREEN
        if ((lbl == 'FileVault' and (val == '已開啟' or val.startswith('已開啟；'))) or
                (lbl == 'macOS 自動登入' and val in ('未設定', '已停用', '未啟用'))):
            return 'fail', RED
        return 'pending', ORANGE

    # Explicit failure cases
    if any(k in val for k in ('未設定', '未啟用', '未回應', '未找到', '未在標準', '尚未配對', '未登錄', '設定異常', '不通過', '失敗', '錯誤')) or \
       any(k in val.lower() for k in ('fail', 'error', 'disabled')):
        return 'fail', RED

    # Explicit pass cases
    if any(k in val for k in ('已設定', '執行中', '已安裝', '可用', '已啟用', '通過', '正常', '已連線')) or \
       any(k in val.lower() for k in ('pass', 'ok', 'running', 'enabled', 'connected')):
        return 'pass', GREEN

    return 'pending', ORANGE


def read_view(scan: bool = False) -> dict:
    """Read-only view of configuration and hardware status."""
    cfg = Config()
    config_error = ''
    try:
        path = get_config_file_path()
        if path.exists():
            cfg = Config.from_dict(read_private_json(path))
    except (OSError, ValueError, TypeError, UnsafePathError):
        cfg = Config(mode=OperationMode.MANUAL_ONLY, auto_detect_ipad=False, autostart_on_login=False)
        config_error = tr('設定檔無法讀取；請修復或還原原檔。此視窗已停用設定儲存與控制。')
    status = read_status() or {}
    actual = status.get('actual', {})
    stamp = actual.get('timestamp', 0)
    fresh = isinstance(stamp, (int, float)) and 0 <= time.time() - stamp <= 120
    identifiers = []
    if scan and not config_error:
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
        'config_error': config_error,
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
    target = (actual.get('resolved_ipad') or {}) if cfg.auto_detect_ipad else cfg.ipad.to_dict()
    if device.get('sidecar_uuid') and device.get('sidecar_uuid') == target.get('sidecar_uuid') and actual.get('sidecar_connected'):
        return '已連線'
    if any(device.get('sidecar_uuid') and d.get('uuid', '').upper() == device['sidecar_uuid'].upper()
           for d in actual.get('sidecar_devices', [])):
        return '已偵測到 Sidecar'
    if any(device.get('usb_serial') and u.get('serial') == device['usb_serial']
           for u in actual.get('usb_devices', [])):
        return '僅 USB 已接上'
    return '狀態未知' if actual.get('discovery_errors') else '未偵測到'


def send_change(action: str, payload: dict) -> str:
    from core.runtime import bundled_app
    result = subprocess.run(
        [sys.executable] + (['-I', '-B'] if bundled_app(ROOT) else [])
        + [str(ROOT / 'bin/padpilot-cli'), 'change-settings', action],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        capture_output=True,
        timeout=70
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or tr('設定更新失敗'))
    return result.stdout.strip()


def build_gui_payload(scan=False, diagnostics=False, admin_checks=False, logs=False) -> dict:
    """No polling request scans hardware, performs authentication, or reads logs implicitly."""
    view = read_view(scan=scan)
    cfg = view['config']
    set_language(cfg.language)
    actual = view['actual']
    status = view['status']
    desired, runtime, details = (status.get(key) or {} for key in ('desired', 'runtime', 'status_details'))
    target = pairing_key(cfg.ipad.to_dict())
    profiles = []
    for profile in cfg.paired_ipads:
        device = profile.to_dict()
        key = pairing_key(device)
        profiles.append(dict(device, key=key, status=tr(device_status(device, view)), status_key=device_status(device, view),
                             is_target=key == target,
                             can_control=key == target and bool(profile.sidecar_uuid) and not view['config_error']))
    consistency = view['consistency_state']
    satisfaction = details.get('actual_role_satisfied') or ('已滿足' if actual.get('sidecar_connected') else '評估中')
    reason = desired.get('reason') or details.get('reason') or '尚無背景決策資訊'
    role = desired.get('target_display_role') or details.get('desired_role') or '未知'
    if consistency == 'APPLYING_CONFIG':
        role, satisfaction, reason = '評估中', '切換中…', '套用新設定中…（等待背景服務評估）'
    elif consistency == 'REVISION_CONFLICT':
        role, satisfaction, reason = '未知', '不同步', '⚠️ 設定檔版本與背景服務狀態不一致，正在重新整理…'
    elif not view['fresh']:
        satisfaction = '資料待更新'
    cooldown = runtime.get('cooldown_until', 0)
    try:
        config_path = str(get_config_file_path())
    except (OSError, ValueError, UnsafePathError):
        config_path = ''
    payload = dict(view, config=cfg.to_dict(), schema_version=1,
        strings={key: tr(key) for key in TRANSLATIONS}, languages=LANGUAGES,
        profiles=profiles, candidates=actual.get('sidecar_devices', []), usbs=actual.get('usb_devices', []),
        virtuals=[device for device in view['identifiers'] if is_virtual_device(device)],
        paths={'config': config_path, 'log': str(get_log_file_path()),
               'betterdisplaycli': BetterDisplayCLI.resolve_cli_path(cfg.betterdisplaycli_path) or ''},
        links={'help': get_documentation_url('README.md', cfg.language),
               'troubleshooting': get_documentation_url('docs/TROUBLESHOOTING.md', cfg.language), 'github': GITHUB_URL},
        donations=DONATION_URLS, version=__version__,
        ui={'readonly': bool(view['config_error']), 'target_name': cfg.ipad.name or tr('未設定'),
            'mode_name': tr(MODES.get(cfg.mode.value, cfg.mode.value)),
            'mode_description': tr(MODE_DESCS.get(cfg.mode.value, ''))},
        decision={'role': tr_message(role), 'satisfaction': tr_message(satisfaction),
                  'reason': tr_message(reason), 'transition': runtime.get('transition_state') or 'IDLE',
                  'last_error': tr_message(runtime.get('last_error') or '無'),
                  'cooldown': isinstance(cooldown, (int, float)) and cooldown > time.time(), 'fresh': view['fresh']})
    from core.autostart import autostart_status
    payload['login_service_status'] = autostart_status()
    errors = [tr_message(value) for value in (actual.get('discovery_errors') or {}).values() if isinstance(value, str)]
    if errors:
        payload['notice'] = tr('部分狀態未知：') + '；'.join(errors)

    def checks(rows):
        result = []
        for label, value in rows:
            localizations = {}
            for language in LANGUAGES:
                set_language(language)
                localizations[language] = {'label': tr(label), 'value': tr_message(value),
                                           'help_url': get_troubleshooting_url(label, language)}
            result.append(dict(localizations[cfg.language], state=get_check_light(label, value)[0],
                               localizations=localizations))
        set_language(cfg.language)
        return result

    if diagnostics:
        from core.diagnostics import collect_system_checks
        payload['system_checks'] = checks(collect_system_checks(cfg, actual))
    if admin_checks:
        from core.diagnostics import collect_authenticated_checks
        payload['authenticated_checks'] = checks(collect_authenticated_checks())
    if logs:
        try:
            with get_log_file_path().open('rb') as stream:
                stream.seek(0, 2)
                size = stream.tell()
                stream.seek(max(0, size - 256 * 1024))
                if stream.tell():
                    stream.readline()  # Discard a partial first line of the bounded tail.
                payload['logs'] = '\n'.join(stream.read().decode('utf-8', errors='replace').splitlines()[-400:])
        except FileNotFoundError:
            payload['logs'] = tr('尚無日誌檔案。\n')
        except OSError as error:
            payload['logs'] = tr('無法讀取日誌：{0}\n', str(error))
    return payload


def run_gui(page='paired', delete=None, select=None):
    """Launch Services routes every request to the existing native app instance."""
    if delete is not None and select is not None:
        raise ValueError('Choose either delete or select, not both')
    from core.autostart import find_menu_app
    app = find_menu_app(settings=True)
    if app is None:
        raise RuntimeError('找不到此專案的 PadPilot.app；請先執行 scripts/install.sh 或 scripts/build_app.py。')
    if page == 'wizard':
        page = 'search'
    if page not in {'paired', 'search', 'settings', 'displays', 'virtual', 'diagnostics', 'about'}:
        raise ValueError('Unknown settings page')
    query = {'page': page}
    for key, value in (('delete', delete), ('select', select)):
        if value is not None:
            if not re.fullmatch('[0-9a-f]{64}', value):
                raise ValueError('Invalid profile key')
            query[key] = value
    subprocess.run(['/usr/bin/open', '-a', str(app), 'padpilot://settings?' + urlencode(query),
                    '--args', '--settings'], check=True, timeout=10)
