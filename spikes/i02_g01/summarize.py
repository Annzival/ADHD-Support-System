"""从受控原始输出产生去除完整请求／随机关联内容的证据摘要。"""
import hashlib
import json
import platform
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

raw_path, destination = map(Path, sys.argv[1:])
raw = raw_path.read_text()
rows = [json.loads(line.split('G01_OBSERVATION ', 1)[1]) for line in raw.splitlines() if 'G01_OBSERVATION ' in line]
assert len(rows) == 30 and len({r['case'] for r in rows}) == 30
fields = ('case', 'status', 'input_trace', 'harness_order_evidence', 'decision_reason', 'reason',
          'expected_http', 'actual_http', 'committed_http', 'uncommitted_http', 'api_calls',
          'calls_in_final_host', 'resends', 'saved_reports', 'core_restarted', 'host_restarted',
          'old_and_new_host_differ', 'order', 'opportunity', 'production_snapshot_unchanged_by_report',
          'existing_state_and_report_preserved', 'windows')
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def run(*args):
    return subprocess.check_output(args, text=True).strip()
summary_rows = []
for r in rows:
    row = {k:r[k] for k in fields if k in r}
    if r.get('association'):
        row['association_fields'] = sorted(r['association'])
        row['association_sha256'] = hashlib.sha256(json.dumps(r['association'], sort_keys=True).encode()).hexdigest()
    summary_rows.append(row)
source_paths = ['spikes/i02_g01/server.py', 'spikes/i02_g01/summarize.py', 'desktop/i02_g01_spike_test.go',
                'desktop/delivery.go', 'desktop/bridge.go', 'agent_core/core.py', 'agent_core/lifecycle.py', 'agent_core/transport.py']
artifacts = [raw_path, *[raw_path.parent/name for name in ('g01-registration-gap.txt','g01-regression-python.txt',
             'g01-regression-ui.txt','g01-regression-ui-retry.txt','g01-vet.txt','g01-windows-compile.txt')]]
summary = dict(status='FAIL' if any(r['status']=='FAIL' for r in rows) else 'PASS',
               scope='隔离候选机制；不是 G-01 正式接纳或 I-02 验收',
               source_commit=run('git','rev-parse','HEAD'), product_baseline='f50af6e', main_merge='065e8fb',
               environment=dict(os=platform.system(),architecture=platform.machine(),python=platform.python_version(),sqlite=sqlite3.sqlite_version,
                                go=run('.scratch/toolchain/go/bin/go','version'),device_callback='synthetic',windows='NOT_RUN'),
               cases=summary_rows,counts=dict(total=len(rows),passed=sum(r['status']=='PASS' for r in rows),failed=sum(r['status']=='FAIL' for r in rows)),
               sources_sha256={p:sha(p) for p in source_paths},
               raw_outputs={p.name:dict(sha256=sha(p),bytes=p.stat().st_size) for p in artifacts},
               retention='原始输出在 .scratch/i02-checks/ 受控保存至复审结束；临时库由测试清理',
               limitations=['登记运行标识未覆盖新宿主启动至登记之间的旧请求，失败断言保留',
                            '设备调用为替身；本机序号仅证明控制夹具顺序，所有真实发送顺序／机会资格未知',
                            '独立实验库不证明未来生产许可与领域事务的集成原子性',
                            '没有宿主持久待交回日志；父测试保留重放字节仅是故障输入',
                            '没有验证任意并发下最后一次发送检查与实际 Windows 调用之间的空隙',
                            '同权限恶意进程伪造设备报告不在本实验威胁模型内'])
destination.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary['counts']))
