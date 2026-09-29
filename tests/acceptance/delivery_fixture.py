"""通过正式 Core 协议准备设备调用；替身返回不代表原生呈现。"""
import os
import uuid


def bind(core):
    challenge = core.hosts.challenge(uuid.uuid4().hex, os.getpid())
    assert challenge['pid'] == os.getpid()
    return core.hosts.confirm(challenge)


def prepare(core, target='delivery:arrangement-a', identity='receipt'):
    d = next(d for d in core.snapshot()['deliveries'] if d['id'] == target)
    permit = core.command('delivery_claim', target, d['version'], bind(core), identity + ':claim')
    call = uuid.uuid4().hex
    core.command('delivery_begin', target, d['version'] + 1, dict(permission=permit, call=call), identity + ':begin')
    return dict(permission=permit, call=call, source='api_return', delivered=True, api_return_at=core.clock(), elapsed=core.elapsed_clock())


def receipt(core, target='delivery:arrangement-a', identity='receipt'):
    payload = prepare(core, target, identity)
    return core.command('delivery_receipt', target, payload['permission']['version'] + 1, payload, identity)
