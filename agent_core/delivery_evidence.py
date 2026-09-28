"""发送许可与设备结果；历史追加与用户操作的版本资格分开校验。"""
import json
import math
import uuid

SCHEMA = """
CREATE TABLE IF NOT EXISTS delivery_permissions (
 attempt TEXT PRIMARY KEY, body TEXT NOT NULL CHECK(json_valid(body))
);
CREATE TABLE IF NOT EXISTS delivery_reports (
 attempt TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL
);
"""


class DeliveryEvidence:
    def command(self, kind, target, version, payload, command_id):
        if kind not in ('delivery_claim', 'delivery_begin', 'delivery_receipt'):
            return super().command(kind, target, version, payload, command_id)
        from .core import encode
        if not isinstance(command_id, str) or not 1 <= len(command_id) <= 160 or type(version) is not int or not isinstance(payload, dict):
            self.reject('invalid_command')
        request = dict(kind=kind, target=target, version=version, payload=payload)

        def apply(db):
            d = self.get(db, 'deliveries', target)
            if kind == 'delivery_claim':
                self.check_host(payload)
                self.sendable(db, d, version, 'pending')
                binding = {k: payload[k] for k in ('core_run', 'host_run', 'instance')}
                permission = dict(binding, permit=str(uuid.uuid4()), attempt=target,
                                  database_id=self.database_id(db), version=version,
                                  target=d['target'], target_kind=d['target_kind'],
                                  target_version=d['target_version'], call=None)
                self.write(db, 'INSERT INTO delivery_permissions VALUES (?,?)', (target, encode(permission)))
                self.change(db, 'deliveries', d, status='claimed')
                return permission, 'delivery_claimed'
            row = db.execute('SELECT body FROM delivery_permissions WHERE attempt=?', (target,)).fetchone()
            if not row:
                self.reject('missing_delivery_permission')
            permission = json.loads(row[0])
            association = payload.get('permission')
            expected = dict(permission, call=None)
            if association != expected or version != permission['version'] + 1:
                self.reject('delivery_association_mismatch')
            if kind == 'delivery_begin':
                self.check_host(permission)
                self.sendable(db, d, version, 'claimed')
                call = payload.get('call')
                if not isinstance(call, str) or not 16 <= len(call) <= 128 or permission['call'] is not None:
                    self.reject('invalid_device_call')
                permission['call'] = call
                self.write(db, 'UPDATE delivery_permissions SET body=? WHERE attempt=?', (encode(permission), target))
                return dict(call=call), 'device_call_authorized'
            if permission['call'] is None or payload.get('call') != permission['call'] or payload.get('source') != 'api_return':
                self.reject('missing_device_call_result')
            if type(payload.get('delivered')) is not bool:
                self.reject('delivery_result_required')
            returned = payload.get('api_return_at')
            if type(returned) not in (float, int) or not math.isfinite(returned):
                self.reject('invalid_device_return_time')
            prior = db.execute('SELECT request,result FROM delivery_reports WHERE attempt=?', (target,)).fetchone()
            if prior:
                if prior['request'] != encode(request):
                    self.reject('conflicting_device_report')
                return json.loads(prior['result']), None
            # Causal order: an API result received while this context is still current
            # precedes any later successful user command under the same writer lock.
            # Wall-clock magnitudes never establish ordering for a late report.
            context = self.get(db, d['target_kind'], d['target'])
            current = (d['status'] == 'claimed' and context['version'] == d['target_version']
                       and self.clock() < context.get('expires_at', context.get('retention_end', float('inf'))))
            result = dict(delivery_id=target, delivered=payload['delivered'],
                          order='before_response' if current else 'unknown',
                          opportunity='eligible' if current and payload['delivered'] and d['target_kind'] == 'interventions' else 'unknown',
                          api_return_at=returned, received_at=self.clock(), user_seen='unknown')
            if current:
                self.change(db, 'deliveries', d, status='delivered' if payload['delivered'] else 'failed',
                            delivered_at=returned if payload['delivered'] else None,
                            delivery_time_basis='host_api_return', report=result)
                if payload['delivered'] and d['attempt'] == 1 and d['target_kind'] != 'recoveries':
                    self.schedule(db, 'follow:' + d['target'], d['target'], returned + self.policy(db)['grace'], 'followup')
            # A historical report does not rewrite delivery cancellation or domain state.
            self.write(db, 'INSERT INTO delivery_reports VALUES (?,?,?)', (target, encode(request), encode(result)))
            self.check_host(permission)  # This transaction alone owns this qualification.
            return result, 'delivery_result_recorded'
        return self.transact(command_id, request, apply)

    def check_host(self, binding):
        try:
            self.hosts.check(binding)
        except (OSError, ValueError, TypeError):
            self.reject('original_host_instance_unavailable')

    def database_id(self, db):
        return db.execute("SELECT value FROM metadata WHERE key='database_id'").fetchone()[0]

    def sendable(self, db, d, version, status):
        if d['version'] != version or d['status'] != status:
            self.reject('delivery_not_pending')
        context = self.get(db, d['target_kind'], d['target'])
        if context['version'] != d['target_version']:
            self.reject('stale_context')
        if self.clock() >= context.get('expires_at', context.get('retention_end', float('inf'))):
            self.reject('expired_context')
