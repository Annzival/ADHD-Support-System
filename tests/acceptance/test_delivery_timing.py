"""P2 定向反例：只使用可控时间，不修改操作系统时钟。"""
import tempfile
import unittest
from pathlib import Path
from agent_core.core import Core
from delivery_fixture import prepare


class DeliveryTiming(unittest.TestCase):
    def test_wall_clock_alone_is_not_elapsed_evidence(self):
        for name,entry,old_seconds in [('forward_jump',1610,610),('backward_but_positive',1100,100),('missing_basis',1010,10)]:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as directory:
                now=[1000]
                c=Core(Path(directory)/'state.sqlite3',clock=lambda:now[0])
                self.addCleanup(c.hosts.close)
                c.seed_fixture(confirmed=True,start=1000,duration=60,window_end=5000)
                c.tick(desktop_online=True)
                payload=prepare(c)
                payload.pop('elapsed',None)
                c.command('delivery_receipt','delivery:arrangement-a',2,payload,'receipt')
                now[0]=entry
                c.command('start','intervention:arrangement-a',1,{},'start')
                metric=c.snapshot()['delivery_metrics'][0]
                print('P2_COUNTEREXAMPLE',name,'wall_difference',old_seconds,'actual_metric',metric,flush=True)
                self.assertEqual(metric['opportunity_count'],1)
                self.assertTrue(metric['entered'])
                self.assertIsNone(metric['response_latency_seconds'])
                self.assertEqual(metric['response_level'],'unknown')

    def fixture(self, directory):
        wall, ticks = [1000], [100000]
        c=Core(Path(directory)/'state.sqlite3',clock=lambda:wall[0],
               elapsed_clock=lambda:dict(clock='controlled_test',ticks=ticks[0],frequency=1000))
        self.addCleanup(c.hosts.close)
        c.seed_fixture(confirmed=True,start=1000,duration=60,window_end=10000)
        c.tick(desktop_online=True)
        return c,wall,ticks

    def save(self,c,payload):
        return c.command('delivery_receipt','delivery:arrangement-a',2,payload,'receipt')

    def enter(self,c):
        c.command('start','intervention:arrangement-a',1,{},'start')
        return c.snapshot()['delivery_metrics'][0]

    def test_elapsed_normal_boundaries_and_wall_jumps(self):
        cases=[('zero',0,0,'immediate'),('within',599,599,'immediate'),
               ('boundary',600,600,'immediate'),('outside',601,601,'delayed'),
               ('forward_jump',10,610,'immediate'),('backward_positive',700,100,'delayed')]
        for name,seconds,wall_delta,level in cases:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as directory:
                c,wall,ticks=self.fixture(directory)
                payload=prepare(c)
                original=self.save(c,payload)
                wall[0]+=wall_delta
                ticks[0]+=seconds*1000
                metric=self.enter(c)
                self.assertEqual(metric['response_latency_seconds'],seconds)
                self.assertEqual(metric['response_level'],level)
                self.assertEqual(metric['opportunity_count'],1)
                self.assertTrue(metric['entered'])
                self.assertEqual(self.save(c,payload),original)
                self.assertEqual(len(c.snapshot()['device_reports']),1)
                self.assertEqual(c.snapshot()['delivery_metrics'],[metric])
                print('P2_ELAPSED',name,metric,flush=True)

    def test_missing_invalid_or_unbounded_samples_preserve_facts(self):
        for case in ('missing','wrong_clock','wrong_frequency','before_begin','after_receipt',
                     'invalid_ticks','missing_entry','reversed_entry','sampler_failure'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                c,wall,ticks=self.fixture(directory)
                payload=prepare(c)
                if case=='missing': payload.pop('elapsed')
                if case=='wrong_clock': payload['elapsed']['clock']='other'
                if case=='wrong_frequency': payload['elapsed']['frequency']=2
                if case=='before_begin': payload['elapsed']['ticks']-=1
                if case=='after_receipt': payload['elapsed']['ticks']+=1
                if case=='invalid_ticks': payload['elapsed']['ticks']=True
                result=self.save(c,payload)
                self.assertTrue(result['delivered'])
                self.assertTrue(result['counts_opportunity'])
                ticks[0]+=10000
                if case=='missing_entry': c.elapsed_clock=lambda:None
                if case=='reversed_entry': ticks[0]=0
                if case=='sampler_failure':
                    def unavailable(): raise OSError('clock unavailable')
                    c.elapsed_clock=unavailable
                metric=self.enter(c)
                self.assertIsNone(metric['response_latency_seconds'])
                self.assertEqual(metric['response_level'],'unknown')
                self.assertTrue(metric['entered'])
                self.assertEqual(metric['opportunity_count'],1)

    def test_core_restart_does_not_mix_epochs_but_keeps_complete_old_pair(self):
        for entered_before in (False,True):
            with self.subTest(entered_before=entered_before),tempfile.TemporaryDirectory() as directory:
                c,wall,ticks=self.fixture(directory)
                payload=prepare(c)
                result=self.save(c,payload)
                ticks[0]+=10000
                prior=self.enter(c) if entered_before else None
                c.hosts.close()
                restored=Core(Path(directory)/'state.sqlite3',clock=lambda:wall[0],
                              elapsed_clock=lambda:dict(clock='controlled_test',ticks=ticks[0],frequency=1000))
                self.addCleanup(restored.hosts.close)
                self.assertEqual(self.save(restored,payload),result)
                metric=restored.snapshot()['delivery_metrics'][0] if entered_before else self.enter(restored)
                if entered_before: self.assertEqual(metric,prior)
                else:
                    self.assertIsNone(metric['response_latency_seconds'])
                    self.assertTrue(metric['entered'])
                    self.assertEqual(metric['opportunity_count'],1)

    def test_late_unknown_order_never_has_latency(self):
        with tempfile.TemporaryDirectory() as directory:
            c,wall,ticks=self.fixture(directory)
            payload=prepare(c)
            c.command('start','intervention:arrangement-a',1,{},'start')
            ticks[0]+=10000
            result=self.save(c,payload)
            self.assertEqual(result['order'],'unknown')
            self.assertFalse(result['counts_opportunity'])
            self.assertEqual(c.snapshot()['delivery_metrics'],[])

    def test_qpc_tick_ambiguity_does_not_create_boundary_classification(self):
        for delta,known in [(0,False),(1,False),(2,True),(599999,False),(600000,False),(600001,False),(600002,True)]:
            with self.subTest(delta=delta),tempfile.TemporaryDirectory() as directory:
                c,wall,ticks=self.fixture(directory)
                c.elapsed_clock=lambda:dict(clock='windows_qpc_v1',ticks=ticks[0],frequency=1000)
                self.save(c,prepare(c))
                ticks[0]+=delta
                metric=self.enter(c)
                self.assertEqual(metric['response_latency_seconds'] is not None,known)
                self.assertEqual(metric['opportunity_count'],1)
                self.assertTrue(metric['entered'])

    def test_host_replacement_cannot_replace_committed_timing(self):
        from delivery_fixture import bind
        with tempfile.TemporaryDirectory() as directory:
            c,wall,ticks=self.fixture(directory)
            payload=prepare(c)
            original=self.save(c,payload)
            bind(c)  # A different host run; already committed report remains immutable.
            ticks[0]+=10000
            self.assertEqual(self.save(c,payload),original)
            metric=self.enter(c)
            self.assertEqual(metric['response_latency_seconds'],10)
            self.assertEqual(len(c.snapshot()['device_reports']),1)
            self.assertEqual(c.snapshot()['device_reports'][0]['elapsed'],original['elapsed'])
