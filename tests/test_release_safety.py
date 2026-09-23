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
DAEMON = runpy.run_path(str(ROOT / 'bin/sidecarswitchd'))


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
        cls = DAEMON['SidecarSwitchDaemon']
        daemon = cls.__new__(cls)
        daemon.config = config.Config()
        daemon.engine = MagicMock(status_revision=1)
        daemon.engine.run_control.side_effect = lambda action: action()
        daemon.apply_config_change = MagicMock(return_value=(False, daemon.config))
        secret = 'PRIVATE_SERIAL_SENTINEL'
        payloads = [json.dumps({'command': 'save_pairing', 'params': {'name': secret}}),
                    'save_pairing:' + json.dumps({'name': secret}),
                    json.dumps({'command': {'name': secret}}),
                    json.dumps({'command': 'status\n' + secret}),
                    '{broken:' + secret + '}',
                    '{"command":"\\u0073ave_pairing","params":{"name":"' + secret + '"}}']
        with self.assertLogs('SidecarSwitch.Daemon', level='INFO') as logs:
            responses = [daemon.handle_client_cmd(value) for value in payloads]
        self.assertNotIn(secret, '\n'.join(logs.output))
        self.assertEqual(daemon.apply_config_change.call_count, 3)
        self.assertTrue(json.loads(responses[0])['ok'])
        self.assertFalse(json.loads(responses[2])['ok'])

    def test_socket_permissions_and_active_endpoint_not_replaced(self):
        # Unix socket names must fit macOS sockaddr_un; keep the temp prefix short.
        with tempfile.TemporaryDirectory(dir='/tmp', prefix='pps-') as directory:
            path = Path(directory) / 'sidecarswitch.sock'
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
        output = ['11\n12\n13\n', '/usr/bin/vim', f'/usr/bin/vim {ROOT}/bin/sidecarswitchd',
                  '/usr/bin/python3', f'/usr/bin/python3 {ROOT}/bin/sidecarswitchd',
                  '/usr/bin/python3', f'/usr/bin/python3 unrelated.py {ROOT}/bin/sidecarswitchd']
        with patch('core.autostart.subprocess.run', side_effect=[
                subprocess.CompletedProcess([], 0, value, '') for value in output]):
            self.assertEqual(autostart.daemon_pids(), [12])

    def test_foreign_job_is_not_stopped(self):
        with patch.object(autostart, 'job_loaded', side_effect=RuntimeError('foreign service')), \
             patch.object(autostart, 'daemon_pids') as pids, patch.object(autostart.os, 'kill') as kill:
            with self.assertRaises(RuntimeError):
                autostart.stop_daemon()
            pids.assert_not_called()
            kill.assert_not_called()

    def test_loaded_job_must_match_bundled_plist_and_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'SidecarSwitch.app/Contents/Library/LaunchAgents/com.sidecarswitch.daemon.plist'
            path.parent.mkdir(parents=True)
            path.write_text(autostart.generate_plist_content())
            executable = path.parents[2] / 'MacOS/SidecarSwitch'
            output = 'managed_by = com.apple.xpc.ServiceManagement\nparent bundle identifier = com.sidecarswitch.app\nprogram identifier = Contents/MacOS/SidecarSwitch (mode: 2)\n'
            with patch.object(autostart, 'service_owner', return_value=path.parents[3].resolve()), patch.object(autostart.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                self.assertTrue(autostart.job_loaded(path))
            for foreign in (output.replace('com.sidecarswitch.app', 'another.app'), output.replace('Contents/MacOS/SidecarSwitch', '/other/SidecarSwitch')):
                with patch.object(autostart.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, foreign, '')):
                    with self.assertRaises(RuntimeError):
                        autostart.job_loaded(path)


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
        command = runpy.run_path(str(ROOT / 'bin/sidecarswitch-cli'))['cmd_status']
        for snapshot in ({}, {'mode': 'automatic'}):
            with patch.dict(command.__globals__, read_status=lambda: snapshot, is_daemon_running=lambda: False), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                command(argparse.Namespace(json=True))
            self.assertFalse(json.loads(output.getvalue())['daemon_responding'])
            self.assertIn('version', json.loads(output.getvalue()))


if __name__ == '__main__':
    unittest.main()
