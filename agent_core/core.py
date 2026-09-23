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
         'sessions', 'checkpoints', 'evidence', 'schedules', 'packets', 'recoveries', 'corrections', 'decisions')
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
CREATE UNIQUE INDEX IF NOT EXISTS one_current_arrangement ON records (json_extract(body,'$.action_id'))
 WHERE kind='arrangements' AND json_extract(body,'$.status')='scheduled';
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_recovery ON records ((1))
 WHERE kind='recoveries' AND json_extract(body,'$.status') IN ('pending','deferred');
CREATE UNIQUE INDEX IF NOT EXISTS one_packet ON records (json_extract(body,'$.session_id'))
 WHERE kind='packets';
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


from .lifecycle import Lifecycle


class Core(Lifecycle):
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

    def seed_fixture(self, *, confirmed, start, duration, window_end, second_start=None, timezone_offset=None, grace=600, quiet=(), second_version=None):
        if confirmed is not True or not math.isfinite(start) or (window_end is not None and (not math.isfinite(window_end) or window_end <= start)):
            raise Rejected('explicit_development_fixture_confirmation_required')
        if duration is not None and not positive(duration):
            raise Rejected('invalid_duration')
        if not positive(grace) or (timezone_offset is not None and (type(timezone_offset) is not int or not -840 <= timezone_offset <= 840)):
            raise Rejected('invalid_fixture_policy')
        request = dict(target='plan-P', start=start, duration=duration, window_end=window_end, second_start=second_start, timezone_offset=timezone_offset, grace=grace, quiet=quiet, second_version=second_version)

        def seed(db):
            if db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
                raise Rejected('fixture_requires_empty_database')
            self.write(db, "INSERT INTO metadata VALUES ('purpose','isolated_i01_development_fixture')")
            self.write(db, "INSERT INTO metadata VALUES ('policy',?)", (encode(dict(timezone_offset=timezone_offset, grace=grace, quiet=quiet)),))
            self.write(db, "INSERT INTO metadata VALUES ('current_plan',?)", (second_version or "P",))
            self.put(db, 'plans', dict(id='plan-P', version=1, source='I01 synthetic fixture v1',
                                      confirmation='operator_explicit_development_confirmation', immutable_version='P'))
            self.put(db, 'actions', dict(id='action-A', version=1, plan_id='plan-P', plan_version='P',
                                        title='开发验收：在空白文档写下一行测试文字', status='pending'))
            self.put(db, 'arrangements', dict(id='arrangement-a', version=1, action_id='action-A', plan_version='P',
                                             start_at=start, duration_seconds=duration, duration_confirmed=duration is not None,
                                             window_end=window_end, status='scheduled'))
            self.put(db, 'schedules', dict(id='start:arrangement-a', version=1, target='arrangement-a',
                                          due_at=start, status='scheduled', kind='start'))
            if second_version is not None:
                self.put(db, 'plans', dict(id='plan-' + second_version, version=1, source='I02 synthetic multi-version fixture', immutable_version=second_version))
            if second_start is not None:
                # Explicit multi-arrangement test fixture; never scheduled by the desktop.
                self.put(db, 'actions', dict(id='action-B', version=1, plan_id='plan-' + (second_version or 'P'), plan_version=second_version or 'P', title='开发验收：第二个测试行动', status='pending'))
                self.put(db, 'arrangements', dict(id='arrangement-b', version=1, action_id='action-B', plan_version=second_version or 'P', start_at=second_start, duration_seconds=duration, duration_confirmed=duration is not None, window_end=window_end, status='scheduled'))
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
        state['stage'] = 'I02_DEVELOPMENT_ONLY'
        state['foreground'] = self.foreground(state)
        state['current_plan'] = self.current_plan()
        state['unsupported'] = ['late_delivery_result_pending_G01', 'plan_import']
        return state
