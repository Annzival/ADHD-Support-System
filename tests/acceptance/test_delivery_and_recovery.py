import tempfile
import unittest
from pathlib import Path

from agent_core.core import Core, Rejected


class DeliveryRecovery(unittest.TestCase):
    def test_repeated_ticks_and_receipts_do_not_create_extra_interventions_or_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000]
            core = Core(Path(directory)/'state.sqlite3', clock=lambda: now[0])
            core.seed_fixture(confirmed=True, start=1010, duration=60, window_end=2000)
            core.tick(desktop_online=True)
            self.assertEqual(core.snapshot()['interventions'], [])
            now[0] = 1010
            core.tick(desktop_online=True)
            core.tick(desktop_online=True)
            core.command('delivery_claim', 'delivery:arrangement-a', 1, {}, 'claim')
            core.command('delivery_receipt', 'delivery:arrangement-a', 2, {'delivered': True}, 'receipt')
            before = core.snapshot()
            core.command('delivery_receipt', 'delivery:arrangement-a', 2, {'delivered': True}, 'receipt')
            self.assertEqual(core.snapshot(), before)
            self.assertEqual(len(before['interventions']), 1)
            self.assertEqual(len(before['deliveries']), 1)
            self.assertEqual(before['deliveries'][0]['delivered_at'], 1010)
            self.assertEqual(before['sessions'], [])
            self.assertEqual(before['evidence'], [])

    def test_restart_never_replays_missed_or_unacknowledged_active_delivery(self):
        for already_due in (False, True):
            with self.subTest(already_due=already_due), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)/'state.sqlite3'
                core = Core(path, clock=lambda: 1010)
                core.seed_fixture(confirmed=True, start=1010, duration=60, window_end=2000)
                if already_due:
                    core.tick(desktop_online=True)
                core = Core(path, clock=lambda: 1011)
                core.recover()
                core.tick(desktop_online=True)
                state = core.snapshot()
                self.assertEqual(len([d for d in state['deliveries'] if d['target_kind'] == 'interventions']), 1)
                self.assertEqual(state['deliveries'][0]['status'], 'expired')
                self.assertEqual(state['actions'][0]['status'], 'pending')
                self.assertEqual(state['evidence'], [])
                recovery_delivery = next(d for d in state['deliveries'] if d['target_kind'] == 'recoveries')
                self.assertEqual(recovery_delivery['status'], 'pending')
                core.command('delivery_receipt', recovery_delivery['id'], recovery_delivery['version'], {'delivered': True}, 'recovery-receipt')
                before = core.snapshot()
                core.recover()
                self.assertEqual(core.snapshot(), before)
                # Valid passive context remains actionable; no additional active attempt.
                core.command('start', 'intervention:arrangement-a', 1, {}, 'passive-start')
                self.assertEqual(len(core.snapshot()['sessions']), 1)

    def test_expired_notification_cannot_start_or_claim_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1010]
            core = Core(Path(directory)/'state.sqlite3', clock=lambda: now[0])
            core.seed_fixture(confirmed=True, start=1010, duration=60, window_end=2000)
            core.tick(desktop_online=True)
            now[0] = 2000
            self.assertFalse(core.context('interventions', 'intervention:arrangement-a', 1)['valid'])
            before = core.snapshot()
            with self.assertRaises(Rejected):
                core.command('start', 'intervention:arrangement-a', 1, {}, 'late-start')
            with self.assertRaises(Rejected):
                core.command('delivery_claim', 'delivery:arrangement-a', 1, {}, 'late-delivery')
            self.assertEqual(core.snapshot(), before)
