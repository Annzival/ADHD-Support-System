import tempfile
import unittest
from pathlib import Path

from agent_core.core import Core


class GoldenPath(unittest.TestCase):
    def test_ex01_completion_is_durable_and_releases_the_slot(self):
        with tempfile.TemporaryDirectory() as directory:
            now = [1000.0]
            path = Path(directory) / 'state.sqlite3'
            core = Core(path, clock=lambda: now[0])
            core.seed_fixture(confirmed=True, start=1010, duration=60, window_end=2000)
            self.assertEqual(core.snapshot()['sessions'], [])
            now[0] = 1010
            core.tick(desktop_online=True)
            intervention = core.snapshot()['interventions'][0]
            core.command('delivery_receipt', 'delivery:arrangement-a', 1,
                         {'delivered': True}, 'receipt-1')
            result = core.command('start', intervention['id'], intervention['version'], {}, 'start-1')
            state = core.snapshot()
            self.assertEqual(len(state['sessions']), 1)
            self.assertEqual(state['checkpoints'][0]['due_at'], 1070)
            self.assertEqual(state['checkpoints'][0]['session_id'], result['session_id'])
            session = state['sessions'][0]
            core.command('report_complete', session['id'], session['version'], {}, 'complete-1')
            self.assertEqual(core.snapshot()['sessions'][0]['status'], 'awaiting_closure')
            core.command('skip_closure', session['id'], 2, {}, 'closure-1')
            state = Core(path, clock=lambda: now[0]).snapshot()
            self.assertEqual(state['sessions'][0]['status'], 'ended')
            self.assertEqual(state['evidence'][0]['result'], 'completed')
            self.assertIsNone(state['evidence'][0]['actual_duration_seconds'])
            self.assertEqual(state['actions'][0]['status'], 'completed')
            self.assertEqual(state['active_session'], None)

    def make_core(self, directory, duration=60):
        now = [1010.0]
        path = Path(directory) / 'state.sqlite3'
        core = Core(path, clock=lambda: now[0])
        core.seed_fixture(confirmed=True, start=1010, duration=duration, window_end=2000)
        core.tick(desktop_online=True)
        return core, now, path

    def test_ex02_open_cancel_and_missing_confirmation_preserve_pending_context(self):
        from agent_core.core import Rejected
        with tempfile.TemporaryDirectory() as directory:
            core, now, path = self.make_core(directory, duration=None)
            original = core.snapshot()
            # Opening and cancelling are read-only client actions.
            self.assertEqual(core.snapshot(), original)
            with self.assertRaisesRegex(Rejected, 'duration_confirmation_required'):
                core.command('start', 'intervention:arrangement-a', 1, {}, 'missing')
            self.assertEqual(core.snapshot(), original)
            result = core.command('start', 'intervention:arrangement-a', 1,
                                  {'duration_seconds': 120, 'duration_confirmed': True}, 'confirmed')
            self.assertEqual(result['due_at'], 1130)
            self.assertEqual(len(core.snapshot()['sessions']), 1)

    def test_ses02_complete_before_or_after_checkpoint_finish_or_skip(self):
        for after_checkpoint in (False, True):
            for closure in ('skip_closure', 'finish_closure'):
                with self.subTest(after_checkpoint=after_checkpoint, closure=closure), tempfile.TemporaryDirectory() as directory:
                    core, now, path = self.make_core(directory)
                    result = core.command('start', 'intervention:arrangement-a', 1, {}, 'start')
                    if after_checkpoint:
                        now[0] = 1071
                        core.tick(desktop_online=True)
                        self.assertEqual(core.snapshot()['checkpoints'][0]['status'], 'due')
                    core.command('report_complete', result['session_id'], 1, {}, 'complete')
                    state = core.snapshot()
                    self.assertEqual(state['active_session']['status'], 'awaiting_closure')
                    self.assertEqual(state['checkpoints'][0]['status'], 'invalidated')
                    core.command(closure, result['session_id'], 2, {'result': 'completed'}, 'end')
                    self.assertIsNone(core.snapshot()['active_session'])
                    self.assertEqual(len(core.snapshot()['evidence']), 1)

    def test_finish_closure_can_refine_partial_without_overwriting_report(self):
        with tempfile.TemporaryDirectory() as directory:
            core, now, path = self.make_core(directory)
            session = core.command('start', 'intervention:arrangement-a', 1, {}, 'start')['session_id']
            core.command('report_complete', session, 1, {}, 'complete')
            core.command('finish_closure', session, 2, {'result': 'partial', 'actual_duration_seconds': 30}, 'end')
            state = core.snapshot()
            self.assertEqual(state['actions'][0]['status'], 'pending')
            self.assertEqual(state['evidence'][0]['original_report'], 'completed')
            self.assertEqual(state['evidence'][0]['result'], 'partial')

    def test_restart_keeps_same_session_checkpoint_and_awaiting_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            core, now, path = self.make_core(directory)
            session = core.command('start', 'intervention:arrangement-a', 1, {}, 'start')['session_id']
            for phase in ('executing', 'awaiting_closure', 'ended'):
                before = core.snapshot()
                core = Core(path, clock=lambda: now[0])
                self.assertEqual(core.snapshot(), before)
                if phase == 'executing':
                    core.command('report_complete', session, 1, {}, 'complete')
                elif phase == 'awaiting_closure':
                    core.command('skip_closure', session, 2, {}, 'end')
