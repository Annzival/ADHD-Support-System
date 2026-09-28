"""正式 Core 的原生进程对象与受控退出；Windows 运行另行记录。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

from agent_core.core import Core, Rejected

HOST = '''import json,os,sys
run=sys.argv[1]
print(os.getpid(),flush=True)
for line in sys.stdin:
 c=json.loads(line)
 print(json.dumps(c if c.get('host_run')==run and c.get('pid')==os.getpid() else {}),flush=True)
'''


class NativeProcessDelivery(unittest.TestCase):
    def host(self):
        run=uuid.uuid4().hex
        p=subprocess.Popen([sys.executable,'-u','-c',HOST,run],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        self.assertEqual(int(p.stdout.readline()),p.pid)
        def close():
            if p.poll() is None:p.kill()
            p.wait(timeout=5);p.stdin.close();p.stdout.close()
        self.addCleanup(close)
        return p,run

    def core(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        c=Core(Path(directory.name)/'state.sqlite3',clock=lambda:1000)
        self.addCleanup(c.hosts.close)
        c.seed_fixture(confirmed=True,start=1000,duration=60,window_end=2000)
        c.tick(desktop_online=True)
        return c

    def reply(self,p,challenge):
        p.stdin.write(json.dumps(challenge)+'\n');p.stdin.flush()
        return json.loads(p.stdout.readline())

    def prepare(self,c,p,run):
        challenge=c.hosts.challenge(run,p.pid)
        binding=c.hosts.confirm(self.reply(p,challenge))
        permit=c.command('delivery_claim','delivery:arrangement-a',1,binding,'claim')
        call=uuid.uuid4().hex
        c.command('delivery_begin','delivery:arrangement-a',2,dict(permission=permit,call=call),'begin')
        return dict(permission=permit,call=call,source='api_return',delivered=True,api_return_at=1000)

    def test_first_binding_exit_and_challenge_identity(self):
        for branch in ('success','exit_before_open','exit_after_open','wrong_challenge','stale_challenge','replacement_cannot_answer'):
            with self.subTest(branch=branch):
                c=self.core();p,run=self.host()
                if branch=='exit_before_open':
                    p.kill();p.wait(timeout=5)
                    with self.assertRaises(OSError):c.hosts.challenge(run,p.pid)
                    continue
                challenge=c.hosts.challenge(run,p.pid)
                response=self.reply(p,challenge)
                if branch=='exit_after_open':
                    p.kill();p.wait(timeout=5)
                    with self.assertRaises(OSError):c.hosts.confirm(response)
                elif branch=='wrong_challenge':
                    with self.assertRaises(ValueError):c.hosts.confirm(dict(response,nonce='wrong'))
                elif branch=='stale_challenge':
                    c.hosts.challenge(run,p.pid)
                    with self.assertRaises(ValueError):c.hosts.confirm(response)
                elif branch=='replacement_cannot_answer':
                    p.kill();p.wait(timeout=5)
                    replacement,_=self.host()
                    # Even when numeric PID is changed to match the replacement,
                    # the trusted replacement cannot acknowledge the old run.
                    self.assertEqual(self.reply(replacement,dict(challenge,pid=replacement.pid)),{})
                    with self.assertRaises(OSError):c.hosts.confirm(response)
                else:
                    binding=c.hosts.confirm(response);c.hosts.check(binding)
                    with self.assertRaises(ValueError):c.hosts.confirm(response)

    def test_native_exit_before_check_after_check_and_committed_query(self):
        for branch in ('before_check','after_check','committed_response_lost','window_close'):
            with self.subTest(branch=branch):
                c=self.core();p,run=self.host();payload=self.prepare(c,p,run)
                c.command('start','intervention:arrangement-a',1,{},'start')
                before=c.snapshot()
                def submit():return c.command('delivery_receipt','delivery:arrangement-a',2,payload,'receipt')
                if branch=='before_check':
                    p.kill();p.wait(timeout=5);self.host() # replacement runs, never registers
                    with self.assertRaises(Rejected):submit()
                    self.assertEqual(c.snapshot(),before)
                    continue
                if branch=='after_check':
                    original=c.check_host
                    def check(binding):
                        original(binding)
                        p.kill();p.wait(timeout=5);self.host()
                    c.check_host=check
                result=submit()
                if branch=='committed_response_lost':p.kill();p.wait(timeout=5);self.host()
                self.assertEqual(submit(),result)
                after=c.snapshot()
                for kind in ('actions','arrangements','sessions','checkpoints','deliveries','schedules'):
                    self.assertEqual(after[kind],before[kind])
                self.assertEqual(len(after['device_reports']),1)
                self.assertEqual(result['order'],'unknown')

    def test_actual_core_exit_after_check_leaves_no_report_and_new_core_rejects(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        root=Path(directory.name);path=root/'state.sqlite3';payload_file=root/'request.json'
        script='''import json,os,sys,uuid
from pathlib import Path
from agent_core.core import Core
c=Core(sys.argv[1],clock=lambda:1000)
c.seed_fixture(confirmed=True,start=1000,duration=60,window_end=2000)
c.tick(desktop_online=True)
b=c.hosts.confirm(c.hosts.challenge(uuid.uuid4().hex,os.getpid()))
p=c.command('delivery_claim','delivery:arrangement-a',1,b,'claim')
call=uuid.uuid4().hex
c.command('delivery_begin','delivery:arrangement-a',2,dict(permission=p,call=call),'begin')
r=dict(permission=p,call=call,source='api_return',delivered=True,api_return_at=1000)
Path(sys.argv[2]).write_text(json.dumps(r))
original=c.check_host
def check(binding):
 original(binding)
 os._exit(71)
c.check_host=check
c.command('delivery_receipt','delivery:arrangement-a',2,r,'receipt')
'''
        process=subprocess.run([sys.executable,'-c',script,str(path),str(payload_file)],capture_output=True)
        self.assertEqual(process.returncode,71,process.stderr.decode())
        c=Core(path,clock=lambda:1000);self.addCleanup(c.hosts.close)
        self.assertEqual(c.snapshot()['device_reports'],[])
        before=c.snapshot()
        with self.assertRaises(Rejected):
            c.command('delivery_receipt','delivery:arrangement-a',2,json.loads(payload_file.read_text()),'receipt')
        self.assertEqual(c.snapshot(),before)

    def test_registration_to_open_exit_and_pid_reuse_counterexamples(self):
        from agent_core.process_identity import ProcessIdentity
        for reuse in (False,True):
            with self.subTest(pid_reuse_substitute=reuse):
                c=self.core();old,run=self.host();replacement=[]
                def open_after_registration(pid):
                    # Deterministic boundary: Core has received the registration,
                    # but has not opened its OS object yet.
                    old.kill();old.wait(timeout=5)
                    if not reuse:return ProcessIdentity(pid)
                    new,_=self.host();replacement.append(new)
                    return ProcessIdentity(new.pid) # model the old numeric PID being reused
                c.hosts.opener=open_after_registration
                if not reuse:
                    with self.assertRaises(OSError):c.hosts.challenge(run,old.pid)
                else:
                    challenge=c.hosts.challenge(run,old.pid)
                    # Model numeric PID equality separately; old run remains old.
                    response=self.reply(replacement[0],dict(challenge,pid=replacement[0].pid))
                    self.assertEqual(response,{})
                    with self.assertRaises(ValueError):c.hosts.confirm(response)
                self.assertEqual(c.hosts.bound,{})
                self.assertEqual(c.snapshot()['device_reports'],[])
