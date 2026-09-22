import concurrent.futures
import tempfile
import unittest
from pathlib import Path

from agent_core.core import Core, Rejected


class Atomicity(unittest.TestCase):
    def prepared(self, directory, phase):
        path = Path(directory) / 'state.sqlite3'
        core = Core(path, clock=lambda: 1010)
        core.seed_fixture(confirmed=True, start=1010, duration=60, window_end=2000)
        core.tick(desktop_online=True)
        args = ('start', 'intervention:arrangement-a', 1, {}, 'start')
        if phase != 'start':
            session = core.command(*args)['session_id']
            args = ('report_complete', session, 1, {}, 'complete')
            if phase != 'report_complete':
                core.command(*args)
                args = (phase, session, 2, {'result': 'completed'}, 'end')
        return core, path, args

    def test_at01_each_write_failure_rolls_back_entire_transition(self):
        for phase in ('start', 'report_complete', 'finish_closure', 'skip_closure'):
            # Fault after each write, including event/result writes immediately before COMMIT.
            for boundary in range(1, 15):
                with self.subTest(phase=phase, boundary=boundary), tempfile.TemporaryDirectory() as directory:
                    core, path, args = self.prepared(directory, phase)
                    before = core.snapshot()
                    writes = [0]
                    def fail():
                        writes[0] += 1
                        if writes[0] == boundary:
                            raise OSError('simulated storage failure')
                    core.fault = fail
                    try:
                        core.command(*args)
                    except OSError:
                        self.assertEqual(Core(path, clock=lambda: 1010).snapshot(), before)
                    else:
                        self.assertLess(writes[0], boundary)
                        break

    def test_at02_lost_response_restart_and_retry_return_original_result(self):
        for phase in ('start', 'report_complete', 'finish_closure', 'skip_closure'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                core, path, args = self.prepared(directory, phase)
                result = core.command(*args)
                before = core.snapshot()
                core = Core(path, clock=lambda: 1010)
                self.assertEqual(core.command(*args), result)
                self.assertEqual(core.snapshot(), before)
                with self.assertRaisesRegex(Rejected, 'command_id_reused'):
                    core.command(*args[:3], {'changed': True}, args[4])

    def test_at03_competing_commands_cannot_both_succeed(self):
        for phase in ('start', 'report_complete', 'skip_closure'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                core, path, args = self.prepared(directory, phase)
                def submit(number):
                    try:
                        Core(path, clock=lambda: 1010).command(*args[:4], f'competing-{number}')
                        return 'success'
                    except Rejected:
                        return 'rejected'
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                    self.assertEqual(sorted(executor.map(submit, (1, 2))), ['rejected', 'success'])
                self.assertLessEqual(sum(s['status'] in ('executing', 'awaiting_closure') for s in core.snapshot()['sessions']), 1)

    def test_stale_notification_and_unsupported_operations_have_no_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            core, path, args = self.prepared(directory, 'start')
            core.command(*args)
            before = core.snapshot()
            with self.assertRaises(Rejected):
                core.command(*args[:4], 'old-notification')
            for kind in ('pause', 'continue', 'reschedule', 'already_completed'):
                with self.assertRaisesRegex(Rejected, 'operation_not_available'):
                    core.command(kind, args[1], 1, {}, kind)
            self.assertEqual(core.snapshot(), before)

    def test_unique_slot_rejects_second_action_until_closure_and_then_allows_it(self):
        with tempfile.TemporaryDirectory() as directory:
            core = Core(Path(directory) / 'state.sqlite3', clock=lambda: 1010)
            core.seed_fixture(confirmed=True, start=1010, second_start=1010, duration=60, window_end=2000)
            core.tick(desktop_online=True)
            session = core.command('start', 'intervention:arrangement-a', 1, {}, 'start')['session_id']
            for phase in ('executing', 'awaiting_closure'):
                with self.subTest(phase=phase), self.assertRaisesRegex(Rejected, 'active_session_exists'):
                    core.command('start', 'intervention:arrangement-b', 1, {}, 'second-'+phase)
                if phase == 'executing':
                    core.command('report_complete', session, 1, {}, 'complete')
            core.command('skip_closure', session, 2, {}, 'end')
            result = core.command('start', 'intervention:arrangement-b', 1, {}, 'second-after-end')
            self.assertEqual(core.snapshot()['active_session']['id'], result['session_id'])
            self.assertEqual(len(core.snapshot()['evidence']), 1)

    def test_at01_process_exit_before_commit_does_not_leave_partial_state(self):
        import json
        import subprocess
        import sys
        for phase in ('start', 'report_complete', 'finish_closure', 'skip_closure'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                core, path, args = self.prepared(directory, phase)
                before = core.snapshot()
                code = '''
import json, os, sys
from agent_core.core import Core
count = 0
def fail():
    global count
    count += 1
    if count == 2:
        os._exit(71)
Core(sys.argv[1], clock=lambda:1010, fault=fail).command(*json.loads(sys.argv[2]))
'''
                result = subprocess.run([sys.executable, '-c', code, str(path), json.dumps(args)])
                self.assertEqual(result.returncode, 71)
                self.assertEqual(Core(path, clock=lambda: 1010).snapshot(), before)

    def test_at03_finish_and_skip_closure_race_preserves_one_final_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            core, path, args = self.prepared(directory, 'skip_closure')
            def submit(kind):
                try:
                    result = Core(path, clock=lambda: 1010).command(kind, args[1], 2, {'result': 'partial'}, kind)
                    return result['result']
                except Rejected:
                    return 'rejected'
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(submit, ('finish_closure', 'skip_closure')))
            self.assertEqual(results.count('rejected'), 1)
            state = core.snapshot()
            self.assertEqual(len(state['evidence']), 1)
            self.assertIn(state['evidence'][0]['result'], results)
            self.assertIsNone(state['active_session'])
