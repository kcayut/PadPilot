"""Validated settings changes shared by the daemon and offline CLI."""
from core.config import Config


def is_virtual_device(device: dict) -> bool:
    return device.get('deviceType') == 'VirtualScreen' or str(device.get('vendor')) == '2198'


def apply_change(cfg: Config, action: str, payload: dict, bd=None) -> bool:
    """Return whether the state engine needs to re-evaluate its target."""
    if not isinstance(payload, dict):
        raise ValueError('無效的設定資料')
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
    raise ValueError('不支援的設定操作')
