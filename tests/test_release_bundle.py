import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_release
import install_release
from core import autostart, gui, runtime
from core.storage import atomic_write


def bundle(path):
    contents = path / 'Contents'
    (contents / 'Resources/PadPilot/bin').mkdir(parents=True)
    (contents / 'Resources/Python/bin').mkdir(parents=True)
    (contents / 'Resources/Python/bin/python3').write_bytes(b'python-placeholder')
    (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.padpilot.app'}))
    (contents / 'Resources/runtime.json').write_text(json.dumps({
        'bundled': True, 'project_root': 'PadPilot', 'python': 'Python/bin/python3'}))
    return path


class ReleaseBundleTests(unittest.TestCase):
    def test_relocation_preserves_runtime_and_launch_agent_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = bundle(root / 'PadPilot.app')
            (root / 'Folder with spaces').mkdir()
            moved = root / 'Folder with spaces/PadPilot.app'
            app.rename(moved)
            project, python = runtime.app_runtime(moved)
            self.assertEqual(runtime.bundled_app(project), moved)
            self.assertEqual(python, moved / 'Contents/Resources/Python/bin/python3')
            plist = root / 'agent.plist'
            plist.write_text(autostart.generate_plist_content(str(python), project, root / 'logs'))
            plist.chmod(0o600)
            value = plistlib.loads(plist.read_bytes())
            self.assertEqual(value['ProgramArguments'], [str(python), '-I', '-B', str(project / 'bin/padpilotd')])
            with patch.object(gui, 'ROOT', project), patch.object(gui.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, stdout='OK')) as child:
                self.assertEqual(gui.send_change('set_language', {'language': 'en', '__expected_revision__': 7}), 'OK')
                self.assertEqual(child.call_args.args[0][1:3], ['-I', '-B'])
                self.assertEqual(json.loads(child.call_args.kwargs['input'])['__expected_revision__'], 7)
            with patch.object(autostart, 'PROJECT_ROOT', project):
                autostart.validate_plist(plist)
                value['ProgramArguments'][-1] = str(root / 'foreign/padpilotd')
                plist.write_bytes(plistlib.dumps(value))
                with self.assertRaises(RuntimeError):
                    autostart.validate_plist(plist)
            metadata = moved / 'Contents/Resources/runtime.json'
            metadata.write_text(json.dumps({'bundled': True, 'project_root': '../../elsewhere', 'python': str(python)}))
            with self.assertRaises(ValueError):
                runtime.app_runtime(moved)

    def test_python_preferences_reject_links_invalid_and_oversized_data(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)):
            pref = runtime.preference_path()
            self.assertEqual(runtime.read_preference(), {})
            atomic_write(pref, b'{"python":"/opt/python/bin/python3"}')
            self.assertEqual(runtime.read_preference()['python'], '/opt/python/bin/python3')
            for content in (b'{"python":"relative"}', b'{"extra":true}', b' ' * 16384):
                pref.write_bytes(content)
                with self.assertRaises(ValueError):
                    runtime.read_preference()
            pref.unlink()
            other = pref.parent / 'other.json'
            other.write_text('{}')
            pref.symlink_to(other)
            with self.assertRaises((OSError, RuntimeError, ValueError)):
                runtime.read_preference()
            pref.unlink()
            os.link(other, pref)
            with self.assertRaises((OSError, RuntimeError, ValueError)):
                runtime.read_preference()
        with self.assertRaises(ValueError):
            runtime.check_python('/bin/sh')

    def test_failed_release_install_restores_app_preferences_and_agent(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'home', return_value=Path(directory)), \
                patch.object(install_release, 'load_config'), patch.object(install_release, 'ensure_settings_closed'), \
                patch.object(install_release, 'stop_menu_apps'), \
                patch.object(install_release.subprocess, 'run', return_value=subprocess.CompletedProcess([], 113)):
            home = Path(directory).resolve()
            source = bundle(home / 'download/PadPilot.app')
            target = bundle(home / 'Applications/PadPilot.app')
            sentinel = target / 'previous-version'
            sentinel.write_text('keep')
            pref = runtime.preference_path()
            original_pref = b'{"python":"/opt/previous/python3"}\n'
            atomic_write(pref, original_pref)
            plist = home / 'Library/LaunchAgents/com.padpilot.daemon.plist'
            plist.parent.mkdir(parents=True)
            previous_root = runtime.app_runtime(target)[0]
            original_plist = autostart.generate_plist_content('/opt/previous/python3', previous_root).encode()
            atomic_write(plist, original_plist, private_parent=False)
            def fake_cli(app, *args, **kwargs):
                if args == ('gui-data',):
                    raise subprocess.CalledProcessError(1, ['gui-data'])
                return subprocess.CompletedProcess([], 0, stdout='{"daemon_responding":false}')
            with patch.object(install_release, 'cli', side_effect=fake_cli):
                with self.assertRaises(subprocess.CalledProcessError):
                    install_release.install(source, target)
            self.assertEqual(sentinel.read_text(), 'keep')
            self.assertEqual(pref.read_bytes(), original_pref)
            self.assertEqual(plist.read_bytes(), original_plist)

    def test_tag_validation_and_conflicting_runtime_options_fail_early(self):
        self.assertEqual(build_release.release_version('v1.2.3-dev.4'), '1.2.3-dev.4')
        for tag in ('main', 'v1', 'v1.2.3/../../bad', 'v1.2.3;echo bad'):
            with self.assertRaises(ValueError):
                build_release.release_version(tag)
        for args in (['--bundled', '--python', '/bin/python3'], ['--python', '/bin/python3', '--bundled']):
            result = subprocess.run(['bash', str(ROOT / 'scripts/install_release.sh'), *args], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Choose --bundled or --python', result.stderr)


if __name__ == '__main__':
    unittest.main()
