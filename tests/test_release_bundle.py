import json
import os
import plistlib
import re
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
    (contents / 'Resources/SidecarSwitch/bin').mkdir(parents=True)
    (contents / 'Resources/Python/bin').mkdir(parents=True)
    (contents / 'Resources/Python/bin/python3').write_bytes(b'python-placeholder')
    (contents / 'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.sidecarswitch.app'}))
    (contents / 'Resources/runtime.json').write_text(json.dumps({
        'bundled': True, 'project_root': 'SidecarSwitch', 'python': 'Python/bin/python3'}))
    return path


class ReleaseBundleTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'darwin', 'Release selection uses macOS plutil')
    def test_download_selects_only_a_published_sidecarswitch_dmg(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, requests = root / 'releases.json', root / 'requests.txt'
            curl = root / 'curl'
            curl.write_text(f'#!{sys.executable}\n' + '''import os, shutil, sys
from pathlib import Path
url = next(arg for arg in sys.argv if arg.startswith('https://'))
with open(os.environ['REQUESTS'], 'a') as log:
    log.write(url + '\\n')
if '/releases?' not in url:
    sys.exit(1)  # Stop before any app download, mounting, or installation.
shutil.copyfile(os.environ['FIXTURE'], sys.argv[sys.argv.index('--output') + 1])
''')
            curl.chmod(0o755)
            for name, output in (('uname', 'if [ "$1" = -s ]; then echo Darwin; else echo arm64; fi'),
                                 ('sw_vers', 'echo 15.0')):
                tool = root / name
                tool.write_text('#!/bin/sh\n' + output + '\n')
                tool.chmod(0o755)
            releases = [
                {'tag_name': 'v0.1.0-dev.4', 'draft': False, 'assets': [{'name': 'unrelated.dmg'}]},
                {'tag_name': 'v0.1.0-dev.3', 'draft': True,
                 'assets': [{'name': 'SidecarSwitch-0.1.0-dev.3-macos-arm64.dmg'}]},
                {'tag_name': 'v0.1.0-dev.2', 'draft': False,
                 'assets': [{'name': 'SHA256SUMS'}, {'name': 'SidecarSwitch-0.1.0-dev.2-macos-arm64.dmg'}]},
            ]
            for available in (True, False):
                fixture.write_text(json.dumps(releases if available else releases[:2]))
                requests.unlink(missing_ok=True)
                result = subprocess.run(['bash', str(ROOT / 'scripts/install_release.sh'), '--yes', '--bundled'],
                                        env=dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'],
                                                 FIXTURE=str(fixture), REQUESTS=str(requests)),
                                        capture_output=True, text=True)
                urls = requests.read_text().splitlines()
                self.assertNotEqual(result.returncode, 0)
                if available:
                    self.assertEqual(len(urls), 2)
                    self.assertTrue(urls[-1].endswith('/v0.1.0-dev.2/SidecarSwitch-0.1.0-dev.2-macos-arm64.dmg'))
                else:
                    self.assertEqual(len(urls), 1)
                    self.assertIn('No published SidecarSwitch release found yet', result.stderr)

    @unittest.skipUnless(sys.platform == 'darwin', 'Icon decoding uses macOS tools')
    def test_app_icon_decodes_at_every_standard_and_retina_size(self):
        from build_app import build_icon
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            icon = root / 'SidecarSwitch.icns'
            build_icon(root, icon)
            data = icon.read_bytes()
            self.assertEqual(data[:4], b'icns')
            self.assertEqual(int.from_bytes(data[4:8], 'big'), len(data))
            decoded = root / 'decoded.iconset'
            subprocess.run(['/usr/bin/iconutil', '-c', 'iconset', str(icon), '-o', str(decoded)],
                           check=True, capture_output=True)
            self.assertEqual(len(list(decoded.glob('*.png'))), 10)
            for size in (16, 32, 128, 256, 512):
                for scale in (1, 2):
                    name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
                    png = (decoded / name).read_bytes()
                    self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(int.from_bytes(png[16:20], 'big'), size * scale)
                    self.assertEqual(int.from_bytes(png[20:24], 'big'), size * scale)

    def test_relocation_preserves_runtime_and_launch_agent_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            app = bundle(root / 'SidecarSwitch.app')
            (root / 'Folder with spaces').mkdir()
            moved = root / 'Folder with spaces/SidecarSwitch.app'
            app.rename(moved)
            project, python = runtime.app_runtime(moved)
            self.assertEqual(runtime.bundled_app(project), moved)
            self.assertEqual(python, moved / 'Contents/Resources/Python/bin/python3')
            plist = root / 'agent.plist'
            plist.write_text(autostart.generate_plist_content())
            plist.chmod(0o600)
            value = plistlib.loads(plist.read_bytes())
            self.assertEqual(value['BundleProgram'], 'Contents/MacOS/SidecarSwitch')
            self.assertEqual(value['ProgramArguments'], ['SidecarSwitch', '--daemon'])
            with patch.object(gui, 'ROOT', project), patch.object(gui.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, stdout='OK')) as child:
                self.assertEqual(gui.send_change('set_language', {'language': 'en', '__expected_revision__': 7}), 'OK')
                self.assertEqual(child.call_args.args[0][1:3], ['-I', '-B'])
                self.assertEqual(json.loads(child.call_args.kwargs['input'])['__expected_revision__'], 7)
            with patch.object(autostart, 'PROJECT_ROOT', project):
                autostart.validate_plist(plist)
                value['ProgramArguments'][-1] = str(root / 'foreign/sidecarswitchd')
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
        for failure, was_running, previous_service in [('gui-data', False, 'enabled'), ('broken-cli', True, 'enabled'),
                ('broken-cli', True, 'notRegistered'), ('broken-cli-unregister', False, 'enabled'), ('unregister', True, 'enabled')]:
            with self.subTest(failure=failure, previous_service=previous_service), tempfile.TemporaryDirectory() as directory, \
                    patch.object(Path, 'home', return_value=Path(directory)), \
                    patch.object(install_release, 'load_config'), patch.object(install_release, 'ensure_settings_closed'), \
                    patch.object(install_release, 'stop_menu_apps'), \
                    patch.object(install_release, 'installation_service', return_value=previous_service), \
                    patch.object(install_release.subprocess, 'run', side_effect=lambda command, **kwargs:
                                 subprocess.CompletedProcess(command, 1 if command[0] == 'pgrep' else 0)) as process_checks:
                home = Path(directory).resolve()
                source = bundle(home / 'download/SidecarSwitch.app')
                target = bundle(home / 'Applications [test] with spaces/SidecarSwitch.app')
                sentinel = target / 'previous-version'
                sentinel.write_text('keep')
                pref = runtime.preference_path()
                original_pref = b'{"python":"/opt/previous/python3"}\n'
                atomic_write(pref, original_pref)
                plist = target / 'Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist'
                original_plist = autostart.generate_plist_content().encode()
                atomic_write(plist, original_plist, private_parent=False)
                state = {'registered': previous_service == 'enabled', 'running': was_running}
                def fake_cli(app, *args, **kwargs):
                    if not sentinel.exists() and (failure.startswith('broken-cli')
                            or args == (('start',) if failure == 'unregister' else ('gui-data',))):
                        raise subprocess.CalledProcessError(1, list(args))
                    if args == ('exit',): state['running'] = False
                    if args == ('start',): state['running'] = True
                    return subprocess.CompletedProcess([], 0, stdout=json.dumps({'daemon_responding': state['running']}))
                def service(action, app):
                    state['registered'] = state['running'] = action == 'register'
                    if action == 'unregister' and not sentinel.exists() and 'unregister' in failure:
                        # The native command can time out after launchd removed the job.
                        raise subprocess.TimeoutExpired(['SidecarSwitch', '--service', action], 30)
                    return 'enabled' if state['registered'] else 'notRegistered'
                with patch.object(install_release, 'cli', side_effect=fake_cli), \
                     patch.object(install_release, 'service_command', side_effect=service), \
                     patch.object(install_release, 'job_loaded', side_effect=lambda path: state['registered']), \
                     patch.object(install_release, 'daemon_pids', side_effect=lambda root: [123] if state['running'] else []) as pids:
                    with self.assertRaises(subprocess.CalledProcessError):
                        install_release.install(source, target)
                    pids.assert_called_once_with(runtime.app_runtime(target)[0])
                self.assertEqual(sentinel.read_text(), 'keep')
                self.assertEqual(pref.read_bytes(), original_pref)
                self.assertEqual(plist.read_bytes(), original_plist)
                self.assertEqual(state, {'registered': previous_service == 'enabled', 'running': was_running})
                pattern = next(call.args[0][-1] for call in process_checks.call_args_list if call.args[0][0] == 'pgrep')
                self.assertRegex(f'{target}/Contents/MacOS/SidecarSwitch --daemon', pattern)
                self.assertRegex(f'/opt/python3 -I -B {target}/Contents/Resources/SidecarSwitch/bin/sidecarswitch-cli exit', pattern)
                self.assertNotRegex(f'{source}/Contents/Resources/Python/bin/python3 installer', pattern)

    def test_rollback_preserves_both_apps_when_replacement_shutdown_is_unverified(self):
        for blocked in ('job', 'daemon', 'job-query', 'daemon-query', 'menu', 'native', 'native-query'):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as directory, \
                    patch.object(Path, 'home', return_value=Path(directory)), \
                    patch.object(install_release, 'load_config'), patch.object(install_release, 'ensure_settings_closed'), \
                    patch.object(install_release, 'installation_service', return_value='enabled'), \
                    patch.object(install_release, 'service_command', return_value='notRegistered') as service, \
                    patch.object(install_release.subprocess, 'run', side_effect=lambda command, **kwargs:
                                 subprocess.CompletedProcess(command, 2 if blocked == 'native-query' else 0)):
                home = Path(directory).resolve()
                source = bundle(home / 'download/SidecarSwitch.app')
                target = bundle(home / 'Applications/SidecarSwitch.app')
                (source / 'replacement').write_text('new')
                (target / 'previous-version').write_text('old')
                pref = runtime.preference_path()
                atomic_write(pref, b'{"python":"/opt/previous/python3"}\n')
                def fake_cli(app, *args, **kwargs):
                    if (app / 'replacement').exists():
                        raise subprocess.CalledProcessError(1, list(args))
                    return subprocess.CompletedProcess([], 0, stdout='{"daemon_responding":false}')
                with patch.object(install_release, 'cli', side_effect=fake_cli), \
                     patch.object(install_release, 'stop_menu_apps', side_effect=[None, RuntimeError('menu still running')] if blocked == 'menu' else None), \
                     patch.object(install_release, 'job_loaded', return_value=blocked == 'job',
                                  side_effect=RuntimeError('ownership cannot be verified') if blocked == 'job-query' else None), \
                     patch.object(install_release, 'daemon_pids', return_value=[123] if blocked == 'daemon' else [],
                                  side_effect=RuntimeError('processes cannot be verified') if blocked == 'daemon-query' else None):
                    with self.assertRaisesRegex(RuntimeError, 'Rollback incomplete'):
                        install_release.install(source, target)
                self.assertTrue((target / 'replacement').exists())
                self.assertFalse((target / 'previous-version').exists())
                self.assertEqual(pref.read_bytes(), b'{}\n')
                self.assertEqual(len(list((home / '.Trash').glob('*/SidecarSwitch.app/previous-version'))), 1)
                self.assertNotIn('register', [call.args[0] for call in service.call_args_list])

    def test_daemon_pid_check_uses_target_root_and_verifies_interpreter_identity(self):
        source = Path('/download/SidecarSwitch.app/Contents/Resources/SidecarSwitch')
        target = Path('/Applications/SidecarSwitch.app/Contents/Resources/SidecarSwitch')
        python = '/opt/test/bin/python3'
        def run(command, **kwargs):
            if command[0] == 'pgrep':
                self.assertEqual(command[-1], r'(^| )' + re.escape(str(target / 'bin/sidecarswitchd')) + r'( |$)')
                output = '12 34 56'
            elif command[-1] == 'comm=':
                output = python
            else:
                output = {'12': f'{python} -I -B {target}/bin/sidecarswitchd',
                          '34': f'{python} -I -B {source}/bin/sidecarswitchd',
                          '56': f'/opt/other/bin/python3 -I -B {target}/bin/sidecarswitchd'}[command[command.index('-p') + 1]]
            return subprocess.CompletedProcess(command, 0, stdout=output)
        with patch.object(autostart, 'PROJECT_ROOT', source), \
             patch.object(autostart.subprocess, 'run', side_effect=run), \
             patch.object(autostart.shutil, 'which', return_value=None):
            self.assertEqual(autostart.daemon_pids(target), [12])
            self.assertEqual(autostart.PROJECT_ROOT, source)

    def test_uninstall_unregisters_before_trashing_and_preserves_app_on_failure(self):
        import manage_app
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                home = Path(directory).resolve()
                app = bundle(home / 'Applications/SidecarSwitch.app')
                events = []
                def native(action, target):
                    self.assertEqual(action, 'unregister')
                    self.assertTrue(app.exists(), 'Unregister needs the original app')
                    events.append('unregister')
                    if failure: raise RuntimeError('registration busy')
                    return 'notRegistered'
                def cli(*args, **kwargs):
                    events.append('exit')
                    return subprocess.CompletedProcess([], 0)
                with patch.object(Path, 'home', return_value=home), \
                     patch.object(manage_app, 'bundled_app', return_value=app), \
                     patch.object(manage_app, 'owned_app', return_value=True), \
                     patch.object(manage_app, 'installation_service', return_value='enabled'), \
                     patch.object(manage_app, 'ensure_settings_closed'), patch.object(manage_app, 'stop_menu_apps'), \
                     patch.object(manage_app, 'service_command', side_effect=native), \
                     patch.object(manage_app.subprocess, 'run', side_effect=cli):
                    if failure:
                        with self.assertRaisesRegex(RuntimeError, 'registration busy'):
                            manage_app.manage(uninstall=True)
                    else:
                        manage_app.manage(uninstall=True)
                self.assertEqual(events, ['exit', 'unregister'])
                self.assertEqual(app.exists(), failure)
                self.assertEqual((home / '.Trash').exists(), not failure)

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
