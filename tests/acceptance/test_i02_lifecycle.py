"""B-04 I-02: real SQLite, controlled clocks, write faults and competing commands."""
import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from agent_core.core import Core, Rejected


class LifecycleTests(unittest.TestCase):
    def fixture(self, **options):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        now = [1000.0]; path = Path(directory.name)/'state.sqlite3'
        core = Core(path, clock=lambda:now[0])
        core.seed_fixture(**(dict(confirmed=True,start=1000,duration=60,window_end=4000,grace=30,timezone_offset=480)|options))
        core.tick(desktop_online=True)
        self.addCleanup(lambda:self.invariants(core))
        return core,now,path

    def record(self,c,kind,status=None):
        return next(r for r in c.snapshot()[kind] if status is None or r.get('status')==status)

    def send(self,c,kind,category,status=None,payload=None,identity=None):
        r=self.record(c,category,status)
        return c.command(kind,r['id'],r['version'],payload or {},identity or kind)

    def start(self,c): return self.send(c,'start','interventions','pending')
    def pause(self,c):
        self.start(c);self.send(c,'pause','sessions','executing');self.send(c,'skip_closure','sessions','awaiting_closure')

    def invariants(self,c):
        s=c.snapshot();active=[r for r in s['sessions'] if r['status'] in ('executing','awaiting_closure')]
        self.assertLessEqual(len(active),1)
        for session in s['sessions']:
            cps=[r for r in s['checkpoints'] if r['session_id']==session['id'] and r['status'] in ('scheduled','due')]
            self.assertEqual(len(cps),1 if session['status']=='executing' else 0)
        for cp in s['checkpoints']:
            self.assertIn(cp['session_id'],[x['id'] for x in s['sessions']])
        self.assertEqual(len({e['command_id'] for e in s['events']}),len(s['events']))
        self.assertEqual(s['command_count'],len(s['events']))
        arrangements={a['id']:a for a in s['arrangements']};actions={a['id']:a for a in s['actions']}
        sessions={r['id']:r for r in s['sessions']};checks={r['id']:r for r in s['checkpoints']}
        targets=set(arrangements)|set(checks)|{r['id'] for r in s['interventions']}
        for a in arrangements.values():self.assertEqual(a['plan_version'],actions[a['action_id']]['plan_version'])
        for session in sessions.values():
            self.assertEqual(session['action_id'],arrangements[session['arrangement_id']]['action_id'])
            self.assertEqual(session['plan_version'],arrangements[session['arrangement_id']]['plan_version'])
        for schedule in s['schedules']:
            self.assertIn(schedule['target'],targets)
            if schedule['status']=='scheduled' and schedule['kind']=='checkpoint':self.assertEqual(checks[schedule['target']]['status'],'scheduled')
        for e in s['evidence']:
            self.assertEqual(e['plan_version'],sessions[e['session_id']]['plan_version'])
            self.assertEqual(sessions[e['session_id']]['status'],'ended')
        for packet in s['packets']:
            self.assertEqual(sessions[packet['session_id']]['status'],'ended')
            self.assertEqual(packet['plan_version'],sessions[packet['session_id']]['plan_version'])
            if packet['status']=='used':self.assertEqual(sessions[packet['used_by']]['packet_id'],packet['id'])
        self.assertLessEqual(sum(r['status'] in ('pending','deferred') for r in s['recoveries']),1)
        return s

    def test_ex03_requires_remaining_duration_even_when_estimated(self):
        c,now,path=self.fixture()
        before=c.snapshot()
        with self.assertRaises(Rejected):self.send(c,'already_started','interventions','pending')
        self.assertEqual(c.snapshot(),before)
        self.send(c,'already_started','interventions','pending',dict(duration_confirmed=True,duration_seconds=90))
        s=self.invariants(c);self.assertEqual(s['sessions'][0]['entry_source'],'already_started')
        self.assertIsNone(s['sessions'][0]['actual_started_at']);self.assertEqual(s['checkpoints'][0]['due_at'],1090)

    def test_ex04_retrospective_complete_or_skip_and_partial(self):
        for mode,result in [('skip_closure','completed'),('finish_closure','completed'),('finish_closure','partial')]:
            with self.subTest(mode=mode,result=result):
                c,_,_=self.fixture();self.send(c,'already_completed','interventions','pending')
                s=self.invariants(c);self.assertEqual(s['checkpoints'],[]);self.assertEqual(s['sessions'][0]['entry_source'],'already_completed')
                self.send(c,mode,'sessions','awaiting_closure',dict(result=result))
                s=self.invariants(c);self.assertEqual(s['evidence'][0]['result'],result);self.assertIsNone(s['evidence'][0]['actual_duration_seconds'])

    def test_ex05_reschedule_preserves_old_references(self):
        c,now,_=self.fixture();old=self.record(c,'arrangements').copy()
        result=self.send(c,'reschedule','interventions','pending',dict(confirmed=True,start_at=1200))
        s=self.invariants(c);a=next(x for x in s['arrangements'] if x['id']==result['arrangement_id'])
        self.assertEqual(a['action_id'],old['action_id']);self.assertEqual(a['predecessor_id'],old['id'])
        original=next(x for x in s['arrangements'] if x['id']==old['id']);self.assertEqual(original['start_at'],1000)
        self.assertEqual(original['status'],'rescheduled');self.assertEqual(s['deliveries'][0]['status'],'cancelled')
        now[0]=1200;c.tick(desktop_online=True);self.assertEqual(len(c.snapshot()['interventions']),2)

    def test_ex06_only_current_arrangement_is_skipped(self):
        c,_,_=self.fixture(second_start=2000);before=c.snapshot()
        self.send(c,'skip_today','interventions','pending')
        s=self.invariants(c);self.assertEqual(s['actions'],before['actions']);self.assertEqual(s['plans'],before['plans'])
        self.assertEqual(s['arrangements'][1],before['arrangements'][1]);self.assertEqual(len(s['decisions']),1)
        for category in ('sessions','checkpoints','packets','evidence'):self.assertEqual(s[category],[])

    def receipt(self,c):
        self.send(c,'delivery_receipt','deliveries','pending',dict(delivered=True))

    def test_ex07_08_followup_once_or_expired_no_replay(self):
        for cause in ('normal','quiet','offline','next'):
            with self.subTest(cause=cause):
                c,now,_=self.fixture(quiet=[(1020,1100)] if cause=='quiet' else (),second_start=1020 if cause=='next' else None)
                self.receipt(c);now[0]=1030;c.tick(desktop_online=cause!='offline');c.tick(desktop_online=True)
                s=c.snapshot();old=[d for d in s['deliveries'] if d['target']=='intervention:arrangement-a']
                if cause=='next':self.assertEqual(len(old),1)
                else:self.assertEqual(len(old),2);self.assertEqual(next(d for d in old if d['attempt']==2)['status'],'pending' if cause=='normal' else 'expired')
                now[0]=1150;c.tick(desktop_online=True)
                self.assertEqual(len([d for d in c.snapshot()['deliveries'] if d['target']=='intervention:arrangement-a']),len(old))
                self.assertEqual(c.snapshot()['evidence'],[])

    def test_ex09_deadline_priority_and_earlier_than_grace(self):
        for window,duration,deadline in [(1020,60,1020),(None,60,1060),(None,None,57600)]:
            with self.subTest(window=window,duration=duration):
                c,now,_=self.fixture(window_end=window,duration=duration);self.receipt(c)
                now[0]=deadline;c.tick(desktop_online=True)
                s=self.invariants(c);self.assertEqual(s['interventions'][0]['status'],'expired')
                self.assertFalse(c.context('interventions','intervention:arrangement-a',1)['valid'])
                self.assertEqual(s['evidence'],[]);self.assertEqual(s['actions'][0]['status'],'pending')

    def test_ex10_single_foreground_keeps_old_passive(self):
        for active in (False,True):
            c,now,_=self.fixture(second_start=1100)
            if active:self.start(c)
            now[0]=1100;c.tick(desktop_online=True);s=self.invariants(c)
            self.assertEqual(s['foreground']['kind'],'sessions' if active else 'interventions')
            if not active:self.assertEqual(s['interventions'][0]['status'],'pending');self.assertEqual(s['foreground']['id'],'intervention:arrangement-b')

    def test_ses01_chain_and_retry_and_ses02_pause(self):
        c,now,_=self.fixture();result=self.start(c);now[0]=1060;c.tick(desktop_online=True)
        cp=self.record(c,'checkpoints','due');args=('continue',cp['id'],cp['version'],dict(duration_confirmed=True,duration_seconds=120),'continue')
        r=c.command(*args);before=c.snapshot();self.assertEqual(c.command(*args),r);self.assertEqual(c.snapshot(),before)
        s=self.invariants(c);current=self.record(c,'checkpoints','scheduled');self.assertEqual(current['predecessor_id'],cp['id']);self.assertEqual(current['session_id'],result['session_id'])
        self.send(c,'pause','sessions','executing');s=self.invariants(c);self.assertEqual(s['active_session']['status'],'awaiting_closure')
        with self.assertRaises(Rejected):c.command(*args[:4],'stale')

    def test_ses04_pause_closure_variants_minimal_packet(self):
        for kind in ('finish_closure','skip_closure'):
            c,_,_=self.fixture();self.start(c);self.send(c,'pause','sessions','executing')
            self.send(c,kind,'sessions','awaiting_closure',dict(result='paused'))
            s=self.invariants(c);self.assertIsNone(s['active_session']);self.assertEqual(len(s['packets']),1)
            self.assertIsNone(s['packets'][0]['progress']);self.assertEqual(s['evidence'][0]['result'],'paused')

    def test_ses05_and_rec04_auto_closure_boundaries(self):
        for report in ('pause','report_complete'):
            for window,next_start,deadline in [(1100,None,1100),(1200,1080,1080),(None,None,57600)]:
                with self.subTest(report=report,window=window,next_start=next_start):
                    c,now,path=self.fixture(window_end=window,second_start=next_start);self.start(c);self.send(c,report,'sessions','executing')
                    c.recover();self.assertEqual(c.snapshot()['active_session']['status'],'awaiting_closure')
                    now[0]=deadline;c=Core(path,clock=lambda:now[0]);c.recover();before=c.snapshot();c.recover();self.assertEqual(c.snapshot(),before)
                    s=self.invariants(c);self.assertEqual(s['evidence'][0]['closure'],'automatic_skip');self.assertEqual(len(s['packets']),int(report=='pause'))

    def test_ses06_rec03_unknown_deadline_never_creates_evidence(self):
        for window,deadline in [(1150,1150),(None,57600)]:
            c,now,path=self.fixture(window_end=window);self.start(c)
            c.recover();self.assertEqual(c.snapshot()['checkpoints'][0]['due_at'],1060)
            now[0]=1060;c.tick(desktop_online=True)
            d=self.record(c,'deliveries','pending');c.command('delivery_receipt',d['id'],d['version'],dict(delivered=True),'checkpoint-receipt')
            now[0]=1090;c.tick(desktop_online=True);self.assertEqual(len([d for d in c.snapshot()['deliveries'] if d['attempt']==2]),1)
            now[0]=deadline;c=Core(path,clock=lambda:now[0]);c.recover();s=self.invariants(c)
            self.assertEqual(s['sessions'][0]['status'],'tracking_ended');self.assertEqual(s['evidence'],[]);self.assertEqual(s['packets'],[])

    def test_rec05_06_packet_new_session_and_old_version(self):
        c,now,path=self.fixture(second_start=1200,second_version='Q');self.pause(c)
        packet=self.record(c,'packets');old=self.record(c,'sessions');r=self.record(c,'recoveries','pending')
        result=c.command('resume_packet',r['id'],r['version'],dict(packet_id=packet['id'],duration_confirmed=True,duration_seconds=90),'resume')
        s=self.invariants(c);self.assertNotEqual(result['session_id'],old['id']);self.assertEqual(s['active_session']['plan_version'],'P');self.assertEqual(s['current_plan'],'Q')
        self.assertEqual(s['packets'][0]['used_by'],result['session_id'])
        self.send(c,'pause','sessions','executing',identity='pause2');self.send(c,'skip_closure','sessions','awaiting_closure',identity='close2')
        self.assertEqual(next(p for p in c.snapshot()['packets'] if p['status']=='available')['previous_packet_id'],packet['id'])

    def test_rec06_archive_and_rec07_completed_packet_rejection(self):
        c,now,_=self.fixture(second_start=1100,second_version='Q');self.pause(c);now[0]=1100;c.tick(desktop_online=True)
        r=self.record(c,'recoveries','pending');packet=self.record(c,'packets')
        c.command('archive_packet',r['id'],r['version'],dict(packet_id=packet['id']),'archive')
        self.assertEqual(c.snapshot()['packets'][0]['status'],'archived')
        with self.assertRaises(Rejected):c.command('resume_packet',r['id'],r['version'],dict(packet_id=packet['id'],duration_confirmed=True,duration_seconds=60),'old')
        c,_,_=self.fixture();self.pause(c);e=self.record(c,'evidence');original=e.copy()
        c.command('correct_fact',e['id'],e['version'],dict(result='completed',content='实际已完成',reason='更正测试'),'correction')
        self.assertEqual(c.snapshot()['evidence'][0],original)
        r=self.record(c,'recoveries','pending');packet=self.record(c,'packets')
        with self.assertRaisesRegex(Rejected,'action_completed'):c.command('resume_packet',r['id'],r['version'],dict(packet_id=packet['id'],duration_confirmed=True,duration_seconds=60),'resume')

    def test_rec01_02_08_09_reuse_defer_and_version_invalidation(self):
        c,now,path=self.fixture(second_start=1200);c.recover();r=self.record(c,'recoveries','pending')
        c.command('defer_recovery',r['id'],r['version'],{},'defer');before=c.snapshot();c.recover();self.assertEqual(c.snapshot(),before)
        now[0]=1200;c.tick(desktop_online=True)
        with self.assertRaises(Rejected):c.command('return_previous',r['id'],r['version'],{},'old')
        self.assertEqual(c.snapshot()['sessions'],[])
        now[0]=5000;c.recover();self.assertTrue(all(i['status']=='expired' for i in c.snapshot()['interventions']))
        self.assertEqual(c.snapshot()['actions'][0]['status'],'pending')

    def prepared(self,kind):
        c,now,path=self.fixture(second_start=1100,second_version='Q')
        category='interventions';status='pending';payload={}
        if kind in ('reschedule',):payload=dict(confirmed=True,start_at=1300)
        if kind=='already_started':payload=dict(duration_confirmed=True,duration_seconds=60)
        if kind in ('pause','continue','finish_closure','resume_packet','switch_current'):
            self.start(c);category='sessions';status='executing'
            if kind=='continue':now[0]=1060;c.tick(desktop_online=True);category='checkpoints';status='due';payload=dict(duration_confirmed=True,duration_seconds=60)
            if kind in ('finish_closure','resume_packet'):
                self.send(c,'pause','sessions','executing');status='awaiting_closure';payload=dict(result='paused')
                if kind=='resume_packet':
                    self.send(c,'skip_closure','sessions','awaiting_closure');category='recoveries';status='pending'
                    payload=dict(packet_id=self.record(c,'packets')['id'],duration_confirmed=True,duration_seconds=60)
            if kind=='switch_current':
                now[0]=1100;c.recover();category='recoveries';status='pending';payload=dict(confirmed=True,duration_confirmed=True,duration_seconds=60)
        r=self.record(c,category,status)
        return c,now,path,(kind,r['id'],r['version'],payload,'tested-command')

    def test_at01_02_all_new_joint_writes_and_restart_retry(self):
        for kind in ('already_started','already_completed','reschedule','skip_today','pause','continue','finish_closure','resume_packet','switch_current'):
            boundary=1
            while True:
                with self.subTest(kind=kind,boundary=boundary):
                    c,now,path,args=self.prepared(kind);before=c.snapshot();writes=[0]
                    def fault():
                        writes[0]+=1
                        if writes[0]==boundary:raise OSError('injected write failure')
                    c.fault=fault
                    try:result=c.command(*args)
                    except OSError:self.assertEqual(Core(path,clock=lambda:now[0]).snapshot(),before)
                    else:
                        c=Core(path,clock=lambda:now[0]);after=c.snapshot();self.assertEqual(c.command(*args),result);self.assertEqual(c.snapshot(),after);self.invariants(c);break
                boundary+=1
                self.assertLess(boundary,80)

    def test_at03_competing_different_commands(self):
        for first,second in [('start','reschedule'),('continue','report_complete'),('resume_packet','resume_packet'),('switch_current','report_complete')]:
            c,now,path,args=self.prepared(first)
            if second=='reschedule':other=('reschedule',args[1],args[2],dict(confirmed=True,start_at=1400),'competitor')
            elif second=='report_complete':s=c.snapshot()['active_session'];other=(second,s['id'],s['version'],{},'competitor')
            else:other=(*args[:4],'competitor')
            def run(command):
                try:Core(path,clock=lambda:now[0]).command(*command);return 'success'
                except Rejected:return 'rejected'
            with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(run,[args,other]))
            self.assertEqual(sorted(results),['rejected','success']);self.invariants(c)

    def test_rec10_11_12_switch_cancel_missing_retry_and_old_check(self):
        c,now,path,args=self.prepared('switch_current');before=c.snapshot();old=c.snapshot()['active_session'];cp=self.record(c,'checkpoints')
        for payload in ({},dict(confirmed=True),dict(duration_confirmed=True,duration_seconds=60)):
            with self.assertRaises(Rejected):c.command(*args[:3],payload,'missing')
            self.assertEqual(c.snapshot(),before)
        result=c.command(*args);s=self.invariants(c);self.assertEqual(s['active_session']['id'],result['session_id'])
        ended=next(x for x in s['sessions'] if x['id']==old['id']);self.assertEqual(ended['exit_reason'],'user_selected_switch')
        self.assertEqual(s['evidence'],[]);self.assertEqual(s['packets'],[])
        c=Core(path,clock=lambda:now[0]);c.recover();self.assertEqual(c.command(*args),result)
        self.assertFalse(c.context('checkpoints',cp['id'],cp['version'])['valid']);self.invariants(c)

    def test_at01_new_commands_process_exit_before_commit(self):
        import subprocess,sys,json
        for kind in ('already_started','already_completed','reschedule','skip_today','pause','continue','finish_closure','resume_packet','switch_current'):
            with self.subTest(kind=kind):
                c,now,path,args=self.prepared(kind);before=c.snapshot()
                code='''
import json,os,sys
from agent_core.core import Core
count=0
def fail():
 global count
 count+=1
 if count==2:os._exit(71)
Core(sys.argv[1],clock=lambda:float(sys.argv[2]),fault=fail).command(*json.loads(sys.argv[3]))
'''
                run=subprocess.run([sys.executable,'-c',code,str(path),str(now[0]),json.dumps(args)])
                self.assertEqual(run.returncode,71);self.assertEqual(Core(path,clock=lambda:now[0]).snapshot(),before)

    def test_ses02_pause_before_and_after_checkpoint_and_old_operation_rejected(self):
        for after in (False,True):
            c,now,_=self.fixture(second_start=1000);self.start(c)
            if after:now[0]=1060;c.tick(desktop_online=True)
            cp=self.record(c,'checkpoints');self.send(c,'pause','sessions','executing')
            self.assertEqual(c.snapshot()['active_session']['status'],'awaiting_closure')
            with self.assertRaises(Rejected):c.command('continue',cp['id'],cp['version'],dict(duration_confirmed=True,duration_seconds=60),'old-check')
            with self.assertRaises(Rejected):c.command('already_completed','intervention:arrangement-b',1,{},'second')
            self.invariants(c)

    def test_rec07_used_packet_and_active_session_rejected_without_changes(self):
        c,_,_=self.fixture();self.pause(c);packet=self.record(c,'packets');r=self.record(c,'recoveries','pending')
        args=('resume_packet',r['id'],r['version'],dict(packet_id=packet['id'],duration_confirmed=True,duration_seconds=60),'resume')
        c.command(*args);before=c.snapshot()
        with self.assertRaises(Rejected):c.command(*args[:4],'resume-different-command')
        self.assertEqual(c.snapshot(),before)
        self.assertEqual(c.snapshot()['packets'][0]['status'],'used')

    def test_rec09_each_source_change_invalidates_prior_choice(self):
        for changed in ('session','packet','arrangement','plan'):
            with self.subTest(changed=changed):
                c,now,_=self.fixture(second_start=1100,second_version='Q')
                if changed=='packet':self.pause(c)
                else:self.start(c)
                now[0]=1100;c.recover();r=self.record(c,'recoveries','pending')
                def fixture_change(db):
                    if changed=='plan':c.write(db,"UPDATE metadata SET value='R' WHERE key='current_plan'")
                    else:
                        category={'session':'sessions','packet':'packets','arrangement':'arrangements'}[changed]
                        identity=(r['source']['session_id'] if changed=='session' else r['source']['packet_ids'][0] if changed=='packet' else r['source']['arrangement_id'])
                        record=c.get(db,category,identity);c.change(db,category,record,fixture_revision=True)
                    return {},'synthetic_source_changed'
                c.transact('fixture-change',dict(target='fixture'),fixture_change)
                before=c.snapshot()
                with self.assertRaises(Rejected):c.command('return_previous',r['id'],r['version'],{},'old-recovery')
                self.assertEqual(c.snapshot(),before)
                c.recover();self.assertEqual(next(x for x in c.snapshot()['recoveries'] if x['id']==r['id'])['status'],'invalidated')
                self.invariants(c)

    def test_automatic_transitions_are_atomic_and_idempotent(self):
        for kind in ('expire_start','auto_closure','end_tracking','followup'):
            boundary=1
            while True:
                c,now,path=self.fixture(window_end=1200)
                if kind=='expire_start':r=self.record(c,'interventions');now[0]=1200
                elif kind=='followup':self.receipt(c);r=next(x for x in c.snapshot()['schedules'] if x['kind']=='followup');now[0]=1030
                else:
                    self.start(c)
                    if kind=='auto_closure':self.send(c,'pause','sessions','executing')
                    r=self.record(c,'sessions');now[0]=1200
                args=(kind,r['id'],r['version'],dict(desktop_online=True),'automatic')
                before=c.snapshot();writes=[0]
                def fault():
                    writes[0]+=1
                    if writes[0]==boundary:raise OSError('injected')
                c.fault=fault
                try:result=c.command(*args)
                except OSError:self.assertEqual(Core(path,clock=lambda:now[0]).snapshot(),before)
                else:
                    c=Core(path,clock=lambda:now[0]);saved=c.snapshot();self.assertEqual(c.command(*args),result);self.assertEqual(c.snapshot(),saved);break
                boundary+=1;self.assertLess(boundary,80)

    def test_rec07_available_packet_cannot_start_second_session(self):
        c,_,_=self.fixture(second_start=1000);self.pause(c)
        c.command('start','intervention:arrangement-b',1,{},'start-b')
        r=self.record(c,'recoveries','pending');packet=self.record(c,'packets');before=c.snapshot()
        with self.assertRaisesRegex(Rejected,'active_session_exists'):
            c.command('resume_packet',r['id'],r['version'],dict(packet_id=packet['id'],duration_confirmed=True,duration_seconds=60),'resume-blocked')
        self.assertEqual(c.snapshot(),before)

    def test_rec08_defer_is_quiet_across_restarts(self):
        c,now,path=self.fixture();c.recover();c.tick(desktop_online=True)
        r=self.record(c,'recoveries','pending');c.command('defer_recovery',r['id'],r['version'],{},'defer')
        before=c.snapshot();c=Core(path,clock=lambda:now[0]);c.recover();c.tick(desktop_online=True)
        self.assertEqual(c.snapshot(),before)
        self.assertEqual(c.snapshot()['sessions'],[])

    def test_ses07_correction_and_packet_archive_each_write_failure_and_retry(self):
        for kind in ('correct_fact','archive_packet'):
            boundary=1
            while True:
                c,now,path=self.fixture(second_start=1100,second_version='Q');self.pause(c)
                if kind=='correct_fact':r=self.record(c,'evidence');payload=dict(result='partial',content='更正进展',reason='测试')
                else:
                    now[0]=1100;c.tick(desktop_online=True);r=self.record(c,'recoveries','pending');payload=dict(packet_id=self.record(c,'packets')['id'])
                args=(kind,r['id'],r['version'],payload,'tested-extra');before=c.snapshot();writes=[0]
                def fault():
                    writes[0]+=1
                    if writes[0]==boundary:raise OSError('injected')
                c.fault=fault
                try:result=c.command(*args)
                except OSError:self.assertEqual(Core(path,clock=lambda:now[0]).snapshot(),before)
                else:
                    c=Core(path,clock=lambda:now[0]);saved=c.snapshot();self.assertEqual(c.command(*args),result);self.assertEqual(c.snapshot(),saved);break
                boundary+=1;self.assertLess(boundary,80)


    def test_rec03_return_same_session_cancels_unexecuted_recovery_delivery(self):
        c,now,_=self.fixture();self.start(c);c.recover();c.tick(desktop_online=True)
        r=self.record(c,'recoveries','pending');original=c.snapshot()['active_session'];cp=self.record(c,'checkpoints')
        c.command('return_previous',r['id'],r['version'],{},'return')
        self.assertEqual(c.snapshot()['active_session'],original);self.assertEqual(self.record(c,'checkpoints'),cp)
        self.assertTrue(all(d['status']=='cancelled' for d in c.snapshot()['deliveries'] if d['target']==r['id']))

    def test_ses01_missing_confirmation_keeps_original_checkpoint_and_schedule(self):
        c,now,_=self.fixture();self.start(c);now[0]=1060;c.tick(desktop_online=True)
        cp=self.record(c,'checkpoints','due');before=c.snapshot()
        for payload in ({},dict(duration_seconds=90),dict(duration_confirmed=True)):
            with self.assertRaisesRegex(Rejected,'duration_confirmation_required'):
                c.command('continue',cp['id'],cp['version'],payload,'unconfirmed')
            self.assertEqual(c.snapshot(),before)

    def test_ses03_later_fixture_version_does_not_rewrite_prior_evidence(self):
        for result in ('completed','partial'):
            c,now,path=self.fixture(second_start=1100,second_version='Q')
            # Synthetic pointer changes isolate history; this is not I-03 activation.
            with c.connect() as db:db.execute("UPDATE metadata SET value='P' WHERE key='current_plan'")
            self.start(c);self.send(c,'report_complete','sessions','executing')
            self.send(c,'finish_closure','sessions','awaiting_closure',dict(result=result))
            original=c.snapshot()
            with c.connect() as db:db.execute("UPDATE metadata SET value='Q' WHERE key='current_plan'")
            c=Core(path,clock=lambda:now[0]);c.recover();current=c.snapshot()
            for category in ('plans','actions','arrangements','sessions','checkpoints','evidence'):
                self.assertEqual(current[category],original[category])
            self.assertEqual(current['evidence'][0]['plan_version'],'P')
            self.assertEqual(current['evidence'][0]['original_report'],'completed')
            self.assertEqual(current['current_plan'],'Q')

    def test_rec11_old_switch_cannot_override_explicit_completion_report(self):
        c,_,_,args=self.prepared('switch_current')
        self.send(c,'report_complete','sessions','executing');before=c.snapshot()
        with self.assertRaises(Rejected):c.command(*args)
        self.assertEqual(c.snapshot(),before)
        self.assertEqual(c.snapshot()['active_session']['report'],'completed')
