#!/usr/bin/env python3
"""Render and exercise the real Swift settings window using isolated fixtures."""
import argparse
import json
import platform
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def fixtures():
    from core.config import Config
    from core.gui import build_gui_payload
    from core.i18n import LANGUAGES, set_language
    from core.models import pairing_key

    one = {'name': 'My iPad', 'sidecar_uuid': '11111111-1111-4111-8111-111111111111', 'usb_serial': 'USB123'}
    two = dict(one, name='Other iPad', sidecar_uuid='22222222-2222-4222-8222-222222222222', usb_serial='USB456')
    cfg = Config.from_dict({'revision': 7, 'auto_detect_ipad': False, 'ipad': one, 'paired_ipads': [one, two]})
    view = {'config': cfg, 'config_error': '', 'fresh': True, 'scanned': True,
            'status_revision': 8, 'config_revision': 7, 'status_config_revision': 7,
            'consistency_state': 'CONSISTENT', 'hardware_snapshot_age': 1,
            'actual': {'timestamp': 100, 'sidecar_connected': True, 'sidecar_display_online': True,
                       'sidecar_devices': [{'uuid': one['sidecar_uuid'], 'name': 'My iPad'},
                                           {'uuid': '33333333-3333-4333-8333-333333333333', 'name': 'New iPad'}],
                       'usb_devices': [{'serial': 'USB123', 'product_name': 'My iPad'},
                                       {'serial': 'USB456', 'product_name': 'Other iPad'}],
                       'online_displays': [{'name': 'Display', 'width': 1920, 'height': 1080, 'is_main': True},
                                           {'name': 'iPad', 'width': 1920, 'height': 1080, 'is_sidecar': True}],
                       'discovery_errors': {}},
            'identifiers': [{'name': 'PadPilotVirtual', 'deviceType': 'VirtualScreen', 'displayID': '7'}],
            'status': {'runtime': {'transition_state': 'IDLE'},
                       'desired': {'target_display_role': 'IPAD_SECONDARY', 'reason': 'User Override active: Use iPad as Secondary (Topology Gen 0).'}}}
    result = {}
    with patch('core.gui.read_view', return_value=view), \
         patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value='/Applications/BetterDisplay.app/Contents/MacOS/BetterDisplay'), \
         patch('core.diagnostics.collect_system_checks', return_value=[('macOS 自動登入', '已停用'), ('FileVault', '已開啟'),
                                                                      ('BetterDisplay 控制介面', '未啟用')]), \
         patch('core.diagnostics.collect_authenticated_checks', return_value=[('BetterDisplay 登入啟動', '尚未驗證')]):
        for language in LANGUAGES:
            cfg.language = language
            payload = build_gui_payload(diagnostics=True, admin_checks=True)
            payload['logs'] = '\n'.join([
                '2026-09-11 10:00:00 [INFO] [test] information',
                '2026-09-11 10:00:01 [WARNING] [test] warning',
                '2026-09-11 10:00:02 [ERROR] [test] error',
                'unstructured [INFO] text is only visible in all',
            ])
            payload['fixture_target_key'] = pairing_key(one)
            result[language] = payload
    set_language('zh-Hant')
    return result


def run_check(mode='layout', output=None):
    if sys.platform != 'darwin':
        raise RuntimeError('Native GUI checks require a macOS desktop session.')
    with tempfile.TemporaryDirectory(prefix='padpilot-native-gui-') as directory:
        root = Path(directory)
        fixture_path = root / 'fixtures.json'
        fixture_path.write_text(json.dumps(fixtures(), ensure_ascii=False), encoding='utf-8')
        output = Path(output).resolve() if output else root / 'accessibility-reports'
        output.mkdir(parents=True, exist_ok=True)
        main = root / 'main.swift'
        main.write_text('''import AppKit
import Foundation
struct Runtime: Decodable { let python: String; let project_root: String }
let application = NSApplication.shared
application.setActivationPolicy(.regular)
Task { @MainActor in
do {
    let fixtures = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: [String: Any]]
    try await runSettingsChecks(runtime: Runtime(python: "/usr/bin/false", project_root: CommandLine.arguments[2]),
                          fixtures: fixtures, mode: CommandLine.arguments[3],
                          output: URL(fileURLWithPath: CommandLine.arguments[4]))
} catch {
    FileHandle.standardError.write(Data("FAIL: \\(error)\\n".utf8))
    exit(1)
}
exit(0)
}
application.run()
''', encoding='utf-8')
        contents = root / 'SettingsChecks.app/Contents'
        (contents / 'MacOS').mkdir(parents=True)
        (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.settings-checks', 'CFBundleName': 'PadPilot Settings Checks', 'CFBundleExecutable': 'SettingsChecks', 'CFBundlePackageType': 'APPL', 'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True}))
        executable = contents / 'MacOS/SettingsChecks'
        subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-D', 'PADPILOT_GUI_CHECKS',
                        '-target', f'{platform.machine()}-apple-macosx14.0',
                        '-module-cache-path', str(ROOT / 'build/swift-cache'),
                        str(ROOT / 'native/Settings.swift'), str(ROOT / 'native/SettingsChecks.swift'),
                        str(main), '-o', str(executable)], check=True)
        subprocess.run([str(executable), str(fixture_path), str(ROOT), mode, str(output)], check=True, timeout=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Keep native accessibility reports in this directory.')
    args = parser.parse_args()
    run_check('layout', args.output)


if __name__ == '__main__':
    main()
