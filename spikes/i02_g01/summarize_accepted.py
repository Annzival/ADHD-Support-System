"""ADR-0058 独立摘要；只读取输出，不运行实验，不覆写历史。"""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('raw', type=Path)
parser.add_argument('target', type=Path)
parser.add_argument('--go', default='go')
args = parser.parse_args()
lines = args.raw.read_text(encoding='utf-8-sig').splitlines()

def rows(marker):
    return [json.loads(s.split(marker, 1)[1]) for s in lines if marker in s]

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def run(*args):
    return subprocess.check_output(args, text=True).strip()

def counts(values):
    return dict(total=len(values), passed=sum(v['status'] == 'PASS' for v in values),
                failed=sum(v['status'] != 'PASS' for v in values))

old = rows('G01_OBSERVATION ')
second = rows('G01_R2_OBSERVATION ')
added = rows('G01_ACCEPTED_OBSERVATION ')
assert len(old) == len({r['case'] for r in old}) == 30, 'missing original cases'
assert len(second) == len({r['case'] for r in second}) == 8, 'missing second-round cases'
assert len(added) == len({r['case'] for r in added}) == 10, 'missing new cases'
assert all(r.get('contract') == 'ADR-0058' for r in second+added), 'wrong contract version'
assert 'PASS' in lines and not any(s.startswith('FAIL') or '--- FAIL:' in s for s in lines), 'not a successful complete run'
assert all(r['status'] == 'PASS' for r in old+second+added)
source_commit = run('git', 'rev-parse', 'HEAD')
source_paths = ['spikes/i02_g01/server.py','spikes/i02_g01/process_identity.py','spikes/i02_g01/summarize_accepted.py',
                'desktop/i02_g01_spike_test.go','desktop/i02_g01_restart_test.go','desktop/i02_g01_accepted_test.go',
                'agent_core/core.py','agent_core/transport.py','desktop/bridge.go','desktop/delivery.go']
for path in source_paths:
    committed = subprocess.check_output(['git','show',f'{source_commit}:{path}'])
    assert committed == Path(path).read_bytes(), f'uncommitted source: {path}'
layer = 'Windows process API + isolated HTTP/SQLite; synthetic device' if platform.system() == 'Windows' else 'Linux pidfd + isolated HTTP/SQLite; synthetic device'
for r in old+second+added:
    # No bootstrap tokens, raw response bodies, challenge nonces or local paths.
    assoc = r.pop('association', None)
    if assoc:
        r['association_sha256'] = hashlib.sha256(json.dumps(assoc,sort_keys=True).encode()).hexdigest()
    response = r.pop('response', None)
    if isinstance(response, dict) and 'error' in response:
        r['reason'] = response['error']
    r['source_commit'] = source_commit
    r['contract'] = 'ADR-0058'
    r['evidence_layer'] = layer
    r['expectation_changed_from_ADR0057'] = r['case'] == 'exit_after_check_before_commit'
    if r['expectation_changed_from_ADR0057']:
        r['old_expected_http'] = 409
        r['old_expected_reports'] = 0
    r.setdefault('actual_reports',r.get('saved_reports'))
    if r['case'].startswith('mixed_'):
        r['expected_http'] = {'committed': 200, 'uncommitted': 409}
        r['actual_http'] = {'committed': r['committed_http'], 'uncommitted': r['uncommitted_http']}
    if 'expected_reports' not in r:
        zero = (r.get('binding_only') or r['case'].startswith('wrong_') or
                r['case'] in {'claim_loss_cancel','before_call','click_only','core_before','host_before',
                              'both_before','host_restart_before_registration',
                              'rollback_after_check_then_host_exit','core_restart_after_check_uncommitted'})
        r['expected_reports'] = 0 if zero else 1
    assert r['actual_http'] == r['expected_http'], r['case']
    assert r['actual_reports'] == r['expected_reports'], r['case']
history = ['i02-g01-verification.md','i02-g01-verification.json','i02-g01-restart-revalidation.md',
           'i02-g01-restart-revalidation.json','i02-g01-commit-boundary-research.md']
summary = dict(status='PASS',scope='ADR-0058 隔离候选；不是生产集成或 I-02 验收',
               source_commit=source_commit,contract='ADR-0058',handoff_merge='e383fb4',
               environment=dict(os=platform.system(),kernel=platform.release(),architecture=platform.machine(),
                                python=platform.python_version(),sqlite=sqlite3.sqlite_version,go=run(args.go,'version'),
                                windows='EXECUTED_ISOLATED' if platform.system()=='Windows' else 'NOT_RUN'),
               original_30=dict(counts=counts(old),cases=old),prior_8=dict(counts=counts(second),cases=second),
               added_10=dict(counts=counts(added),cases=added),
               sources_sha256={p:sha(p) for p in source_paths},
               historical_sha256={n:sha(Path('docs/implementation/results')/n) for n in history},
               raw_output=dict(name=args.raw.name,sha256=sha(args.raw),bytes=args.raw.stat().st_size),
               limits=['真实 PID 复用采用确定性替身，真实进程退出独立执行',
                       '首次绑定依赖可信宿主只回应自身新挑战，不抵御同权限恶意伪造或转交',
                       '随机标识不是 OS 证据；依据是打开句柄之后原进程回应的因果链和保留对象的存续',
                       '原生通知/窗口/PC 重启未测，Windows 不可从 Linux 推断',
                       '生产库与实验库分离；无生产同事务集成证明',
                       '检查到提交无时长上限承诺；检查资格不跨回滚或 Core 运行继承'])
args.target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:summary[k]['counts'] for k in ('original_30','prior_8','added_10')}))
