"""P0 boundaries: permissions, IPC privacy, launchd ownership and startup rollback."""
import contextlib
import io
import json
import os
import plistlib
import runpy
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import autostart, config
from core.storage import (UnsafePathError, atomic_write, private_directory, read_private_json,
                          remove_state_file, state_file_exists)

ROOT = Path(__file__).resolve().parents[1]
DAEMON = runpy.run_path(str(ROOT / 'bin/padpilotd'))


class ReleaseSafetyTests(unittest.TestCase):
    def test_private_state_repairs_modes_and_atomic_replacements(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'runtime/status.json'
            mask = os.umask(0)
            try:
                for _ in range(2):
                    atomic_write(state, b'{"safe": true}')
                    for path in (root, root / 'runtime'):
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
                    self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)
                    state.chmod(0o666)
                    self.assertEqual(read_private_json(state), {'safe': True})
                    self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)
            finally:
                os.umask(mask)

    def test_symlink_hardlink_and_foreign_paths_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / 'outside'
            outside.write_text('keep')
            linked = root / 'config.json'
            linked.symlink_to(outside)
            with self.assertRaises(UnsafePathError):
                atomic_write(linked, b'{}')
            self.assertEqual(outside.read_text(), 'keep')
            linked.unlink()
            os.link(outside, linked)
            with self.assertRaises(UnsafePathError):
                read_private_json(linked)
            alias = root / 'alias'
            alias.symlink_to(root, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                private_directory(alias)
            with patch('os.getuid', return_value=os.getuid() + 1), self.assertRaises(UnsafePathError):
                private_directory(root)

    def test_fallback_cleanup_and_hidden_markers_reject_untrusted_paths(self):
        from core import menu
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fallback, victim = root / 'fallback', root / 'victim'
            fallback.mkdir()
            victim.mkdir()
            status = victim / 'status.json'
            status.write_text('keep')
            (fallback / 'runtime').symlink_to(victim, target_is_directory=True)
            with self.assertRaises(UnsafePathError):
                remove_state_file(fallback / 'runtime/status.json')
            self.assertEqual(status.read_text(), 'keep')
            marker = fallback / 'menu-hidden'
            atomic_write(marker, b'')
            self.assertTrue(state_file_exists(marker))
            with patch('os.getuid', return_value=os.getuid() + 1), self.assertRaises(UnsafePathError):
                state_file_exists(marker)
            with patch.object(menu, 'state_file_exists', side_effect=UnsafePathError('foreign marker')), \
                 patch.object(menu, 'load_json', return_value={}), patch.object(menu, 'load_status', return_value={}), \
                 patch.object(menu, 'daemon_pids', return_value=[]):
                self.assertFalse(menu.read_menu()['hidden'])
            remove_state_file(marker)
            self.assertFalse(marker.exists())

    def test_failed_standalone_start_terminates_only_the_new_child(self):
        child = MagicMock()
        with patch.object(autostart.subprocess, 'Popen', return_value=child), \
             patch.object(autostart, 'wait_for_daemon', side_effect=RuntimeError('no handshake')), \
             patch.object(autostart.threading, 'Thread') as reaper, self.assertRaises(RuntimeError):
            autostart.start_standalone()
        child.terminate.assert_called_once_with()
        child.wait.assert_called_once_with(timeout=5)
        reaper.assert_not_called()

    def test_preflight_failure_preserves_service_and_write_failure_restores_it(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.plist'
            path.write_text(autostart.generate_plist_content())
            for fail_before_stop in (True, False):
                with patch.object(autostart, 'job_loaded', side_effect=[True, False]), \
                     patch.object(autostart, 'is_daemon_running', return_value=True), \
                     patch.object(autostart, 'stop_daemon') as stop, \
                     patch.object(autostart, 'load_config', side_effect=config.Config), \
                     patch.object(autostart, 'private_directory', side_effect=UnsafePathError('unsafe logs') if fail_before_stop else None), \
                     patch.object(autostart, 'private_file'), \
                     patch.object(autostart, 'atomic_write', side_effect=OSError('disk full')), \
                     patch.object(autostart, 'wait_for_daemon') as wait, \
                     patch.object(autostart.subprocess, 'run') as run:
                    ok, _ = autostart.enable_autostart(plist_path=path)
                self.assertFalse(ok)
                self.assertEqual(stop.call_count, 0 if fail_before_stop else 1)
                self.assertEqual(wait.call_count, 0 if fail_before_stop else 1)
                self.assertEqual(run.call_count, 0 if fail_before_stop else 1)

    def test_rollback_never_adds_standalone_to_an_existing_launchd_job(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.plist'
            path.write_text(autostart.generate_plist_content())
            with patch.object(autostart, 'job_loaded', return_value=True), \
                 patch.object(autostart, 'is_daemon_running', side_effect=[True, False]), \
                 patch.object(autostart, 'load_config', side_effect=config.Config), \
                 patch.object(autostart, 'stop_daemon', side_effect=RuntimeError('still loaded')), \
                 patch.object(autostart, 'start_standalone') as start, \
                 patch.object(autostart, 'wait_for_daemon') as wait:
                ok, _ = autostart.enable_autostart(plist_path=path, log_dir=Path(directory) / 'logs')
            self.assertFalse(ok)
            start.assert_not_called()
            wait.assert_called_once_with()

    def test_config_fallback_is_private_and_foreign_fallback_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fallback = root / 'fallback/config.json'
            original = config.atomic_write
            def write(path, content):
                if path == root / 'primary/config.json':
                    raise PermissionError('primary unavailable')
                original(path, content)
            with patch.object(config, 'CONFIG_FILE', root / 'primary/config.json'), \
                 patch.object(config, 'FALLBACK_CONFIG_FILE', fallback), patch.object(config, 'atomic_write', write):
                config.save_config(config.Config())
                self.assertEqual(stat.S_IMODE(fallback.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(fallback.parent.stat().st_mode), 0o700)
                with patch('os.getuid', return_value=os.getuid() + 1), self.assertRaises(UnsafePathError):
                    config.load_config()

    def test_ipc_payloads_and_unknown_commands_never_enter_logs(self):
        cls = DAEMON['PadPilotDaemon']
        daemon = cls.__new__(cls)
        daemon.config = config.Config()
        daemon.engine = MagicMock(status_revision=1)
        daemon.apply_config_change = MagicMock(return_value=(False, daemon.config))
        secret = 'PRIVATE_SERIAL_SENTINEL'
        payloads = [json.dumps({'command': 'save_pairing', 'params': {'name': secret}}),
                    'save_pairing:' + json.dumps({'name': secret}),
                    json.dumps({'command': {'name': secret}}),
                    json.dumps({'command': 'status\n' + secret}),
                    '{broken:' + secret + '}',
                    '{"command":"\\u0073ave_pairing","params":{"name":"' + secret + '"}}']
        with self.assertLogs('PadPilot.Daemon', level='INFO') as logs:
            responses = [daemon.handle_client_cmd(value) for value in payloads]
        self.assertNotIn(secret, '\n'.join(logs.output))
        self.assertEqual(daemon.apply_config_change.call_count, 3)
        self.assertTrue(json.loads(responses[0])['ok'])
        self.assertFalse(json.loads(responses[2])['ok'])

    def test_socket_permissions_and_active_endpoint_not_replaced(self):
        # Unix socket names must fit macOS sockaddr_un; keep the temp prefix short.
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='pps-') as directory:
            path = Path(directory) / 'padpilot.sock'
            server = DAEMON['create_ipc_socket'](path)
            try:
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                inode = path.stat().st_ino
                with self.assertRaises(RuntimeError):
                    DAEMON['create_ipc_socket'](path)
                self.assertEqual(path.stat().st_ino, inode)
                connection, _ = server.accept()
                connection.close()
            finally:
                server.close()
            # A dead endpoint can be replaced; a regular file cannot.
            DAEMON['create_ipc_socket'](path).close()
            path.unlink()
            path.write_text('keep')
            with self.assertRaises(RuntimeError):
                DAEMON['create_ipc_socket'](path)
            self.assertEqual(path.read_text(), 'keep')

    def test_daemon_candidate_must_be_python_running_our_script(self):
        output = ['11\n12\n13\n', '/usr/bin/vim', f'/usr/bin/vim {ROOT}/bin/padpilotd',
                  '/usr/bin/python3', f'/usr/bin/python3 {ROOT}/bin/padpilotd',
                  '/usr/bin/python3', f'/usr/bin/python3 unrelated.py {ROOT}/bin/padpilotd']
        with patch('core.autostart.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, value, '') for value in output]):
            self.assertEqual(autostart.daemon_pids(), [12])

    def test_foreign_plist_is_not_modified_or_unloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.plist'
            content = plistlib.dumps({'Label': 'another.app', 'ProgramArguments': ['/usr/bin/python3', str(ROOT / 'bin/padpilotd')]})
            path.write_bytes(content)
            path.chmod(0o644)
            with patch('core.autostart.subprocess.run') as run, self.assertRaises(RuntimeError):
                autostart.stop_daemon(path)
            run.assert_not_called()
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)

    def test_loaded_job_must_match_disk_plist_arguments_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.plist'
            path.write_text(autostart.generate_plist_content())
            output = f'path = {path}\narguments = {{\n{sys.executable}\n{ROOT}/bin/padpilotd\n}}\n'
            with patch('core.autostart.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                self.assertTrue(autostart.job_loaded(path))
            with patch('core.autostart.subprocess.run', return_value=subprocess.CompletedProcess([], 0, output.replace(str(ROOT), '/other'), '')), self.assertRaises(RuntimeError):
                autostart.job_loaded(path)

    def test_failed_handshake_restores_previous_login_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'job.plist'
            previous = autostart.generate_plist_content().encode()
            path.write_bytes(previous)
            cfg = config.Config(autostart_on_login=False, revision=7)
            with patch.object(autostart, 'job_loaded', return_value=False), \
                 patch.object(autostart, 'is_daemon_running', return_value=False), \
                 patch.object(autostart, 'stop_daemon') as stop, \
                 patch.object(autostart, 'load_config', return_value=cfg), \
                 patch.object(autostart, 'save_config') as save, \
                 patch.object(autostart, 'wait_for_daemon', side_effect=RuntimeError('not ready')), \
                 patch('core.autostart.subprocess.run', return_value=subprocess.CompletedProcess([], 0)):
                ok, message = autostart.enable_autostart(plist_path=path, log_dir=Path(directory) / 'logs')
            self.assertFalse(ok)
            self.assertIn('restored', message)
            self.assertEqual(path.read_bytes(), previous)
            self.assertEqual(save.call_args.args[0].to_dict(), cfg.to_dict())
            self.assertEqual(stop.call_count, 2)

    def test_handshake_rejects_legacy_or_foreign_response(self):
        payload = {'ok': True, 'project_root': str(ROOT), 'pid': 123}
        for value, expected in ((payload, True), (dict(payload, project_root='/another'), False),
                                (dict(payload, pid='123'), False), ('OK', False)):
            client = MagicMock()
            client.makefile.return_value = io.BytesIO(json.dumps(value).encode())
            with patch.object(autostart.socket, 'socket') as factory:
                factory.return_value.__enter__.return_value = client
                self.assertIs(autostart.is_daemon_running(), expected)

    def test_cli_status_labels_stale_snapshot_and_empty_json(self):
        import argparse
        command = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))['cmd_status']
        for snapshot in ({}, {'mode': 'automatic'}):
            with patch.dict(command.__globals__, read_status=lambda: snapshot, is_daemon_running=lambda: False), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                command(argparse.Namespace(json=True))
            self.assertFalse(json.loads(output.getvalue())['daemon_responding'])
            self.assertIn('version', json.loads(output.getvalue()))


if __name__ == '__main__':
    unittest.main()
