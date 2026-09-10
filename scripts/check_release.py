#!/usr/bin/env python3
"""Local Early Preview gates. Does not publish, tag, rewrite history or control displays."""
import argparse
import datetime
import json
import platform
import plistlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import __version__

PATTERNS = {
    'credential': re.compile(r'AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'private_path': re.compile(r'/Users/(?!example/|test/)[\w.-]+/'),
    'lan_address': re.compile(r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b'),
    'device_serial': re.compile(r'\b(?:00008[0-9a-fA-F]{19,35}|00008[0-9a-fA-F]{3}-[0-9a-fA-F]{16})\b'),
}


def privacy_kinds(text):
    return [kind for kind, pattern in PATTERNS.items() if pattern.search(text)]


def scan_privacy():
    """Targeted text scan, not proof that every possible secret has been found."""
    tree = []
    names = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z'], cwd=ROOT).split(b'\0')
    for name in set(names):
        if not name:
            continue
        path = name.decode()
        try:
            data = (ROOT / path).read_bytes()
        except OSError:
            continue
        if b'\0' in data:
            continue
        for line_number, line in enumerate(data.decode('utf-8', errors='replace').splitlines(), 1):
            for kind in privacy_kinds(line):
                tree.append({'kind': kind, 'path': path, 'line': line_number})
    history = set()
    patches = subprocess.check_output(['git', 'log', '--all', '--format=COMMIT %H', '--patch',
                                       '--no-ext-diff', '--no-color'], cwd=ROOT).decode('utf-8', errors='replace')
    commit, path = '', ''
    for line in patches.splitlines():
        if line.startswith('COMMIT '):
            commit = line[7:]
        elif line.startswith('+++ b/'):
            path = line[6:]
        elif line.startswith('--- a/'):
            path = line[6:]
        elif line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
            for kind in privacy_kinds(line[1:]):
                history.add((kind, commit, path))
    return {'scanner': 'targeted text patterns; review findings manually; values are never included',
            'tree': tree, 'history': [dict(kind=k, commit=c, path=p) for k, c, p in sorted(history)]}


def check_versions():
    for name in ('README.md', 'README.en.md'):
        assert f'version-{__version__}-' in (ROOT / name).read_text(), f'{name}: version mismatch'
        assert 'early%20preview' in (ROOT / name).read_text(), f'{name}: Early Preview warning missing'
    assert f'## [{__version__}]' in (ROOT / 'CHANGELOG.md').read_text(), 'CHANGELOG version mismatch'
    from core.autostart import generate_plist_content
    expected = plistlib.loads(generate_plist_content().encode())
    source = (ROOT / 'launchd/com.padpilot.daemon.plist.in').read_text()
    from xml.sax.saxutils import escape
    for key, value in {'__PYTHON_BIN__': sys.executable, '__PROJECT_ROOT__': str(ROOT),
                       '__LOG_DIR__': str(Path.home() / 'Library/Logs/PadPilot')}.items():
        source = source.replace(key, escape(value))
    assert plistlib.loads(source.encode()) == expected, 'LaunchAgent template and shared generator differ'
    installed_build = ROOT / 'build/PadPilot.app/Contents/Info.plist'
    if installed_build.exists():
        info = plistlib.loads(installed_build.read_bytes())
        assert info['CFBundleShortVersionString'] == __version__, 'App version mismatch; rebuild first'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gui', action='store_true', help='Run real Tk layout/language gates on a desktop session')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--scan-only', action='store_true')
    mode.add_argument('--software-only', action='store_true',
                      help='Gate only software checks; privacy is reported but requires a separate release gate')
    args = parser.parse_args()
    output = ROOT / 'build'
    output.mkdir(exist_ok=True)
    privacy = scan_privacy()
    (output / 'privacy-scan.json').write_text(json.dumps(privacy, indent=2), encoding='utf-8')
    print(f'Privacy review: tree={len(privacy["tree"])}, history={len(privacy["history"])}; see build/privacy-scan.json (values redacted)')
    if args.scan_only:
        return 1 if privacy['tree'] or privacy['history'] else 0
    report = {'version': __version__, 'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'python': platform.python_version(), 'macOS': platform.mac_ver()[0], 'architecture': platform.machine(),
              'checks': {}, 'gui': 'not_run', 'physical_acceptance': 'unknown',
              'minimum_python_runtime': 'not_run' if sys.version_info[:2] != (3, 10) else 'current_runtime',
              'github': 'not_checked', 'stable_ready': False,
              'gate': 'software_only' if args.software_only else 'release'}
    commands = [('unit_tests', [sys.executable, '-W', 'always::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests']),
                ('shell_syntax', ['bash', '-n', 'scripts/install.sh', 'scripts/uninstall.sh']),
                ('diff', ['git', 'diff', '--check']),
                ('plist_lint', ['plutil', '-lint', 'launchd/com.padpilot.daemon.plist.in'])]
    if args.gui:
        commands += [('gui_layout', [sys.executable, 'scripts/check_gui_layout.py']),
                     ('gui_languages', [sys.executable, 'scripts/check_gui_languages.py'])]
    for name, command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        log = result.stdout + result.stderr
        (output / f'release-{name}.log').write_text(log, encoding='utf-8')
        ok = result.returncode == 0 and 'ResourceWarning' not in log
        report['checks'][name] = 'pass' if ok else 'fail'
        print(f'{"PASS" if ok else "FAIL"}: {name}')
    try:
        check_versions()
        report['checks']['versions'] = 'pass'
    except (AssertionError, OSError, ValueError) as error:
        report['checks']['versions'] = 'fail'
        print(f'FAIL: versions: {error}')
    if args.gui:
        report['gui'] = 'pass' if all(report['checks'][k] == 'pass' for k in ('gui_layout', 'gui_languages')) else 'fail'
    report['privacy'] = 'review_required' if privacy['tree'] or privacy['history'] else 'no_pattern_matches'
    (output / 'release-check.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Stable gate remains closed until physical acceptance and the supported-version matrix are verified.')
    if args.software_only:
        print('Software-only result is not a release approval; the separate privacy gate remains required.')
    return 0 if all(v == 'pass' for v in report['checks'].values()) and (args.software_only or report['privacy'] != 'review_required') else 1


if __name__ == '__main__':
    sys.exit(main())
