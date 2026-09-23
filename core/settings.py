"""Validated settings changes shared by the daemon and offline CLI."""
from core.betterdisplay import BetterDisplayCLI
from core.config import Config, validate_connection_hotkey
from core.detector import DisplayDetector
from core.models import OperationMode
from uuid import UUID


class ConflictError(Exception):
    """Raised when expected_revision does not match current configuration revision."""
    pass


def is_virtual_device(device: dict) -> bool:
    return device.get('deviceType') == 'VirtualScreen' or str(device.get('vendor')) == '2198'


def apply_change(cfg: Config, action: str, payload: dict, bd=None) -> bool:
    """Return whether the state engine needs to re-evaluate its target."""
    if not isinstance(payload, dict):
        raise ValueError('無效的設定資料')
    if action == 'set_connection_hotkey':
        if set(payload) != {'shortcut'}:
            raise ValueError('Invalid connection hotkey')
        cfg.connection_hotkey = validate_connection_hotkey(payload['shortcut'])
        return False  # Register in the menu app; never initiate a display transition.
    if action == 'set_language':
        if set(payload) != {'language'} or payload['language'] not in ('zh-Hant', 'en', 'ja'):
            raise ValueError('Unsupported language')
        cfg.language = payload['language']
        return False  # Presentation only; never re-evaluate display connections.
    if action in ('set_usb_event_wakeup', 'set_auto_detect_ipad', 'set_connect_on_boot'):
        if set(payload) != {'enabled'} or type(payload['enabled']) is not bool:
            raise ValueError('請提供布林值 enabled')
        if action == 'set_connect_on_boot' and payload['enabled'] and not cfg.autostart_on_login:
            raise ValueError('開機連線需要啟用登入時自動啟動；請透過 sidecarswitch-cli change-settings set_connect_on_boot 設定。')
        field = action.removeprefix('set_')
        changed = getattr(cfg, field) != payload['enabled']
        setattr(cfg, field, payload['enabled'])
        return changed and action != 'set_connect_on_boot'
    if action == 'set_mode':
        mode_val = payload.get('mode')
        if not isinstance(mode_val, str):
            raise ValueError('無效的模式設定')
        try:
            mode = OperationMode(mode_val.lower())
        except ValueError:
            raise ValueError(f'無效的模式: {mode_val}')
        changed = cfg.mode != mode
        cfg.mode = mode
        return changed
    if action == 'set_autostart':
        raise ValueError('請透過 sidecarswitch-cli autostart 變更登入服務與連動設定。')
    if action == 'save_pairing':
        if set(payload) != {'ipad', 'activate'} or type(payload['activate']) is not bool:
            raise ValueError('無效的配對命令')
        return cfg.remember_ipad(payload['ipad'], payload['activate'])
    if action == 'delete_pairing':
        if set(payload) != {'key'} or not isinstance(payload['key'], str):
            raise ValueError('無效的刪除命令')
        return cfg.forget_ipad(payload['key'])
    if action == 'set_virtual_display':
        name = payload.get('name')
        if set(payload) != {'name'} or not isinstance(name, str) or not name.strip() or len(name) > 256 or any(ord(c) < 32 for c in name):
            raise ValueError('無效的虛擬螢幕名稱')
        devices = bd.get_display_identifiers()
        if getattr(bd, 'identifiers_error', ''):
            raise ValueError('無法確認螢幕清單，設定未變更。')
        matches = [d for d in devices if str(d.get('name', '')).casefold() == name.casefold()]
        if len(matches) != 1 or not is_virtual_device(matches[0]):
            raise ValueError('請選擇可確認且名稱唯一的 BetterDisplay 虛擬螢幕。')
        # Existing controls use -namelike, so reject names matching another screen too.
        if any(d is not matches[0] and name.casefold() in str(d.get('name', '')).casefold() for d in devices):
            raise ValueError('名稱也符合其他螢幕，請先在 BetterDisplay 設定唯一名稱。')
        changed = cfg.virtual_display_name != name
        cfg.virtual_display_name = name
        return changed
    if action == 'set_display_exclusion':
        if (set(payload) != {'uuid', 'excluded'} or not isinstance(payload['uuid'], str)
                or (payload['excluded'] is not None and type(payload['excluded']) is not bool)):
            raise ValueError('無效的螢幕排除設定')
        try:
            key = str(UUID(payload['uuid'])).upper()
        except ValueError as error:
            raise ValueError('無效的螢幕排除設定') from error
        detector = DisplayDetector(cfg, bd)
        displays = detector.get_online_displays()
        if detector.display_error or getattr(bd, 'identifiers_error', ''):
            raise ValueError('無法確認螢幕清單，設定未變更。')
        matches = [d for d in displays if (d.uuid or '').upper() == key]
        if len(matches) != 1:
            raise ValueError('螢幕已離線或識別不唯一，請重新整理。')
        if matches[0].is_sidecar or matches[0].is_virtual:
            raise ValueError('Sidecar 與虛擬螢幕不計入實體螢幕判斷。')
        previous = cfg.display_exclusions.get(key)
        if payload['excluded'] is None:
            cfg.display_exclusions.pop(key, None)
        else:
            cfg.display_exclusions[key] = payload['excluded']
        return previous != payload['excluded']
    if action == 'set_betterdisplaycli_path':
        if 'path' not in payload:
            raise ValueError('無效的設定資料')
        path = payload['path']
        if path is not None and not isinstance(path, str):
            raise ValueError('無效的路徑設定')
        if isinstance(path, str):
            path = path.strip()
            if not path:
                path = None
        if path is not None:
            resolved = BetterDisplayCLI.resolve_cli_path(path)
            if not resolved:
                raise ValueError(f'指定路徑不存在或無執行權限: {path}')
            path = resolved
        changed = cfg.betterdisplaycli_path != path
        cfg.betterdisplaycli_path = path
        return changed
    raise ValueError('不支援的設定操作')
