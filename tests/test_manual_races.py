"""Exercise IPC races using the existing isolated cancellation fixture."""
import json
import threading
import time
import unittest
from unittest.mock import patch

import test_manual_cancellation as fixtures


class ManualRaceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ManualCancellationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.addCleanup(self.fixture.tearDown)

    def test_connect_ipc_pressed_during_transition_does_not_queue_another_retry_budget(self):
        fixture = self.fixture
        fixture.make_state(fixtures.OperationMode.MANUAL_ONLY)
        connect, entered, release = fixture.block(lambda _: False)
        fixture.bd.connect_sidecar.side_effect = connect
        waiting = threading.Event()
        fixture.engine._eval_lock = fixtures.ObservedLock(fixture.engine._eval_lock, waiting)
        request = json.dumps({'command': 'connect_ipad', 'expected_revision': fixture.cfg.revision,
                              'params': {'target_key': fixtures.pairing_key(fixture.cfg.ipad.to_dict())}})
        first = fixture.start(lambda: fixture.daemon.handle_client_cmd(request))
        self.assertTrue(entered.wait(1), 'First request did not reach simulated hardware')
        second = fixture.start(lambda: fixture.daemon.handle_client_cmd(request), name='queued-control')
        self.assertTrue(waiting.wait(1), 'Second IPC request did not reach control serialization')
        release.set()
        self.assertTrue(json.loads(fixture.finish(first))['ok'])
        self.assertTrue(json.loads(fixture.finish(second))['ok'])
        self.assertEqual(fixture.bd.connect_sidecar.call_count, fixture.cfg.max_retries,
                         'A press during the active transition queued a second retry budget')
        self.assertIsNone(fixture.engine.runtime.user_override)

    def test_manual_after_auto_save_preserves_latest_config_and_status_revision(self):
        fixture = self.fixture
        fixture.make_state(fixtures.OperationMode.MANUAL_ONLY)
        fixture.engine.evaluate(async_transition=False)
        side_effects, entered, release = fixture.block(fixture.daemon._run_config_side_effects)
        fixture.stack.enter_context(patch.object(fixture.daemon, '_run_config_side_effects', side_effect=side_effects))
        automatic = json.dumps({'command': 'set_mode', 'params': {'mode': 'automatic'},
                                'expected_revision': fixture.cfg.revision})
        older = fixture.start(lambda: fixture.daemon.handle_client_cmd(automatic))
        self.assertTrue(entered.wait(1), 'Automatic config was not saved before the side-effect checkpoint')
        newer = fixture.start(lambda: fixture.daemon.handle_client_cmd(fixture.manual_request()))
        manual = json.loads(fixture.finish(newer, .5))
        self.assertTrue(manual['ok'])
        self.assertFalse(release.is_set(), 'Manual ACK waited for the old mode side effect')
        release.set()
        fixture.finish(older)
        revision = manual['config_revision']
        self.assertEqual(revision, fixture.cfg.revision + 2)
        for config in (fixture.daemon.config, fixture.engine.config, fixture.detector.config):
            self.assertEqual(config.mode, fixtures.OperationMode.MANUAL_ONLY)
            self.assertEqual(config.revision, revision, 'Old side effect replaced the successfully saved Manual config')
        self.assertEqual(fixture.engine._last_snapshot.config_revision, revision)
        self.assertEqual(fixture.engine.runtime.mode, fixtures.OperationMode.MANUAL_ONLY)
        fixture.bd.connect_sidecar.assert_not_called()
        fixture.bd.set_main_display.assert_not_called()

    def test_manual_during_initial_observation_consumes_pending_boot_connection(self):
        fixture = self.fixture
        fixture.make_state(fixtures.OperationMode.MANUAL_ONLY)
        self.assertTrue(fixture.cfg.connect_on_boot)
        observe, entered, release = fixture.block(lambda **_: (fixture.actual, ((), False)))
        fixture.detector.observe.side_effect = observe
        initial = fixture.start(lambda: fixture.engine.evaluate(async_transition=False))
        self.assertTrue(entered.wait(1), 'Initial boot observation did not start')
        response = fixture.finish(fixture.start(lambda: fixture.daemon.handle_client_cmd(fixture.manual_request())), .5)
        self.assertTrue(json.loads(response)['ok'])
        self.assertFalse(release.is_set(), 'Manual ACK waited for the initial boot observation')
        release.set()
        fixture.finish(initial)
        # The next normal observation must not revive the consumed boot attempt.
        fixture.detector.observe.side_effect = lambda **_: (fixture.actual, ((), False))
        fixture.engine.evaluate(async_transition=False)
        self.assertFalse(fixture.daemon.try_boot_connection(time.monotonic() + 30))
        fixture.bd.connect_sidecar.assert_not_called()

        fixture.bd.connect_sidecar.side_effect = fixture.connected
        self.assertTrue(fixture.engine.request_sidecar_connection(async_transition=False))
        fixture.bd.connect_sidecar.assert_called_once_with('TARGET')

    def test_explicit_connection_after_manual_ack_survives_the_cancelled_worker(self):
        fixture = self.fixture
        fixture.make_state(fixtures.OperationMode.MANUAL_ONLY)
        connect, entered, release = fixture.block(lambda _: False)
        fixture.bd.connect_sidecar.side_effect = connect
        old = fixture.start(lambda: fixture.engine.request_sidecar_connection(async_transition=False))
        self.assertTrue(entered.wait(1), 'Old connection did not reach simulated hardware')
        manual = json.loads(fixture.finish(
            fixture.start(lambda: fixture.daemon.handle_client_cmd(fixture.manual_request())), .5))
        self.assertTrue(manual['ok'])
        self.assertFalse(release.is_set())

        waiting = threading.Event()
        fixture.engine._eval_lock = fixtures.ObservedLock(fixture.engine._eval_lock, waiting)
        request = json.dumps({'command': 'connect_ipad', 'expected_revision': manual['config_revision'],
                              'params': {'target_key': fixtures.pairing_key(fixture.cfg.ipad.to_dict())}})
        fresh = fixture.start(lambda: fixture.daemon.handle_client_cmd(request), name='queued-control')
        self.assertTrue(waiting.wait(1), 'Fresh connection did not wait for the old hardware operation')
        fixture.bd.connect_sidecar.side_effect = fixture.connected
        release.set()
        fixture.finish(old)
        self.assertTrue(json.loads(fixture.finish(fresh))['ok'])
        self.assertEqual(fixture.bd.connect_sidecar.call_count, 2,
                         'A fresh request after Manual ACK was coalesced into cancelled work')
        fixture.bd.set_main_display.assert_called_once()


if __name__ == '__main__':
    unittest.main()
