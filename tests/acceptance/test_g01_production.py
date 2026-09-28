"""ADR-0058：正式 Core、正式 SQLite 事务；无实验库或实验路由。"""
import copy
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from agent_core.core import Core, Rejected
from delivery_fixture import prepare


class ControlledIdentity:
    """确定性存续替身，用于精确控制最后检查前后，不声称 OS 实测。"""
    def __init__(self, pid):
        self.pid, self.instance, self.live = pid, uuid.uuid4().hex, True
        self.fail = False
    def alive(self):
        if self.fail:
            raise OSError('injected_identity_unavailable')
        return self.live
    def close(self):
        self.live = False


class ProductionDelivery(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        core = Core(Path(directory.name) / 'state.sqlite3', clock=lambda: 1000)
        self.addCleanup(core.hosts.close)
        core.hosts.opener = ControlledIdentity
        core.seed_fixture(confirmed=True, start=1000, duration=60, window_end=2000)
        core.tick(desktop_online=True)
        payload = prepare(core)
        identity = core.hosts.bound[payload['permission']['instance']][1]
        return core, payload, identity

    def submit(self, core, payload, command='receipt'):
        return core.command('delivery_receipt', 'delivery:arrangement-a', 2, payload, command)

    def tables(self, core):
        with core.connect() as db:
            return {t: [tuple(r) for r in db.execute('SELECT * FROM ' + t)]
                    for t in ('records', 'events', 'commands', 'delivery_permissions', 'delivery_reports')}

    def respond(self, core):
        core.command('start', 'intervention:arrangement-a', 1, {}, 'start')

    def test_u01_unknown_late_report_preserves_domain_and_old_operations(self):
        for order in ('during_call', 'after_return', 'request_lost', 'window_closed'):
            with self.subTest(order=order):
                core, payload, _ = self.fixture()
                self.respond(core)
                before = core.snapshot()
                result = self.submit(core, payload)
                after = core.snapshot()
                self.assertEqual(result['order'], 'unknown')
                self.assertEqual(result['opportunity'], 'unknown')
                for kind in ('plans','actions','arrangements','interventions','deliveries','sessions','checkpoints','schedules','recoveries'):
                    self.assertEqual(after[kind], before[kind])
                self.assertFalse(core.context('interventions','intervention:arrangement-a',1)['valid'])
                self.assertEqual(len(after['events']), len(before['events']) + 1)
                saved = self.tables(core)
                self.assertEqual(self.submit(core, payload), result)
                self.assertEqual(self.tables(core), saved)

    def test_normal_result_preserves_delivery_time_followup_and_unique_opportunity(self):
        core, payload, _ = self.fixture()
        payload['api_return_at'] = 999.5
        result = self.submit(core, payload)
        self.assertEqual(result['order'], 'before_response')
        self.assertEqual(result['opportunity'], 'eligible')
        state = core.snapshot()
        self.assertEqual(state['deliveries'][0]['delivered_at'], 999.5)
        follow = next(s for s in state['schedules'] if s['kind']=='followup')
        self.assertEqual(follow['due_at'], 1599.5)
        self.respond(core)
        before = self.tables(core)
        self.assertEqual(self.submit(core, payload), result)
        self.assertEqual(self.tables(core), before)
        self.assertEqual(len(before['delivery_reports']), 1)

    def test_u02_duplicates_conflicts_and_wrong_associations(self):
        for field in ('permit','attempt','core_run','host_run','database_id','instance','target_version'):
            with self.subTest(field=field):
                core, payload, _ = self.fixture()
                invalid = copy.deepcopy(payload)
                invalid['permission'][field] = 'wrong'
                before = self.tables(core)
                with self.assertRaises(Rejected): self.submit(core, invalid)
                self.assertEqual(self.tables(core), before)
        for field, value in (('call','wrong'), ('source','click'), ('delivered',None)):
            with self.subTest(field=field):
                core, payload, _ = self.fixture()
                invalid = dict(payload, **{field:value})
                before = self.tables(core)
                with self.assertRaises(Rejected): self.submit(core, invalid)
                self.assertEqual(self.tables(core), before)
        core, payload, _ = self.fixture()
        result = self.submit(core, payload)
        self.assertEqual(self.submit(core, payload, 'different-command'), result)
        self.assertEqual(len(self.tables(core)['delivery_reports']), 1)
        self.assertEqual(len([e for e in core.snapshot()['events'] if e['fact']=='delivery_result_recorded']), 1)
        for command in ('receipt','conflicting-command'):
            before = self.tables(core)
            with self.assertRaises(Rejected): self.submit(core, dict(payload, delivered=False), command)
            self.assertEqual(self.tables(core), before)

    def test_r01_r02_core_host_and_both_restart_database_decides_commit(self):
        for committed in (False, True):
            for restart in ('core','host','both'):
                with self.subTest(committed=committed,restart=restart):
                    core, payload, identity = self.fixture()
                    self.respond(core)
                    result = self.submit(core,payload) if committed else None
                    if restart in ('host','both'): identity.live = False
                    if restart in ('core','both'):
                        core = Core(core.path,clock=lambda:1000)
                        self.addCleanup(core.hosts.close)
                    before = self.tables(core)
                    if committed: self.assertEqual(self.submit(core,payload),result)
                    else:
                        with self.assertRaises(Rejected): self.submit(core,payload)
                    self.assertEqual(self.tables(core),before)

    def test_c01_exit_after_last_check_allows_original_transaction_only(self):
        core, payload, identity = self.fixture()
        self.respond(core)
        def after_check():
            # The actual final check has returned; the transaction is still open.
            identity.live = False
        original = core.check_host
        def check(binding):
            original(binding)
            after_check()
        core.check_host = check
        result = self.submit(core,payload)
        self.assertEqual(result['order'],'unknown')
        self.assertEqual(len(self.tables(core)['delivery_reports']),1)
        self.assertEqual(self.submit(core,payload),result)

    def test_c02_dead_unknown_instance_or_unavailable_rejects_entire_transaction(self):
        for reason in ('dead','unknown','unavailable'):
            with self.subTest(reason=reason):
                core,payload,identity=self.fixture()
                self.respond(core)
                if reason=='dead': identity.live=False
                elif reason=='unavailable': identity.fail=True
                else: core.hosts.bound.clear()
                before=self.tables(core)
                with self.assertRaises(Rejected): self.submit(core,payload)
                self.assertEqual(self.tables(core),before)

    def test_c03_each_write_failure_rolls_back_and_retry_rechecks(self):
        for late in (False,True):
            reference,payload,_=self.fixture()
            if late: self.respond(reference)
            writes=[]
            reference.fault=lambda:writes.append(1)
            self.submit(reference,payload)
            for position in range(1,len(writes)+1):
                with self.subTest(late=late,write=position):
                    core,payload,identity=self.fixture()
                    if late:self.respond(core)
                    before=self.tables(core)
                    count=[0]
                    def fail():
                        count[0]+=1
                        if count[0]==position: raise OSError('injected_write_failure')
                    core.fault=fail
                    with self.assertRaises(OSError):self.submit(core,payload)
                    core.fault=None
                    self.assertEqual(self.tables(core),before)
                    identity.live=False
                    with self.assertRaises(Rejected):self.submit(core,payload)
                    self.assertEqual(self.tables(core),before)
