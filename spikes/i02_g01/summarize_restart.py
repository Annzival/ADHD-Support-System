"""第二轮独立摘要；不覆写第一轮报告或机器证据。"""
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
from pathlib import Path

raw_path, target = map(Path, sys.argv[1:])
lines = raw_path.read_text().splitlines()
old = [json.loads(s.split('G01_OBSERVATION ', 1)[1]) for s in lines if 'G01_OBSERVATION ' in s]
new = [json.loads(s.split('G01_R2_OBSERVATION ', 1)[1]) for s in lines if 'G01_R2_OBSERVATION ' in s]
assert len(old) == len({r['case'] for r in old}) == 30
assert len(new) == len({r['case'] for r in new}) == 8

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def run(*args):
    return subprocess.check_output(args, text=True).strip()
def counts(rows):
    return dict(total=len(rows), passed=sum(r['status']=='PASS' for r in rows), failed=sum(r['status']=='FAIL' for r in rows))
fields = ('case','status','input_trace','expected_http','actual_http','saved_reports','core_restarted',
          'host_restarted','api_calls','resends','reason','decision_reason','order','opportunity',
          'production_snapshot_unchanged_by_report','existing_state_and_report_preserved','windows')
old = [{k:r[k] for k in fields if k in r} for r in old]
source_paths = ['spikes/i02_g01/server.py','spikes/i02_g01/process_identity.py','spikes/i02_g01/summarize_restart.py',
                'desktop/i02_g01_spike_test.go','desktop/i02_g01_restart_test.go',
                'agent_core/core.py','agent_core/lifecycle.py','agent_core/transport.py','desktop/bridge.go','desktop/delivery.go']
outputs = ['g01-r2-complete-go.txt','g01-r2-final-go.txt','g01-r2-original30.txt','g01-r2-new8.txt','g01-r2-python.txt','g01-r2-ui.txt','g01-r2-vet.txt','g01-r2-windows-compile.txt']
historical = ['docs/implementation/results/i02-g01-verification.md','docs/implementation/results/i02-g01-verification.json']
summary = dict(status='FAIL' if any(r['status']=='FAIL' for r in old+new) else 'PASS',
               scope='第二轮隔离机制复验；不代表生产事务或 I-02 验收',
               source_commit=run('git','rev-parse','HEAD'), main_handoff_merge='ebce4e1', prior_evidence_commit='eb3863b',
               environment=dict(os=platform.system(),kernel=platform.release(),architecture=platform.machine(),
                                python=platform.python_version(),sqlite=sqlite3.sqlite_version,go=run('.scratch/toolchain/go/bin/go','version'),
                                native_process_observation='Linux pidfd_open + poll(0)',windows='NOT_RUN'),
               original_30=dict(counts=counts(old),cases=old),new_8=dict(counts=counts(new),cases=new),
               sources_sha256={p:sha(p) for p in source_paths},historical_evidence_sha256={p:sha(p) for p in historical},
               raw_outputs={n:dict(sha256=sha(raw_path.parent/n),bytes=(raw_path.parent/n).stat().st_size) for n in outputs},
               primary_sources=[
                   'https://man7.org/linux/man-pages/man2/pidfd_open.2.html',
                   'https://docs.python.org/3.12/library/os.html#os.pidfd_open',
                   'https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess',
                   'https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject',
                   'https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers',
                   'https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process'],
               limits=['句柄身份和退出观测不与 SQLite COMMIT 原子耦合，最后检查后重启的断言失败',
                       '退出观测延迟由事务暂停点控制，cached_exit 延迟是诊断替身，不是生产监视器',
                       'PID 复用分支仅替换实例标签，是确定性替身；真实退出使用 OS 进程终止及等待',
                       '窗口关闭仍是同进程控制事件，不是 Wails 原生关闭；原生 Windows 句柄路径未运行',
                       '运行存续不是通知呈现／阅读依据；API 仍为替身，顺序与机会资格未知',
                       '进程身份在可信宿主登记时打开并持有；未验证恶意 PID 冒充或首次打开之前的 PID 竞争'],
               raw_retention='.scratch/i02-checks/ 受控保留至复审结束；不提交令牌或原始数据库')
target.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(dict(original=counts(old),added=counts(new))))
