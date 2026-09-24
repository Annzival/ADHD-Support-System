"""隔离 G-01 实验端点；生产启动器不会导入本文件或创建实验表。"""
import json
import sqlite3
import sys
import threading
import time
import uuid
from pathlib import Path

from agent_core.core import Core, Rejected, encode
from .process_identity import ProcessIdentity
from agent_core.transport import Server, Handler, read_exact


class Experiment:
    def __init__(self, core, path):
        self.core, self.path = core, path
        self.run = str(uuid.uuid4())
        self.host = None
        self.identities = {}
        self.hook = None
        self.hook_entered = threading.Event()
        self.hook_release = threading.Event()
        self.cached_exit = False
        self.delay_observer = False
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS permits(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY, permit TEXT UNIQUE, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reports(attempt TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS facts(attempt TEXT PRIMARY KEY, kind TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS commands(id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL);
            ''')

    def db(self):
        return sqlite3.connect(self.path)

    def checkpoint(self, name):
        if self.hook == name:
            self.hook_entered.set()
            if not self.hook_release.wait(8):
                raise OSError('barrier_timeout')
            self.hook = None

    def live(self, host, instance):
        identity = self.identities.get(host)
        if identity is None:
            raise Rejected('process_identity_unavailable')
        if identity.instance != instance:
            raise Rejected('process_instance_mismatch')
        try:
            alive = identity.alive()
        except OSError:
            raise Rejected('process_identity_unavailable')
        if not alive:
            if not self.delay_observer:
                self.cached_exit = True
            raise Rejected('host_process_exited')

    def control(self, p):
        # Only diagnostic barriers; intentionally outside transaction lock.
        action = p['action']
        if action == 'arm':
            self.hook = p['point']; self.hook_entered.clear(); self.hook_release.clear()
        elif action == 'release':
            self.hook_release.set()
        elif action == 'delay_observer':
            self.delay_observer = True
        elif action == 'identity_unavailable':
            self.identities[self.host].close()
        elif action == 'reuse_identity':
            # Deterministic replacement of the instance behind the same numeric PID.
            self.identities[self.host].instance = 'synthetic-reused-instance'
        elif action != 'inspect':
            raise Rejected('unknown_control')
        return dict(entered=self.hook_entered.is_set(), cached_exit=self.cached_exit,
                    registered_host=self.host, observer_delayed=self.delay_observer)

    def handle(self, route, p):
        if route == 'control':
            return self.control(p)
        with self.lock, self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if route == 'host':
                host = p['host']
                if host not in self.identities:
                    try:
                        self.identities[host] = ProcessIdentity(p.get('pid'))
                    except (OSError, AttributeError):
                        raise Rejected('process_identity_unavailable')
                identity = self.identities[host]
                if identity.pid != p.get('pid'):
                    raise Rejected('process_instance_mismatch')
                self.live(host, identity.instance)
                self.host = host
                return dict(core=self.run)
            if route == 'advance':
                self.core.clock = lambda: p['now']
                (self.path.parent/'clock.json').write_text(json.dumps(p['now']))
                self.core.tick(desktop_online=True)
                return dict(now=p['now'])
            if route == 'inspect':
                return dict(reports=[json.loads(r[0]) for r in db.execute('SELECT body FROM reports')],
                            commands=db.execute('SELECT count(*) FROM commands').fetchone()[0],
                            facts=db.execute('SELECT count(*) FROM facts').fetchone()[0])
            if route == 'permit':
                if p['host'] != self.host:
                    raise Rejected('host_run_mismatch')
                state = self.core.snapshot()
                d = next((d for d in state['deliveries'] if d['id'] == p['attempt']), None)
                if not d or d['status'] != 'claimed' or not self.core.context(d['target_kind'], d['target'], d['target_version'])['valid']:
                    raise Rejected('not_current_claim')
                permit = dict(id=str(uuid.uuid4()), database=state['database_id'], attempt=d['id'],
                              target=d['target'], target_version=d['target_version'], core=self.run, host=self.host,
                              process_instance=self.identities[self.host].instance)
                # No second licence for the same attempt, including after a restart.
                if any(json.loads(row[0])['attempt'] == d['id'] for row in db.execute('SELECT body FROM permits')):
                    raise Rejected('attempt_already_permitted')
                db.execute('INSERT INTO permits VALUES (?,?)', (permit['id'], encode(permit)))
                return permit
            if route not in ('begin', 'result'):
                raise Rejected('unknown_experiment_route')
            if route == 'result':
                prior = db.execute('SELECT request,result FROM commands WHERE id=?', (p['command'],)).fetchone()
                if prior:
                    if prior[0] != encode(p):
                        raise Rejected('command_content_conflict')
                    return json.loads(prior[1])  # Committed result lookup precedes live-run checks.
            row = db.execute('SELECT body FROM permits WHERE id=?', (p.get('permit', {}).get('id'),)).fetchone()
            if not row or json.loads(row[0]) != p.get('permit'):
                raise Rejected('permit_or_attempt_mismatch')
            permit = json.loads(row[0])
            if permit['core'] != self.run or permit['host'] != self.host:
                raise Rejected('run_boundary_uncommitted')
            if route == 'begin':
                self.live(permit['host'], permit['process_instance'])
                d = next(d for d in self.core.snapshot()['deliveries'] if d['id'] == permit['attempt'])
                if d['status'] != 'claimed' or not self.core.context(d['target_kind'], d['target'], d['target_version'])['valid']:
                    raise Rejected('cancelled_before_call')
                if db.execute('SELECT 1 FROM calls WHERE permit=?', (permit['id'],)).fetchone():
                    raise Rejected('call_already_started')
                db.execute('INSERT INTO calls VALUES (?,?,?)', (p['call'], permit['id'], encode(p)))
                return dict(allowed=True)
            call = db.execute('SELECT body FROM calls WHERE id=? AND permit=?', (p.get('call'), permit['id'])).fetchone()
            if not call or type(p.get('delivered')) is not bool or p.get('source') != 'api_return':
                raise Rejected('no_matching_device_result')
            start = json.loads(call[0])['sequence']
            if type(p.get('sequence')) is not int or p['sequence'] <= start:
                raise Rejected('invalid_host_local_sequence')
            existing = db.execute('SELECT body FROM reports WHERE attempt=?', (permit['attempt'],)).fetchone()
            if existing:
                if json.loads(existing[0])['report'] != {k:v for k,v in p.items() if k != 'command'}:
                    raise Rejected('attempt_result_conflict')
                result = json.loads(existing[0])
            else:
                result = dict(report={k:v for k,v in p.items() if k != 'command'}, order='unknown',
                              opportunity='unknown', precise_latency=None, sent_at=None,
                              received_at=time.time(), user_seen='unknown')
                db.execute('INSERT INTO reports VALUES (?,?)', (permit['attempt'], encode(result)))
                db.execute('INSERT INTO facts VALUES (?,?)', (permit['attempt'], 'device_report_saved_experiment'))
            if p.get('fault_before_commit'):
                raise OSError('injected rollback')
            db.execute('INSERT INTO commands VALUES (?,?,?)', (p['command'], encode(p), encode(result)))
            self.checkpoint('before_live_check')
            self.live(permit['host'], permit['process_instance'])
            self.checkpoint('after_live_check_before_commit')
            return result  # SQLite context manager commits next; OS exit is not serialized with it.


class SpikeHandler(Handler):
    def do_POST(self):
        if not self.path.startswith('/spike/'):
            with self.server.experiment.lock:
                return super().do_POST()
        if not self.authorized():
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 16384:
                raise ValueError()
            p = json.loads(read_exact(self.rfile, size))
            result = self.server.experiment.handle(self.path.removeprefix('/spike/'), p)
            self.reply(200, result)
        except Rejected as e:
            self.reply(409, dict(error=str(e)))
        except (KeyError, TypeError, ValueError):
            self.reply(400, dict(error='invalid_experiment_request'))
        except OSError:
            self.reply(503, dict(error='injected_not_committed'))


if __name__ == '__main__':
    directory, boot = map(Path, sys.argv[1:])
    existed = (directory/'state.sqlite3').exists()
    clock = json.loads((directory/'clock.json').read_text()) if (directory/'clock.json').exists() else 100
    core = Core(directory/'state.sqlite3', clock=lambda:clock)
    if not existed:
        core.seed_fixture(confirmed=True, start=99, duration=60, window_end=1000)
        core.tick(desktop_online=True)
    else:
        core.recover()
    server = Server(core)
    server.RequestHandlerClass = SpikeHandler
    server.experiment = Experiment(core, directory/'experiment.sqlite3')
    server.publish(boot)
    # No real-time scheduler: time and delivery steps are controlled by the harness.
    server.serve_forever()
