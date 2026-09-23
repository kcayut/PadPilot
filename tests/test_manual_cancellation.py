"""Manual mode cancels pending work without waiting for simulated hardware."""
import json
import runpy
import socket
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

from core import logger

with patch.object(logger, 'setup_logging'):
    from core.config import Config
    from core.models import ActualState, DisplayInfo, DisplayRole, IpadConfig, OperationMode, pairing_key
    from core.state_engine import StateEngine
    Daemon = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'bin/sidecarswitchd'))['SidecarSwitchDaemon']


class ObservedLock:
    """Expose when an old control has reached the existing evaluation lock."""
    def __init__(self, lock, waiting):
        self.lock, self.waiting = lock, waiting

    def acquire(self, *args, **kwargs):
        if threading.current_thread().name == 'queued-control':
            self.waiting.set()
        return self.lock.acquire(*args, **kwargs)

    def release(self):
        self.lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class ManualCancellationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.tasks, self.gates = [], []
        for target in ('core.state_engine.write_atomic_status', 'core.state_engine.notify_error',
                       'core.state_engine.logger'):
            self.stack.enter_context(patch(target))
        self.save = MagicMock()
        self.stack.enter_context(patch.dict(Daemon.handle_client_cmd.__globals__,
                                           save_config=self.save, logger=MagicMock()))

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        for task in self.tasks:
            task['thread'].join(2)
        self.assertFalse(any(task['thread'].is_alive() for task in self.tasks), 'Worker did not stop')

    def make_state(self, mode=OperationMode.AUTOMATIC):
        self.cfg = Config(mode=mode, auto_detect_ipad=False, retry_interval=0,
                          ipad=IpadConfig('Test iPad', 'TARGET'))
        self.fallback = DisplayInfo(99, 'SidecarSwitchVirtual', is_main=True, is_virtual=True)
        self.ipad = DisplayInfo(2, 'Test iPad', is_sidecar=True)
        self.actual = ActualState(main_display=self.fallback, virtual_display_connected=True,
                                  sidecar_available=True, resolved_ipad=self.cfg.ipad)
        self.detector, self.bd = MagicMock(), MagicMock()
        self.detector.observe.side_effect = lambda **_: (self.actual, ((), False))
        self.bd.set_main_display.side_effect = self.set_main
        self.engine = StateEngine(self.cfg, self.detector, self.bd)
        # Keep every transition on a worker owned and joined by this test.
        self.engine._trigger_transition = self.engine._run_transition
        self.daemon = Daemon.__new__(Daemon)
        self.daemon.config, self.daemon.engine = self.cfg, self.engine
        self.daemon.detector, self.daemon.bd_cli = self.detector, self.bd
        self.daemon.config_lock = threading.RLock()
        self.daemon.wakeup = threading.Event()
        self.daemon.running = True
        self.save.reset_mock(side_effect=True)

    def set_main(self, _):
        self.actual.main_display = self.ipad
        return True

    def connected(self, _):
        self.actual.sidecar_connected = self.actual.sidecar_display_online = True
        return True

    def block(self, result):
        entered, release = threading.Event(), threading.Event()
        self.gates.append(release)

        def blocked(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Simulated hardware was not released')
            return result(*args, **kwargs)

        return blocked, entered, release

    def start(self, action, name=None):
        task = {'done': threading.Event(), 'values': [], 'errors': []}

        def run():
            try:
                task['values'].append(action())
            except BaseException as error:
                task['errors'].append(error)
            finally:
                task['done'].set()

        task['thread'] = threading.Thread(target=run, name=name, daemon=True)
        self.tasks.append(task)
        task['thread'].start()
        return task

    def finish(self, task, timeout=2):
        self.assertTrue(task['done'].wait(timeout), 'Command waited for blocked hardware')
        task['thread'].join(1)
        self.assertEqual(task['errors'], [])
        return task['values'][0]

    def manual_request(self, revision=None):
        return json.dumps({'command': 'set_mode', 'params': {'mode': 'manual_only'},
                           'expected_revision': self.daemon.config.revision if revision is None else revision})

    def test_manual_returns_during_connect_and_later_explicit_connection_still_works(self):
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                self.make_state()
                connect, entered, release = self.block(self.connected if accepted else lambda _: False)
                self.bd.connect_sidecar.side_effect = connect
                worker = self.start(lambda: self.engine.evaluate(async_transition=False))
                self.assertTrue(entered.wait(1))
                self.finish(self.start(lambda: self.engine.set_mode(OperationMode.MANUAL_ONLY)), .5)
                self.assertFalse(release.is_set())
                release.set()
                self.finish(worker)
                self.assertEqual(self.engine.runtime.mode, OperationMode.MANUAL_ONLY)
                self.bd.connect_sidecar.assert_called_once_with('TARGET')
                self.bd.set_main_display.assert_not_called()
                self.engine.evaluate(async_transition=False)
                self.bd.connect_sidecar.assert_called_once()

                self.actual.sidecar_connected = self.actual.sidecar_display_online = False
                self.bd.connect_sidecar.side_effect = self.connected
                self.assertTrue(self.engine.request_sidecar_connection(async_transition=False))
                self.assertEqual(self.bd.connect_sidecar.call_count, 2)
                self.bd.set_main_display.assert_called_once()

    def test_selecting_manual_again_cancels_an_active_one_shot(self):
        self.make_state(OperationMode.MANUAL_ONLY)
        connect, entered, release = self.block(lambda _: False)
        self.bd.connect_sidecar.side_effect = connect
        worker = self.start(lambda: self.engine.request_sidecar_connection(async_transition=False))
        self.assertTrue(entered.wait(1))
        response = self.finish(self.start(lambda: self.daemon.handle_client_cmd(self.manual_request())), .5)
        self.assertTrue(json.loads(response)['ok'])
        release.set()
        self.finish(worker)
        self.assertIsNone(self.engine.runtime.user_override)
        self.bd.connect_sidecar.assert_called_once()
        self.bd.set_main_display.assert_not_called()

    def test_manual_discards_override_and_reconnect_queued_behind_observation(self):
        for action in ('override', 'reconnect'):
            with self.subTest(action=action):
                self.make_state()
                observe, entered, release = self.block(lambda **_: (self.actual, ((), False)))
                self.detector.observe.side_effect = observe
                waiting = threading.Event()
                self.engine._eval_lock = ObservedLock(self.engine._eval_lock, waiting)
                scan = self.start(lambda: self.engine.evaluate(async_transition=False))
                self.assertTrue(entered.wait(1))
                queued = self.start(
                    (lambda: self.engine.set_user_override(DisplayRole.IPAD_MAIN, async_transition=False))
                    if action == 'override' else self.engine.reconnect_sidecar, name='queued-control')
                self.assertTrue(waiting.wait(1))
                self.finish(self.start(lambda: self.engine.set_mode(OperationMode.MANUAL_ONLY)), .5)
                release.set()
                self.finish(scan)
                self.finish(queued)
                self.bd.connect_sidecar.assert_not_called()
                self.bd.disconnect_sidecar.assert_not_called()
                self.bd.set_main_display.assert_not_called()
                self.assertIsNone(self.engine.runtime.user_override)

    def test_json_manual_ack_does_not_wait_for_refresh_or_guarded_control(self):
        for command in ('refresh', 'use_ipad_main'):
            with self.subTest(command=command):
                self.make_state()
                observe, entered, release = self.block(lambda **_: (self.actual, ((), False)))
                self.detector.observe.side_effect = observe
                params = {} if command == 'refresh' else {'target_key': pairing_key(self.cfg.ipad.to_dict())}
                request = json.dumps({'command': command, 'params': params,
                                      'expected_revision': self.cfg.revision})
                worker = self.start(lambda: self.daemon.handle_client_cmd(request))
                self.assertTrue(entered.wait(1))
                response = self.finish(self.start(lambda: self.daemon.handle_client_cmd(self.manual_request())), .5)
                self.assertTrue(json.loads(response)['ok'])
                self.assertFalse(release.is_set())
                self.save.assert_called_once()
                self.assertEqual(self.save.call_args.args[0].mode, OperationMode.MANUAL_ONLY)
                self.assertEqual(self.daemon.config.mode, OperationMode.MANUAL_ONLY)
                release.set()
                self.finish(worker)
                self.bd.connect_sidecar.assert_not_called()
                self.bd.set_main_display.assert_not_called()

    def test_conflict_or_save_failure_does_not_cancel_a_running_connection(self):
        for error in ('CONFIG_CONFLICT', 'VALIDATION_ERROR'):
            with self.subTest(error=error):
                self.make_state()
                connect, entered, release = self.block(self.connected)
                self.bd.connect_sidecar.side_effect = connect
                worker = self.start(lambda: self.engine.evaluate(async_transition=False))
                self.assertTrue(entered.wait(1))
                revision = self.cfg.revision - 1 if error == 'CONFIG_CONFLICT' else self.cfg.revision
                if error == 'VALIDATION_ERROR':
                    self.save.side_effect = OSError('simulated save failure')
                response = self.finish(self.start(lambda: self.daemon.handle_client_cmd(self.manual_request(revision))), .5)
                self.assertEqual(json.loads(response)['error'], error)
                self.assertEqual(self.engine.runtime.mode, OperationMode.AUTOMATIC)
                self.assertEqual(self.daemon.config.mode, OperationMode.AUTOMATIC)
                release.set()
                self.finish(worker)
                self.bd.connect_sidecar.assert_called_once_with('TARGET')
                self.bd.set_main_display.assert_called_once()

    def test_socket_server_accepts_status_and_manual_while_refresh_is_blocked(self):
        self.make_state()
        observe, entered, release = self.block(lambda **_: (self.actual, ((), False)))
        self.detector.observe.side_effect = observe
        ready, bind_errors = threading.Event(), []
        create_socket = Daemon.run_ipc_server.__globals__['create_ipc_socket']

        def listening(path):
            try:
                server = create_socket(path)
                server.settimeout(.1)
                return server
            except OSError as error:
                bind_errors.append(error)
                raise
            finally:
                ready.set()

        with tempfile.TemporaryDirectory(prefix='sidecarswitch-ipc-') as directory:
            endpoint = Path(directory) / 'test.sock'

            def request(command):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(2)
                    client.connect(str(endpoint))
                    client.sendall((command + '\n').encode())
                    return json.loads(client.recv(8192))

            with patch.dict(Daemon.run_ipc_server.__globals__, SOCKET_PATH=endpoint,
                            create_ipc_socket=listening):
                server = self.start(self.daemon.run_ipc_server)
                refresh = None
                try:
                    self.assertTrue(ready.wait(1))
                    self.assertEqual(bind_errors, [], 'Temporary Unix socket could not be bound')
                    refresh = self.start(lambda: request('{"command":"refresh"}'))
                    self.assertTrue(entered.wait(1))
                    status = self.finish(self.start(lambda: request('{"command":"status"}')), .5)
                    self.assertTrue(status['ok'])
                    manual = self.finish(self.start(lambda: request(self.manual_request())), .5)
                    self.assertTrue(manual['ok'])
                    self.assertEqual(self.daemon.config.mode, OperationMode.MANUAL_ONLY)
                    self.assertFalse(release.is_set())
                    self.save.assert_called_once()
                finally:
                    release.set()
                    self.daemon.running = False
                    if refresh is not None:
                        self.finish(refresh)
                    self.finish(server)
        self.bd.connect_sidecar.assert_not_called()
        self.bd.set_main_display.assert_not_called()

    def test_manual_wakes_sixty_second_retry_wait_without_another_attempt(self):
        self.make_state()
        self.cfg.retry_interval = 60
        self.bd.connect_sidecar.return_value = False
        waiting, wait = threading.Event(), self.engine._wait

        def retry_wait(seconds):
            self.assertEqual(seconds, 60)
            waiting.set()
            wait(seconds)

        with patch.object(self.engine, '_wait', side_effect=retry_wait):
            worker = self.start(lambda: self.engine.evaluate(async_transition=False))
            try:
                self.assertTrue(waiting.wait(1))
            finally:
                self.engine.set_mode(OperationMode.MANUAL_ONLY)
                self.finish(worker, .5)
        self.bd.connect_sidecar.assert_called_once_with('TARGET')
        self.bd.set_main_display.assert_not_called()

    def test_manual_during_virtual_settle_wait_does_not_change_main_display(self):
        self.make_state()
        self.actual.main_display = None
        self.actual.sidecar_available = False
        self.actual.virtual_display_exists = True
        self.actual.virtual_display_connected = False
        self.bd.connect_virtual_display.return_value = True
        waiting, wait = threading.Event(), self.engine._wait

        def settle_wait(seconds):
            self.assertEqual(seconds, 1)
            waiting.set()
            wait(seconds)

        with patch.object(self.engine, '_wait', side_effect=settle_wait):
            worker = self.start(lambda: self.engine.evaluate(async_transition=False))
            try:
                self.assertTrue(waiting.wait(1))
                self.bd.connect_virtual_display.assert_called_once_with('SidecarSwitchVirtual')
            finally:
                self.engine.set_mode(OperationMode.MANUAL_ONLY)
                self.finish(worker, .5)
        self.bd.set_main_display.assert_not_called()
        self.bd.connect_sidecar.assert_not_called()


if __name__ == '__main__':
    unittest.main()
