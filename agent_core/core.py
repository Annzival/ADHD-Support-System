"""I-01 权威状态。时钟和写入故障是测试边界；桌面只调用命令与快照。"""
import json
from contextlib import contextmanager
import math
import sqlite3
import time
import uuid
from pathlib import Path


class Rejected(Exception):
    pass


KINDS = ('plans', 'actions', 'arrangements', 'interventions', 'deliveries',
         'sessions', 'checkpoints', 'evidence', 'schedules')
SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
 kind TEXT NOT NULL, id TEXT PRIMARY KEY, version INTEGER NOT NULL,
 body TEXT NOT NULL CHECK(json_valid(body))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session ON records ((1))
 WHERE kind='sessions' AND json_extract(body,'$.status') IN ('executing','awaiting_closure');
CREATE UNIQUE INDEX IF NOT EXISTS one_intervention ON records (json_extract(body,'$.arrangement_id'))
 WHERE kind='interventions';
CREATE UNIQUE INDEX IF NOT EXISTS one_checkpoint ON records (json_extract(body,'$.session_id'))
 WHERE kind='checkpoints' AND json_extract(body,'$.status') IN ('scheduled','due');
CREATE UNIQUE INDEX IF NOT EXISTS one_evidence ON records (json_extract(body,'$.session_id'))
 WHERE kind='evidence';
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT NOT NULL UNIQUE,
 fact TEXT NOT NULL, target TEXT NOT NULL, occurred_at REAL NOT NULL, body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS commands (
 id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= 86400


class Core:
    def __init__(self, path, clock=time.time, fault=None):
        self.path, self.clock, self.fault = Path(path), clock, fault
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('database_id',?)", (str(uuid.uuid4()),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    def write(self, db, sql, values=()):
        db.execute(sql, values)
        if self.fault:
            self.fault()

    def put(self, db, kind, record):
        self.write(db, 'INSERT INTO records VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET version=excluded.version,body=excluded.body',
                   (kind, record['id'], record['version'], encode(record)))

    def get(self, db, kind, identity):
        row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, identity)).fetchone()
        if not row:
            raise Rejected('unknown_context')
        return json.loads(row[0])

    def rows(self, db, kind):
        return [json.loads(row[0]) for row in db.execute('SELECT body FROM records WHERE kind=? ORDER BY id', (kind,))]

    def change(self, db, kind, record, **fields):
        self.put(db, kind, dict(record, **fields, version=record['version'] + 1))

    def transact(self, command_id, request, operation):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                prior = db.execute('SELECT request,result FROM commands WHERE id=?', (command_id,)).fetchone()
                if prior:
                    if prior['request'] != encode(request):
                        raise Rejected('command_id_reused_with_different_request')
                    db.rollback()
                    return json.loads(prior['result'])
                result, fact = operation(db)
                self.write(db, 'INSERT INTO events(command_id,fact,target,occurred_at,body) VALUES (?,?,?,?,?)',
                           (command_id, fact, request['target'], self.clock(), encode(result)))
                self.write(db, 'INSERT INTO commands VALUES (?,?,?)', (command_id, encode(request), encode(result)))
                db.commit()
                return result
            except BaseException:
                db.rollback()
                raise

    def seed_fixture(self, *, confirmed, start, duration, window_end, second_start=None):
        if confirmed is not True or not math.isfinite(start) or not math.isfinite(window_end) or window_end <= start:
            raise Rejected('explicit_development_fixture_confirmation_required')
        if duration is not None and not positive(duration):
            raise Rejected('invalid_duration')
        request = dict(target='plan-P', start=start, duration=duration, window_end=window_end, second_start=second_start)

        def seed(db):
            if db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
                raise Rejected('fixture_requires_empty_database')
            self.write(db, "INSERT INTO metadata VALUES ('purpose','isolated_i01_development_fixture')")
            self.put(db, 'plans', dict(id='plan-P', version=1, source='I01 synthetic fixture v1',
                                      confirmation='operator_explicit_development_confirmation', immutable_version='P'))
            self.put(db, 'actions', dict(id='action-A', version=1, plan_id='plan-P', plan_version='P',
                                        title='开发验收：在空白文档写下一行测试文字', status='pending'))
            self.put(db, 'arrangements', dict(id='arrangement-a', version=1, action_id='action-A', plan_version='P',
                                             start_at=start, duration_seconds=duration, duration_confirmed=duration is not None,
                                             window_end=window_end, status='scheduled'))
            self.put(db, 'schedules', dict(id='start:arrangement-a', version=1, target='arrangement-a',
                                          due_at=start, status='scheduled', kind='start'))
            if second_start is not None:
                # Explicit multi-arrangement test fixture; never scheduled by the desktop.
                self.put(db, 'actions', dict(id='action-B', version=1, plan_id='plan-P', plan_version='P', title='开发验收：第二个测试行动', status='pending'))
                self.put(db, 'arrangements', dict(id='arrangement-b', version=1, action_id='action-B', plan_version='P', start_at=second_start, duration_seconds=duration, duration_confirmed=duration is not None, window_end=window_end, status='scheduled'))
                self.put(db, 'schedules', dict(id='start:arrangement-b', version=1, target='arrangement-b', due_at=second_start, status='scheduled', kind='start'))
            return dict(plan_id='plan-P'), 'development_fixture_confirmed'
        return self.transact('fixture-v1', request, seed)

    def snapshot(self):
        with self.connect() as db:
            db.execute('BEGIN')
            state = {kind: self.rows(db, kind) for kind in KINDS}
            state['events'] = [dict(row) for row in db.execute('SELECT * FROM events ORDER BY sequence')]
            state['command_count'] = db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]
            state['database_id'] = db.execute("SELECT value FROM metadata WHERE key='database_id'").fetchone()[0]
            db.commit()
        state['active_session'] = next((s for s in state['sessions'] if s['status'] in ('executing', 'awaiting_closure')), None)
        state['now'] = self.clock()
        state['stage'] = 'I01_DEVELOPMENT_ONLY'
        state['unsupported'] = ['already_started', 'already_completed', 'reschedule', 'skip_today', 'continue', 'pause', 'recovery', 'automatic_expiry']
        return state

    def tick(self, *, desktop_online):
        state = self.snapshot()
        now = self.clock()
        for schedule in state['schedules']:
            if schedule['status'] != 'scheduled' or schedule['due_at'] > now:
                continue
            kind = 'start_due' if schedule['kind'] == 'start' else 'checkpoint_due'
            try:
                self.command(kind, schedule['target'], 1, {'desktop_online': desktop_online}, 'due:' + schedule['id'])
            except Rejected:
                pass  # An already resolved or expired context must not regain authority.

    def command(self, kind, target, version, payload, command_id):
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 160 or type(version) is not int:
            raise Rejected('invalid_command')
        request = dict(kind=kind, target=target, version=version, payload=payload)
        kinds = {'start_due': 'arrangements', 'checkpoint_due': 'checkpoints',
                 'delivery_receipt': 'deliveries', 'delivery_claim': 'deliveries', 'delivery_expire': 'deliveries', 'start': 'interventions',
                 'report_complete': 'sessions', 'finish_closure': 'sessions', 'skip_closure': 'sessions'}
        if kind not in kinds:
            raise Rejected('operation_not_available_in_i01')

        def apply(db):
            record = self.get(db, kinds[kind], target)
            if record['version'] != version:
                raise Rejected('stale_context')
            now = self.clock()
            if kind == 'start_due':
                if record['status'] != 'scheduled' or now < record['start_at']:
                    raise Rejected('invalid_arrangement')
                intervention_id = 'intervention:' + target
                self.put(db, 'interventions', dict(id=intervention_id, version=1, arrangement_id=target,
                         status='pending', expires_at=record['window_end']))
                # Past-due startup and absent desktop are not delayed active delivery.
                deliver = payload.get('desktop_online') is True and now < record['window_end']
                self.put(db, 'deliveries', dict(id='delivery:' + target, version=1, target=intervention_id,
                         target_kind='interventions', target_version=1, attempt=1,
                         status='pending' if deliver else 'expired', delivered_at=None))
                schedule = self.get(db, 'schedules', 'start:' + target)
                self.change(db, 'schedules', schedule, status='fired')
                return dict(intervention_id=intervention_id), 'start_intervention_created'
            if kind == 'delivery_expire':
                if record['status'] not in ('pending', 'claimed'):
                    raise Rejected('delivery_not_pending')
                self.change(db, 'deliveries', record, status='expired')
                return dict(delivery_id=target), 'delivery_expired'
            if kind in ('delivery_receipt', 'delivery_claim'):
                if record['status'] not in ('pending', 'claimed') or (kind == 'delivery_claim' and record['status'] != 'pending'):
                    raise Rejected('delivery_not_pending')
                context = self.get(db, record['target_kind'], record['target'])
                if context['version'] != record['target_version']:
                    raise Rejected('stale_context')
                if record['target_kind'] == 'interventions' and now >= context['expires_at']:
                    raise Rejected('expired_context')
                if record['target_kind'] == 'checkpoints' and now >= context['retention_end']:
                    raise Rejected('expired_context')
                if kind == 'delivery_claim':
                    self.change(db, 'deliveries', record, status='claimed')
                    return dict(delivery_id=target), 'delivery_claimed'
                if type(payload.get('delivered')) is not bool:
                    raise Rejected('delivery_result_required')
                self.change(db, 'deliveries', record, status='delivered' if payload['delivered'] else 'failed',
                            delivered_at=now if payload['delivered'] else None)
                return dict(delivery_id=target), 'delivery_result_recorded'
            if kind == 'start':
                arrangement = self.get(db, 'arrangements', record['arrangement_id'])
                action = self.get(db, 'actions', arrangement['action_id'])
                if record['status'] != 'pending' or now >= record['expires_at'] or arrangement['status'] != 'scheduled' or action['status'] != 'pending':
                    raise Rejected('expired_or_resolved_context')
                if any(s['status'] in ('executing', 'awaiting_closure') for s in self.rows(db, 'sessions')):
                    raise Rejected('active_session_exists')
                duration = arrangement['duration_seconds'] if arrangement['duration_confirmed'] else None
                if duration is None:
                    duration = payload.get('duration_seconds')
                    if payload.get('duration_confirmed') is not True or not positive(duration):
                        raise Rejected('duration_confirmation_required')
                if now + duration >= arrangement['window_end']:
                    raise Rejected('checkpoint_outside_development_window')
                identity = str(uuid.uuid4())
                checkpoint = 'checkpoint:' + identity
                self.put(db, 'sessions', dict(id=identity, version=1, action_id=action['id'],
                         arrangement_id=arrangement['id'], plan_version=arrangement['plan_version'],
                         intervention_id=target, status='executing', entered_at=now, entry_source='start_now',
                         actual_started_at=None, actual_ended_at=None, report=None))
                self.put(db, 'checkpoints', dict(id=checkpoint, version=1, session_id=identity,
                         due_at=now + duration, status='scheduled', retention_end=arrangement['window_end']))
                self.put(db, 'schedules', dict(id='check:' + identity, version=1, target=checkpoint,
                         due_at=now + duration, status='scheduled', kind='checkpoint'))
                self.change(db, 'arrangements', arrangement, status='executing')
                self.change(db, 'interventions', record, status='resolved')
                self.cancel_deliveries(db, target)
                return dict(session_id=identity, checkpoint_id=checkpoint, due_at=now + duration), 'execution_session_started'
            if kind == 'checkpoint_due':
                session = self.get(db, 'sessions', record['session_id'])
                if session['status'] != 'executing' or record['status'] != 'scheduled' or now < record['due_at'] or now >= record['retention_end']:
                    raise Rejected('invalid_checkpoint')
                self.change(db, 'checkpoints', record, status='due')
                schedule = self.get(db, 'schedules', 'check:' + session['id'])
                self.change(db, 'schedules', schedule, status='fired')
                self.put(db, 'deliveries', dict(id='delivery:' + target, version=1, target=target,
                         target_kind='checkpoints', target_version=2, attempt=1, delivered_at=None,
                         status='pending' if payload.get('desktop_online') is True else 'expired'))
                return dict(checkpoint_id=target), 'checkpoint_became_due'
            arrangement = self.get(db, 'arrangements', record['arrangement_id'])
            if now >= arrangement['window_end']:
                raise Rejected('expired_context_i02_lifecycle_not_available')
            if kind == 'report_complete':
                if record['status'] != 'executing':
                    raise Rejected('session_not_executing')
                self.change(db, 'sessions', record, status='awaiting_closure', report='completed', reported_at=now)
                for cp in self.rows(db, 'checkpoints'):
                    if cp['session_id'] == target and cp['status'] in ('scheduled', 'due'):
                        self.change(db, 'checkpoints', cp, status='invalidated')
                        self.cancel_deliveries(db, cp['id'])
                schedule = self.get(db, 'schedules', 'check:' + target)
                self.change(db, 'schedules', schedule, status='cancelled')
                return dict(session_id=target), 'completion_reported'
            if record['status'] != 'awaiting_closure':
                raise Rejected('session_not_awaiting_closure')
            result = 'completed' if kind == 'skip_closure' else payload.get('result')
            if result not in ('completed', 'partial'):
                raise Rejected('closure_result_required')
            actual_duration = payload.get('actual_duration_seconds') if kind == 'finish_closure' else None
            if actual_duration is not None and not positive(actual_duration):
                raise Rejected('invalid_actual_duration')
            self.put(db, 'evidence', dict(id='evidence:' + target, version=1, session_id=target,
                     action_id=record['action_id'], arrangement_id=record['arrangement_id'], plan_version=record['plan_version'],
                     result=result, original_report=record['report'], actual_duration_seconds=actual_duration,
                     actual_started_at=None, actual_ended_at=None, recorded_at=now,
                     closure='explicit_skip' if kind == 'skip_closure' else 'confirmed'))
            action = self.get(db, 'actions', record['action_id'])
            if result == 'completed':
                self.change(db, 'actions', action, status='completed')
            self.change(db, 'arrangements', arrangement, status='ended')
            self.change(db, 'sessions', record, status='ended', ended_at=now)
            return dict(session_id=target, result=result), 'execution_session_ended'
        return self.transact(command_id, request, apply)

    def cancel_deliveries(self, db, target):
        for delivery in self.rows(db, 'deliveries'):
            if delivery['target'] == target and delivery['status'] in ('pending', 'claimed'):
                self.change(db, 'deliveries', delivery, status='cancelled')

    def recover(self):
        """旧运行未确认送达的尝试失效，已提交执行状态和检查时间保持不变。"""
        for delivery in self.snapshot()['deliveries']:
            if delivery['status'] in ('pending', 'claimed'):
                self.command('delivery_expire', delivery['id'], delivery['version'], {},
                             'expire:' + delivery['id'])
        self.tick(desktop_online=False)

    def context(self, kind, identity, version):
        state = self.snapshot()
        record = next((r for r in state.get(kind, []) if r['id'] == identity), None)
        valid = record is not None and record['version'] == version
        if record and kind == 'interventions':
            valid = valid and record['status'] == 'pending' and self.clock() < record['expires_at']
        elif record and kind == 'checkpoints':
            valid = valid and record['status'] == 'due' and self.clock() < record['retention_end']
        else:
            valid = False
        return dict(valid=valid, state=state)
