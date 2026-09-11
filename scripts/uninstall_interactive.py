#!/usr/bin/env python3
"""Preview all uninstall choices before stopping or removing anything."""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from setup_state import read_receipt, write_receipt

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = {'python@3.14': 'formula', 'betterdisplay': 'cask'}


def ask(question):
    while True:
        answer = input(f'{question} [y/N, q = 取消/cancel]: ').strip().lower()
        if answer in ('q', 'quit', 'cancel', '取消'):
            raise KeyboardInterrupt
        if answer in ('y', 'yes'):
            return True
        if answer in ('', 'n', 'no'):
            return False
        print('請輸入 y 或 n；輸入 q 取消。 / Enter y or n; q cancels the uninstall.')


def preflight_dependencies(dependencies):
    selected = {item['name'] for item in dependencies}
    installed = []
    for item in dependencies:
        brew = Path(item['brew'])
        if not brew.is_absolute() or brew.name != 'brew' or not brew.is_file() or not os.access(brew, os.X_OK):
            raise RuntimeError(f"Homebrew 路徑無效，請保留 / Invalid Homebrew path; keep {item['name']}: {brew}")
        result = subprocess.run([str(brew), 'list', f"--{item['kind']}", '--versions'],
                                check=True, capture_output=True, text=True)
        if item['name'] not in {line.split()[0] for line in result.stdout.splitlines() if line.strip()}:
            print(f"{item['name']} 未安裝，略過。 / Not installed in this Homebrew; skipping.")
            continue
        installed.append(item)
        if item['kind'] == 'formula':
            result = subprocess.run([str(brew), 'uses', '--installed', '--recursive', item['name']],
                                    check=True, capture_output=True, text=True)
            shared = set(result.stdout.split()) - selected
            if shared:
                raise RuntimeError(f"{item['name']} 已由其他套件共用，請保留 / Shared dependency; keep it: {', '.join(sorted(shared))}")
    return installed


def main(argv=None):
    parser = argparse.ArgumentParser(description='預覽 PadPilot 解除安裝；所有資料預設保留。 / Preview uninstall; preserve user data by default.')
    parser.add_argument('--yes', '-y', action='store_true', help='略過互動 / Apply explicit options without prompting')
    parser.add_argument('--purge', action='store_true', help='移除設定、配對與日誌 / Remove settings, pairing and logs')
    parser.add_argument('--remove-config', action='store_true', help='移除設定與配對 / Remove settings and pairing')
    parser.add_argument('--remove-logs', action='store_true', help='移除日誌 / Remove logs')
    parser.add_argument('--remove-source', action='store_true', help='移除受管來源 / Remove bootstrap-managed source')
    parser.add_argument('--remove-dependency', action='append', default=[], metavar='NAME',
                        help='指定依賴，可重複 / Remove a recorded dependency; repeatable')
    parser.add_argument('--allow-display-disconnect', action='store_true', help='確認可能中斷唯一螢幕 / Accept losing the only display')
    args = parser.parse_args(argv)
    if not args.yes and not sys.stdin.isatty():
        parser.error('沒有互動終端；未做變更。 / No interactive terminal. Use --yes with explicit options; nothing changed.')
    try:
        receipt = read_receipt(ROOT)
        source_path = Path.home() / 'Applications/PadPilot-source'
        managed_source = (receipt.get('managed_source') is True and not source_path.is_symlink()
                          and ROOT == source_path.resolve())
        available = {item['name']: item for item in receipt['dependencies']
                     if DEPENDENCIES.get(item['name']) == item['kind']}
        selected = set(args.remove_dependency)
        if selected - available.keys():
            parser.error('僅能移除安裝紀錄中的依賴 / Only recorded dependencies can be removed: '
                         + (', '.join(sorted(available)) or '無 / none'))
        if args.remove_source and not managed_source:
            parser.error('此來源目錄不受安裝器管理，請手動處理。 / Unmanaged source; remove it manually after uninstall.')
        remove_config = args.purge or args.remove_config
        remove_logs = args.purge or args.remove_logs
        remove_source = args.remove_source
        print('PadPilot 解除安裝 / Uninstall\n移除 App、登入啟動與本專案快捷；個人資料與依賴預設保留。')
        print('Remove the app, login startup and owned shortcuts. User data and dependencies are kept by default.')
        if not args.yes:
            if not remove_config:
                remove_config = ask('將設定與 iPad 配對移到垃圾桶？ / Trash settings and iPad pairing?')
            if not remove_logs:
                remove_logs = ask('將日誌移到垃圾桶？ / Trash PadPilot logs?')
            if managed_source and not remove_source:
                remove_source = ask(f'將一鍵安裝來源移到垃圾桶？ / Trash managed source ({ROOT})?')
            for name in sorted(available):
                if name not in selected and ask(f'卸除安裝器新增的 {name}？其他軟體可能需要它。 / Remove {name}? Other software may need it.'):
                    selected.add(name)
        if 'betterdisplay' in selected:
            print('移除 BetterDisplay 可能立即移除虛擬螢幕；若它是唯一畫面，請先接上實體螢幕或確認遠端復原方式。')
            print('Removing BetterDisplay can disconnect your only display. Connect a physical monitor or verify remote recovery first.')
            if not args.allow_display_disconnect:
                if args.yes:
                    parser.error('移除 BetterDisplay 需要 / Removing BetterDisplay also requires --allow-display-disconnect.')
                if not ask('可接受失去 BetterDisplay 虛擬螢幕，仍要卸除？ / Accept display disconnection and remove BetterDisplay?'):
                    selected.remove('betterdisplay')
        dependencies = [available[name] for name in sorted(selected, key=lambda name: (name.startswith('python@'), name))]
        dependencies = preflight_dependencies(dependencies)
        missing = selected - {item['name'] for item in dependencies}
        print('\n即將執行 / Uninstall preview:\n  • 停止 PadPilot、移除 App 與整合 / Stop PadPilot; trash its app and integrations')
        for label, enabled in (('設定與配對 / Settings & pairing', remove_config), ('日誌 / Logs', remove_logs),
                               (f'來源目錄 / Source ({ROOT})', remove_source)):
            print(f"  • {label}: {'移到垃圾桶 / Trash' if enabled else '保留 / Keep'}")
        for name in sorted(available):
            action = ('未安裝 / Not installed' if name in missing else
                      'Homebrew 卸除，無法從垃圾桶復原 / Uninstall, not recoverable from Trash' if name in selected else '保留 / Keep')
            print(f'  • {name}：{action}')
        print('  • Homebrew、系統 Python、Apple 開發工具及其他既有依賴：保留')
        print('  • Keep Homebrew, system Python, Apple developer tools and other existing dependencies')
        print('  • 保留 BetterDisplay 時，也會保留其虛擬螢幕設定')
        print('  • Keeping BetterDisplay also preserves its virtual display settings')
        if not args.yes and not ask('確認執行以上解除安裝？ / Apply this uninstall plan?'):
            print('已取消，未做任何變更。 / Cancelled; nothing changed.')
            return 0
        # Import only after confirmation: core.config initializes its state directory.
        from manage_app import manage, trash
        manage(uninstall=True, remove_config=remove_config, remove_logs=remove_logs)
        if missing:
            receipt['dependencies'] = [item for item in receipt['dependencies'] if item['name'] not in missing]
            write_receipt(ROOT, receipt)
        failures = []
        for item in dependencies:
            try:
                subprocess.run([item['brew'], 'uninstall', f"--{item['kind']}", item['name']], check=True,
                               env={**os.environ, 'HOMEBREW_NO_AUTOREMOVE': '1', 'HOMEBREW_NO_INSTALL_CLEANUP': '1'})
                receipt['dependencies'] = [entry for entry in receipt['dependencies'] if entry != item]
                write_receipt(ROOT, receipt)
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
                failures.append(item['name'])
                print(f"未能完整卸除或更新紀錄 / Removal or receipt update failed for {item['name']}: {error}", file=sys.stderr)
        if remove_source and not failures:
            trash(ROOT)
        elif remove_source:
            print(f'依賴卸除未完成，來源保留供重試 / Dependency removal incomplete; source kept for retry: {ROOT}')
        print('PadPilot 已解除安裝，垃圾桶中的資料仍可復原。 / PadPilot uninstalled; items in Trash can be restored.')
        return 1 if failures else 0
    except (EOFError, KeyboardInterrupt):
        print('\n已取消；確認前不做任何變更。 / Cancelled; no changes are made before confirmation.')
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'解除安裝未完成 / Uninstall incomplete: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
