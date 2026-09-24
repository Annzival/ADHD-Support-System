"""确定性生命周期；所有转换由 Core 的单一事务入口调用。"""
import datetime as dt
import hashlib
import json
import math
import uuid

ACTIVE = ('executing', 'awaiting_closure')
CURRENT = ('scheduled', 'due')
USER_KINDS = {
    'start': 'interventions', 'already_started': 'interventions', 'already_completed': 'interventions',
    'reschedule': 'interventions', 'skip_today': 'interventions',
    'report_complete': 'sessions', 'pause': 'sessions', 'finish_closure': 'sessions', 'skip_closure': 'sessions',
    'continue': 'checkpoints', 'correct_fact': 'evidence',
    'resume_packet': 'recoveries', 'archive_packet': 'recoveries', 'switch_current': 'recoveries',
    'defer_recovery': 'recoveries', 'return_previous': 'recoveries',
    'delivery_claim': 'deliveries', 'delivery_receipt': 'deliveries',
}
SYSTEM_KINDS = {'start_due': 'arrangements', 'checkpoint_due': 'checkpoints',
                'delivery_expire': 'deliveries', 'followup': 'schedules',
                'recovery_present': 'recoveries', 'expire_start': 'interventions', 'auto_closure': 'sessions', 'end_tracking': 'sessions'}


class Lifecycle:
    def reject(self, message):
        from .core import Rejected
        raise Rejected(message)

    def policy(self, db):
        row = db.execute("SELECT value FROM metadata WHERE key='policy'").fetchone()
        return json.loads(row[0]) if row else dict(timezone_offset=None, grace=600, quiet=[])

    def current_plan(self, db=None):
        if db is None:
            with self.connect() as conn:
                return self.current_plan(conn)
        row = db.execute("SELECT value FROM metadata WHERE key='current_plan'").fetchone()
        return row[0] if row else 'P'

    def midnight(self, db, timestamp):
        offset = self.policy(db)['timezone_offset']
        if offset is None:
            local = dt.datetime.fromtimestamp(timestamp)
            return dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time()).timestamp()
        zone = dt.timezone(dt.timedelta(minutes=offset))
        local = dt.datetime.fromtimestamp(timestamp, zone)
        return dt.datetime.combine(local.date() + dt.timedelta(days=1), dt.time(), zone).timestamp()

    def start_end(self, db, a):
        if a['window_end'] is not None:
            return a['window_end']
        if a['duration_seconds'] is not None:
            return a['start_at'] + a['duration_seconds']
        return self.midnight(db, a['start_at'])

    def closure_end(self, db, s):
        a = self.get(db, 'arrangements', s['arrangement_id'])
        bounds = [a['window_end']] if a['window_end'] is not None else []
        bounds += [x['start_at'] for x in self.rows(db, 'arrangements')
                   if x['id'] != a['id'] and x['status'] == 'scheduled' and x['start_at'] > s['entered_at']]
        return min(bounds) if bounds else self.midnight(db, s['reported_at'])

    def active(self, db):
        return next((s for s in self.rows(db, 'sessions') if s['status'] in ACTIVE), None)

    def completed(self, db, action_id):
        # Corrections append facts; never rewrite an original evidence row.
        for e in self.rows(db, 'evidence'):
            if e['action_id'] != action_id:
                continue
            changes = sorted((c for c in self.rows(db, 'corrections') if c['evidence_id'] == e['id']), key=lambda c: c['ordinal'])
            if (changes[-1]['result'] if changes else e['result']) == 'completed':
                return True
        return False

    def duration(self, payload, fallback=None):
        from .core import positive
        if payload.get('duration_confirmed') is True and positive(payload.get('duration_seconds')):
            return payload['duration_seconds']
        if fallback is not None:
            return fallback
        self.reject('duration_confirmation_required')

    def put_new(self, db, category, identity, **fields):
        r = dict(id=identity, version=1, **fields)
        self.put(db, category, r)
        return r

    def schedule(self, db, identity, target, due_at, kind):
        return self.put_new(db, 'schedules', identity, target=target, due_at=due_at, kind=kind, status='scheduled')

    def cancel_deliveries(self, db, target):
        # G-01 proposal is not an enabled historical-result acceptance rule.
        for d in self.rows(db, 'deliveries'):
            if d['target'] == target and d['status'] in ('pending', 'claimed'):
                self.change(db, 'deliveries', d, status='cancelled')
        for s in self.rows(db, 'schedules'):
            if s['target'] == target and s['status'] == 'scheduled':
                self.change(db, 'schedules', s, status='cancelled')

    def invalidate_checks(self, db, session_id):
        for cp in self.rows(db, 'checkpoints'):
            if cp['session_id'] == session_id and cp['status'] in CURRENT:
                self.change(db, 'checkpoints', cp, status='invalidated')
                self.cancel_deliveries(db, cp['id'])

    def allowed_contact(self, db, online):
        return online is True and not any(start <= self.clock() < end for start, end in self.policy(db)['quiet'])

    def foreground(self, state):
        if state['active_session']:
            return dict(kind='sessions', id=state['active_session']['id'])
        pending = [i for i in state['interventions'] if i['status'] == 'pending' and self.clock() < i['expires_at']]
        arrangements = {a['id']: a for a in state['arrangements']}
        if pending:
            i = max(pending, key=lambda x: (arrangements[x['arrangement_id']]['start_at'], x['id']))
            return dict(kind='interventions', id=i['id'])
        return None

    def latest_start(self, db):
        options = [a for a in self.rows(db, 'arrangements') if a['start_at'] <= self.clock() and a['status'] == 'scheduled']
        return max(options, key=lambda a: (a['start_at'], a['id'])) if options else None

    def delivery(self, db, identity, record, target_kind, attempt, online):
        self.put_new(db, 'deliveries', identity, target=record['id'], target_kind=target_kind,
                     target_version=record['version'], attempt=attempt, strength='strong' if attempt == 1 else 'weak',
                     status='pending' if self.allowed_contact(db, online) else 'expired', delivered_at=None)

    def checkpoint(self, db, session, a, duration, predecessor=None):
        now = self.clock()
        due = (session["entered_at"] if predecessor is None else now) + duration
        end = a['window_end'] if a['window_end'] is not None else self.midnight(db, due)
        if due >= end:
            self.reject('checkpoint_outside_development_window')
        identity = 'checkpoint:' + str(uuid.uuid4())
        cp = self.put_new(db, 'checkpoints', identity, session_id=session['id'], due_at=due,
                         retention_end=end, status='scheduled', predecessor_id=predecessor)
        self.schedule(db, 'check:' + identity, identity, due, 'checkpoint')
        return cp

    def new_session(self, db, a, source, duration=None, intervention=None, packet=None):
        if self.active(db):
            self.reject('active_session_exists')
        if self.completed(db, a['action_id']):
            self.reject('action_completed')
        now = self.clock()
        retro = source == 'already_completed'
        s = self.put_new(db, 'sessions', str(uuid.uuid4()), action_id=a['action_id'], arrangement_id=a['id'],
                         plan_version=a['plan_version'], intervention_id=intervention, packet_id=packet,
                         status='awaiting_closure' if retro else 'executing', entered_at=now, entry_source=source,
                         actual_started_at=None, actual_ended_at=None, report='completed' if retro else None,
                         reported_at=now if retro else None)
        cp = None if retro else self.checkpoint(db, s, a, duration)
        self.change(db, 'arrangements', a, status='ended' if retro else 'executing')
        return dict(session_id=s['id'], checkpoint_id=cp['id'] if cp else None, due_at=cp['due_at'] if cp else None)

    def valid_start(self, db, i):
        a = self.get(db, 'arrangements', i['arrangement_id'])
        if i['status'] != 'pending' or self.clock() >= i['expires_at'] or a['status'] != 'scheduled' or self.completed(db, a['action_id']):
            self.reject('expired_or_resolved_context')
        return a

    def valid_session(self, db, s):
        if s['status'] != 'executing':
            self.reject('session_not_executing')
        cp = next(c for c in self.rows(db, 'checkpoints') if c['session_id'] == s['id'] and c['status'] in CURRENT)
        if self.clock() >= cp['retention_end']:
            self.reject('expired_context')
        return cp

    def close(self, db, s, payload, mode):
        from .core import positive
        if s['status'] != 'awaiting_closure':
            self.reject('session_not_awaiting_closure')
        result = s['report'] if mode != 'confirmed' else payload.get('result')
        allowed = ('paused',) if s['report'] == 'paused' else ('completed', 'partial')
        if result not in allowed:
            self.reject('closure_result_required')
        actual = payload.get('actual_duration_seconds') if mode == 'confirmed' else None
        if actual is not None and not positive(actual):
            self.reject('invalid_actual_duration')
        progress = payload.get('progress') if mode == 'confirmed' else None
        if progress is not None and (not isinstance(progress, str) or len(progress) > 2000):
            self.reject('invalid_progress')
        self.put_new(db, 'evidence', 'evidence:' + s['id'], session_id=s['id'], action_id=s['action_id'],
                     arrangement_id=s['arrangement_id'], plan_version=s['plan_version'], result=result,
                     original_report=s['report'], actual_duration_seconds=actual, actual_started_at=None,
                     actual_ended_at=None, recorded_at=self.clock(), closure=mode, progress=progress)
        if result == 'completed':
            action = self.get(db, 'actions', s['action_id'])
            self.change(db, 'actions', action, status='completed')
        if result == 'paused':
            self.put_new(db, 'packets', 'packet:' + s['id'], session_id=s['id'], action_id=s['action_id'],
                         plan_version=s['plan_version'], progress=progress, status='available', used_by=None,
                         previous_packet_id=s.get('packet_id'))
        a = self.get(db, 'arrangements', s['arrangement_id'])
        self.change(db, 'arrangements', a, status='ended')
        self.change(db, 'sessions', s, status='ended', ended_at=self.clock())
        return dict(session_id=s['id'], result=result), 'execution_session_ended'

    def end_tracking(self, db, s, reason):
        self.invalidate_checks(db, s['id'])
        self.change(db, 'sessions', s, status='tracking_ended', exit_reason=reason, tracking_ended_at=self.clock())
        a = self.get(db, 'arrangements', s['arrangement_id'])
        self.change(db, 'arrangements', a, status='tracking_ended')

    def command(self, kind, target, version, payload, command_id):
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 160 or type(version) is not int or not isinstance(payload, dict):
            self.reject('invalid_command')
        kinds = USER_KINDS | SYSTEM_KINDS
        if kind not in kinds:
            self.reject('operation_not_available')
        request = dict(kind=kind, target=target, version=version, payload=payload)
        def apply(db):
            r = self.get(db, kinds[kind], target)
            if r['version'] != version:
                self.reject('stale_context')
            result = self.apply(db, kind, r, payload)
            self.refresh_recovery(db, create=bool(any(r["status"] in ("pending", "deferred") for r in self.rows(db, "recoveries")) or any(p["status"] == "available" for p in self.rows(db, "packets"))))
            return result
        return self.transact(command_id, request, apply)

    def apply(self, db, kind, r, p):
        now = self.clock()
        target = r['id']
        if kind == 'recovery_present':
            if r['status'] != 'pending' or r.get('presented'):
                self.reject('recovery_not_pending')
            self.delivery(db, 'delivery:' + target, r, 'recoveries', 1, p.get('desktop_online'))
            self.change(db, 'recoveries', r, presented=True)
            d = self.get(db, 'deliveries', 'delivery:' + target)
            self.change(db, 'deliveries', d, target_version=r['version'] + 1)
            return dict(recovery_id=target), 'recovery_presentation_requested'
        if kind == 'start_due':
            if r['status'] != 'scheduled' or now < r['start_at']:
                self.reject('invalid_arrangement')
            i = self.put_new(db, 'interventions', 'intervention:' + target, arrangement_id=target,
                             status='pending', expires_at=self.start_end(db, r))
            latest = self.latest_start(db)
            online = p.get('desktop_online') and now < i['expires_at'] and not self.active(db) and latest['id'] == target
            self.delivery(db, 'delivery:' + target, i, 'interventions', 1, online)
            schedule = self.get(db, 'schedules', 'start:' + target)
            self.change(db, 'schedules', schedule, status='fired')
            for old in self.rows(db, 'interventions'):
                if old['id'] != i['id']:
                    old_a = self.get(db, 'arrangements', old['arrangement_id'])
                    if (old_a['start_at'], old_a['id']) < (r['start_at'], target):
                        self.cancel_deliveries(db, old['id'])
            return dict(intervention_id=i['id']), 'start_intervention_created'
        if kind in ('delivery_expire', 'delivery_claim', 'delivery_receipt'):
            if r['status'] not in ('pending', 'claimed') or (kind == 'delivery_claim' and r['status'] != 'pending'):
                self.reject('delivery_not_pending')
            if kind == 'delivery_expire':
                self.change(db, 'deliveries', r, status='expired')
                return dict(delivery_id=target), 'delivery_expired'
            context = self.get(db, r['target_kind'], r['target'])
            if context['version'] != r['target_version']:
                self.reject('stale_context')
            limit = context.get('expires_at', context.get('retention_end', float('inf')))
            if now >= limit:
                self.reject('expired_context')
            if kind == 'delivery_claim':
                self.change(db, 'deliveries', r, status='claimed')
                return dict(delivery_id=target), 'delivery_claimed'
            if type(p.get('delivered')) is not bool:
                self.reject('delivery_result_required')
            self.change(db, 'deliveries', r, status='delivered' if p['delivered'] else 'failed', delivered_at=now if p['delivered'] else None)
            if p['delivered'] and r['attempt'] == 1 and r['target_kind'] != 'recoveries':
                self.schedule(db, 'follow:' + r['target'], r['target'], now + self.policy(db)['grace'], 'followup')
            return dict(delivery_id=target), 'delivery_result_recorded'
        if kind == 'followup':
            if r['status'] != 'scheduled' or now < r['due_at']:
                self.reject('invalid_schedule')
            is_start = r['target'].startswith('intervention:')
            category = 'interventions' if is_start else 'checkpoints'
            c = self.get(db, category, r['target'])
            online = p.get('desktop_online')
            if is_start:
                a = self.get(db, 'arrangements', c['arrangement_id'])
                latest = self.latest_start(db)
                online = online and c['status'] == 'pending' and now < c['expires_at'] and latest and latest['id'] == a['id'] and not self.active(db)
            else:
                online = online and c['status'] == 'due' and now < c['retention_end']
            self.delivery(db, 'follow-delivery:' + c['id'], c, category, 2, online)
            self.change(db, 'schedules', r, status='fired')
            return dict(target=c['id']), 'followup_checked'
        if kind == 'expire_start':
            if r['status'] != 'pending' or now < r['expires_at']:
                self.reject('not_expired')
            self.change(db, 'interventions', r, status='expired')
            a = self.get(db, 'arrangements', r['arrangement_id'])
            self.change(db, 'arrangements', a, status='expired_unknown')
            self.cancel_deliveries(db, target)
            return dict(intervention_id=target), 'start_context_expired_unknown'
        if kind in ('start', 'already_started', 'already_completed', 'reschedule', 'skip_today'):
            a = self.valid_start(db, r)
            if kind in ('start', 'already_started', 'already_completed'):
                duration = None if kind == 'already_completed' else self.duration(p, a['duration_seconds'] if kind == 'start' and a['duration_confirmed'] else None)
                result = self.new_session(db, a, 'start_now' if kind == 'start' else kind, duration, target)
                fact = 'completion_reported_retrospectively' if kind == 'already_completed' else 'execution_session_started'
            elif kind == 'reschedule':
                start = p.get('start_at')
                end = p.get('window_end')
                if p.get('confirmed') is not True or type(start) not in (int, float) or not math.isfinite(start) or start <= now:
                    self.reject('specific_time_confirmation_required')
                if end is not None and (type(end) not in (int, float) or not math.isfinite(end) or end <= start):
                    self.reject('invalid_window')
                self.change(db, 'arrangements', a, status='rescheduled')
                new = dict(a, id='arrangement:' + str(uuid.uuid4()), version=1, start_at=start, window_end=end,
                           status='scheduled', predecessor_id=a['id'])
                self.put(db, 'arrangements', new)
                self.schedule(db, 'start:' + new['id'], new['id'], start, 'start')
                result, fact = dict(arrangement_id=new['id']), 'execution_arrangement_rescheduled'
            else:
                self.change(db, 'arrangements', a, status='skipped')
                self.put_new(db, 'decisions', 'skip:' + a['id'], arrangement_id=a['id'], action_id=a['action_id'],
                             decided_at=now, decision='skip_this_arrangement')
                result, fact = dict(arrangement_id=a['id']), 'arrangement_skipped_by_user'
            self.change(db, 'interventions', r, status='resolved')
            self.cancel_deliveries(db, target)
            return result, fact
        if kind == 'checkpoint_due':
            s = self.get(db, 'sessions', r['session_id'])
            if s['status'] != 'executing' or r['status'] != 'scheduled' or now < r['due_at'] or now >= r['retention_end']:
                self.reject('invalid_checkpoint')
            self.change(db, 'checkpoints', r, status='due')
            for schedule in self.rows(db, 'schedules'):
                if schedule['target'] == target and schedule['kind'] == 'checkpoint' and schedule['status'] == 'scheduled':
                    self.change(db, 'schedules', schedule, status='fired')
            self.delivery(db, 'delivery:' + target, self.get(db, 'checkpoints', target), 'checkpoints', 1, p.get('desktop_online'))
            return dict(checkpoint_id=target), 'checkpoint_became_due'
        if kind == 'continue':
            s = self.get(db, 'sessions', r['session_id'])
            self.valid_session(db, s)
            if r['status'] != 'due':
                self.reject('checkpoint_not_due')
            duration = self.duration(p)
            self.change(db, 'checkpoints', r, status='continued')
            self.cancel_deliveries(db, target)
            a = self.get(db, 'arrangements', s['arrangement_id'])
            cp = self.checkpoint(db, s, a, duration, target)
            self.change(db, 'sessions', s, last_continued_at=now)
            return dict(session_id=s['id'], checkpoint_id=cp['id']), 'checkpoint_continued'
        if kind in ('report_complete', 'pause'):
            self.valid_session(db, r)
            self.invalidate_checks(db, target)
            self.change(db, 'sessions', r, status='awaiting_closure', report='completed' if kind == 'report_complete' else 'paused', reported_at=now)
            return dict(session_id=target), 'completion_reported' if kind == 'report_complete' else 'pause_reported'
        if kind in ('finish_closure', 'skip_closure', 'auto_closure'):
            if kind == 'auto_closure' and now < self.closure_end(db, r):
                self.reject('closure_not_due')
            if kind != 'auto_closure' and now >= self.closure_end(db, r):
                self.reject('expired_context')
            return self.close(db, r, p, {'finish_closure':'confirmed', 'skip_closure':'explicit_skip', 'auto_closure':'automatic_skip'}[kind])
        if kind == 'end_tracking':
            if r['status'] != 'executing':
                self.reject('session_not_executing')
            cp = next(c for c in self.rows(db, 'checkpoints') if c['session_id'] == target and c['status'] in CURRENT)
            if now < cp['retention_end']:
                self.reject('tracking_not_due')
            self.end_tracking(db, r, 'unanswered_deadline')
            return dict(session_id=target), 'session_tracking_ended_unknown'
        if kind == 'correct_fact':
            if not isinstance(p.get('reason'), str) or not p['reason'].strip() or not isinstance(p.get('content'), str) or not p['content'].strip() or p.get('result') not in ('completed', 'partial', 'paused', 'unknown'):
                self.reject('explicit_correction_required')
            ordinal = 1 + len(self.rows(db, 'corrections'))
            c = self.put_new(db, 'corrections', str(uuid.uuid4()), evidence_id=target, action_id=r['action_id'],
                             result=p['result'], content=p['content'], reason=p['reason'], recorded_at=now, ordinal=ordinal)
            return dict(correction_id=c['id']), 'execution_fact_corrected'
        return self.recovery_choice(db, kind, r, p)

    def tick(self, *, desktop_online):
        from .core import Rejected
        # Take fresh state between phases; expiry precedes follow-ups and delivery.
        for phase in ('start', 'expiry', 'checkpoint', 'followup'):
            state = self.snapshot()
            tasks = []
            if phase == 'expiry':
                for i in state['interventions']:
                    if i['status'] == 'pending' and self.clock() >= i['expires_at']:
                        tasks.append(('expire_start', i))
                for s in state['sessions']:
                    if s['status'] == 'awaiting_closure':
                        with self.connect() as db:
                            if self.clock() >= self.closure_end(db, s): tasks.append(('auto_closure', s))
                    if s['status'] == 'executing':
                        cp = next(c for c in state['checkpoints'] if c['session_id'] == s['id'] and c['status'] in CURRENT)
                        if self.clock() >= cp['retention_end']: tasks.append(('end_tracking', s))
            else:
                for schedule in sorted(state['schedules'], key=lambda x: (x['due_at'], x['id'])):
                    if schedule['kind'] != phase or schedule['status'] != 'scheduled' or schedule['due_at'] > self.clock(): continue
                    if phase == 'followup': tasks.append(('followup', schedule))
                    else:
                        category = 'arrangements' if phase == 'start' else 'checkpoints'
                        tasks.append(('start_due' if phase == 'start' else 'checkpoint_due', next(r for r in state[category] if r['id'] == schedule['target'])))
            for kind, r in tasks:
                try:
                    self.command(kind, r['id'], r['version'], {'desktop_online':desktop_online}, f'rule:{kind}:{r["id"]}:{r["version"]}')
                except Rejected:
                    pass
        if desktop_online:
            for r in self.snapshot()['recoveries']:
                if r['status'] == 'pending' and not r.get('presented'):
                    try:
                        self.command('recovery_present', r['id'], r['version'], {'desktop_online':True}, 'present:' + r['id'])
                    except Rejected:
                        pass

    def recovery_sources(self, db):
        sessions = [s for s in self.rows(db, 'sessions') if s['status'] in ACTIVE]
        packets = [p for p in self.rows(db, 'packets') if p['status'] == 'available']
        missed = [i for i in self.rows(db, 'interventions') if i['status'] in ('pending', 'expired') and any(d['target'] == i['id'] and d['status'] == 'expired' for d in self.rows(db, 'deliveries'))]
        if not (sessions or packets or missed): return None
        current = self.current_plan(db)
        candidates = [a for a in self.rows(db, 'arrangements') if a['plan_version'] == current and a['status'] == 'scheduled' and a['start_at'] <= self.clock() < self.start_end(db, a) and not self.completed(db, a['action_id'])]
        latest = max(candidates, key=lambda a: (a['start_at'], a['id'])) if candidates else None
        refs = {kind: [[r['id'],r['version']] for r in records] for kind,records in [('sessions',sessions),('packets',packets),('interventions',missed),('arrangements',[latest] if latest else [])]}
        related_actions = {s['action_id'] for s in sessions} | {p['action_id'] for p in packets} | ({latest['action_id']} if latest else set())
        refs['actions'] = [[a['id'],a['version']] for a in self.rows(db,'actions') if a['id'] in related_actions]
        refs['corrections'] = [[c['id'],c['version']] for c in self.rows(db,'corrections') if c['action_id'] in related_actions]
        refs['checkpoints'] = [[c['id'],c['version']] for c in self.rows(db,'checkpoints') if c['session_id'] in {s['id'] for s in sessions} and c['status'] in CURRENT]
        return dict(refs=refs, current_plan=current, session_id=sessions[0]['id'] if sessions else None,
                    packet_ids=[p['id'] for p in packets], previous_intervention_ids=[i['id'] for i in missed],
                    arrangement_id=latest['id'] if latest else None)

    def refresh_recovery(self, db, create, proactive=False):
        from .core import encode
        source = self.recovery_sources(db)
        fingerprint = hashlib.sha256(encode(source).encode()).hexdigest() if source else None
        records = self.rows(db, 'recoveries')
        for r in records:
            if r['status'] in ('pending','deferred') and r['fingerprint'] != fingerprint:
                self.change(db, 'recoveries', r, status='invalidated')
                self.cancel_deliveries(db,r['id'])
        if not create or source is None or any(r['fingerprint'] == fingerprint for r in records): return
        self.put_new(db, 'recoveries', 'recovery:' + str(uuid.uuid4()), status='pending', fingerprint=fingerprint,
                     source=source, created_at=self.clock(), presented=not (proactive or any(r['status']=='pending' and not r.get('presented') for r in records)))

    def recover(self):
        from .core import Rejected
        for d in self.snapshot()['deliveries']:
            if d['status'] in ('pending', 'claimed'):
                try: self.command('delivery_expire',d['id'],d['version'],{},'expire:' + d['id'])
                except Rejected: pass
        self.tick(desktop_online=False)
        from .core import encode
        with self.connect() as db:
            source = self.recovery_sources(db)
        if source is None:
            return
        fingerprint = hashlib.sha256(encode(source).encode()).hexdigest()
        def reconcile(db):
            if hashlib.sha256(encode(self.recovery_sources(db)).encode()).hexdigest() != fingerprint:
                self.reject('recovery_source_changed')
            self.refresh_recovery(db, create=True, proactive=True)
            return dict(source_fingerprint=fingerprint), 'recovery_sources_reconciled'
        self.transact('reconcile:' + fingerprint, dict(target='recovery', fingerprint=fingerprint), reconcile)

    def recovery_choice(self, db, kind, r, p):
        from .core import encode
        current = self.recovery_sources(db)
        if r['status'] not in ('pending','deferred') or current is None or hashlib.sha256(encode(current).encode()).hexdigest() != r['fingerprint']:
            self.reject('stale_recovery_context')
        if kind == 'defer_recovery':
            self.cancel_deliveries(db, r['id'])
            self.change(db, 'recoveries', r, status='deferred')
            return dict(recovery_id=r['id']), 'recovery_deferred'
        if kind == 'return_previous':
            self.cancel_deliveries(db, r['id'])
            self.change(db, 'recoveries', r, status='resolved', choice=kind)
            return dict(session_id=current['session_id'], intervention_ids=current['previous_intervention_ids']), 'recovery_context_selected'
        if kind in ('resume_packet','archive_packet'):
            identity=p.get('packet_id')
            if identity not in current['packet_ids']: self.reject('packet_not_in_context')
            packet=self.get(db,'packets',identity)
            if packet['status']!='available': self.reject('packet_unavailable')
            if kind=='archive_packet':
                if not current['arrangement_id']: self.reject('no_current_arrangement')
                self.change(db,'packets',packet,status='archived')
                result=dict(packet_id=identity)
            else:
                if self.active(db): self.reject('active_session_exists')
                if self.completed(db,packet['action_id']): self.reject('action_completed')
                duration=self.duration(p)
                if any(a['action_id']==packet['action_id'] and a['status']=='scheduled' for a in self.rows(db,'arrangements')): self.reject('action_already_arranged')
                a=self.put_new(db,'arrangements','arrangement:'+str(uuid.uuid4()),action_id=packet['action_id'],plan_version=packet['plan_version'],
                               start_at=self.clock(),window_end=None,duration_seconds=duration,duration_confirmed=True,status='scheduled',packet_id=identity)
                result=self.new_session(db,a,'resume_packet',duration,packet=identity)
                self.change(db,'packets',packet,status='used',used_by=result['session_id'])
        elif kind=='switch_current':
            if p.get('confirmed') is not True: self.reject('switch_confirmation_required')
            duration=self.duration(p)
            if not current['session_id'] or not current['arrangement_id']: self.reject('switch_unavailable')
            old=self.get(db,'sessions',current['session_id']); self.valid_session(db,old)
            a=self.get(db,'arrangements',current['arrangement_id'])
            if a['action_id']==old['action_id']: self.reject('same_action')
            self.end_tracking(db,old,'user_selected_switch')
            result=self.new_session(db,a,'recovery_switch',duration)
            for i in self.rows(db,'interventions'):
                if i['arrangement_id']==a['id'] and i['status']=='pending':
                    self.change(db,'interventions',i,status='resolved'); self.cancel_deliveries(db,i['id'])
        else: self.reject('operation_not_available')
        self.cancel_deliveries(db, r['id'])
        self.change(db,'recoveries',r,status='resolved',choice=kind)
        return result,'recovery_choice_applied'

    def context(self, kind, identity, version):
        state=self.snapshot()
        r=next((x for x in state.get(kind,[]) if x['id']==identity),None)
        valid=r is not None and r['version']==version
        if r and kind=='interventions': valid=valid and r['status']=='pending' and self.clock()<r['expires_at']
        elif r and kind=='checkpoints': valid=valid and r['status']=='due' and self.clock()<r['retention_end']
        elif r and kind=='recoveries': valid=valid and r['status'] in ('pending','deferred')
        else: valid=False
        return dict(valid=bool(valid),state=state)
