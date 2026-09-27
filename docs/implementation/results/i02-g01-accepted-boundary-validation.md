# G-01：ADR-0058 新契约与原进程实例核验

> Windows 后续进度：操作者报告现有矩阵退出码为 0，摘要曾因纯 CRLF/LF 差异停止。换行修复与**仅重建摘要**步骤见文末“Windows 摘要换行修复”。下述 Linux／NOT_RUN 结论保留为 `647a404` 当时证据；当前尚未收到通过完整校验的 Windows 摘要，不宣称 Windows PASS，不重跑矩阵。

## 分层结论与停止点

**Linux 隔离契约 PASS；等待 Windows 原进程机制验收。** 原 38 支按 ADR-0058 全部通过，新增 10 支通过。这里只验证候选，不是生产接纳实现或 I-02 PASS。生产 Core schema、命令路由、回执守卫、桌面业务和依赖均未修改。

补充回归单独记录：Python 46 方法、既有 Go 回归及诊断通过；浏览器 **12 PASS／1 FAIL**，小窗 runtime 加载支出现 `ECONNRESET`。保留本次失败输出，未重跑以制造全绿，也未调试连接问题。它与旧报告的间歇连接错误同属需要保留的稳定性风险，尚未证明根因相同。

Windows 10 原进程句柄／首次绑定／隔离事务路径 **NOT_RUN**。交叉编译只证明可编译；完整 I-02 原生通知、Wails 行为和 PC 重启另行验收。本轮矩阵完成后停止，不继续严格提交协调研究，不自动进入生产集成。

## 基线与版本依据

沿用 [Issue #33](https://github.com/Annzival/ADHD-Support-System/issues/33)、[Draft PR #35](https://github.com/Annzival/ADHD-Support-System/pull/35)、原任务分支。工作树起初干净；核实 PR #41 人工合并为 `e383fb4`，交接与 ADR-0058 均存在于远端 main，正常合入为 `17efadf`，无冲突、未改写历史。

已完整读取 AGENTS、CONTEXT、发布规则、ADR-0055/0057/0058、新交接、G01-R/U/C 场景、两轮报告与提交边界研究，检查实际隔离事务、进程身份和宿主夹具。源码 checkpoint：`bc24f2a`。机器摘要记录源码文件与历史报告 SHA-256、原始输出哈希及环境。访问一手资料日期：2026-09-27。

| 历史版本 | 当时规则／结果 | 本轮如何处理 |
| --- | --- | --- |
| `62bc99a`／`eb3863b` | 第一轮 29/30；新宿主运行未登记时误存，FAIL | [报告](i02-g01-verification.md)与[摘要](i02-g01-verification.json)原样保留 |
| `9848b29`／`86b6941` | 原 30 PASS，新增 7 PASS／1 FAIL；检查后重启仍保存 | [报告](i02-g01-restart-revalidation.md)与[摘要](i02-g01-restart-revalidation.json)原样保留 |
| `baf72b1` | 研究回传“需产品取舍”，当时尚未接受 | [研究](i02-g01-commit-boundary-research.md)原样保留，不将后来的决定写回过去 |
| ADR-0058，PR #41 | 允许同一原事务通过检查后完成提交 | 本文件与独立[机器摘要](i02-g01-accepted-boundary-validation.json)记录新预期和新运行 |

唯一改变旧预期的原分支是 `exit_after_check_before_commit`：旧为 **409／零报告**，新为 **200／一份报告、一条事实、一份原命令结果**。旧主张没有被“修好”；是用户已接受的新契约允许这条时间线。其余原 37 支预期不变。测试通过显式 `I02_G01_CONTRACT=ADR-0058` 选择新预期；缺少该版本不会把旧断言自动转绿。旧证据仍以旧 commit 复现，不拿新代码冒充旧实现。

## 首次绑定：为什么句柄对应发起登记的原进程

原来只用登记中的 PID 打开句柄，不能单独排除“登记后原进程退出，PID 已指向另一个实例”的空档。本轮只在实验适配中增加一次往返，不增加权限、进程所有权或启动仲裁。

1. 可信宿主在自己的进程中读取 PID，并创建本次运行标识；不加载上次宿主的运行材料。Core 收到登记后打开并保留 OS 进程对象，尚不允许该宿主取得发送许可。
2. **打开之后**，Core 为这次待绑定对象生成新的随机挑战，含 Core 运行、宿主运行、PID 和对象引用。它仅保存在 Core 内存，不是设备事实。
3. 原宿主收到挑战后，只对自己的运行标识与实际 PID 相符的挑战作答。Core 核对当前完整挑战，再查询刚才保留的同一个 OS 对象仍然存活，才完成登记；挑战随后消费。错挑战、旧挑战和缺失回应不能建立首次绑定。
4. 后续许可引用已绑定对象，结果事务仍重新检查其存续；登记成功不是任何未来事务的接纳资格。Core 重启清空内存材料，旧许可的 Core 运行不符仍拒绝，已提交原命令则先从数据库返回。

**依据是因果链，不是随机字符串或 PID 相等本身：** 可信原宿主能够回答打开后才生成的新挑战，说明它在打开之后仍执行过代码；它诚实提供的 PID 在自己存活时唯一标识它。因此打开时不能已经是复用该 PID 的另一个实例。若它在打开前已退出，无法产生这个新回应；新宿主不代答旧运行。如果回应产生后才退出，保留对象的存续检查会发现退出，后续结果事务也会重查。全过程不比较跨进程时钟。

这依赖既定可信本机宿主前提、挑战不被提前预测或错配，以及宿主不转交旧运行身份。随机挑战用于防止先前请求冒充新回应，不能独自证明 OS 身份；同权限恶意进程伪造、窃取或代答不在威胁模型内。本协议不是新的强认证声明。

Windows 继续仅用 `OpenProcess(SYNCHRONIZE, FALSE, pid)` 和 `WaitForSingleObject(handle, 0)`，不增加访问权。Microsoft 的 [Process Handles and Identifiers](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)说明存活期间 PID 的唯一性及退出后保留句柄的对象引用；[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)说明访问检查；[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)说明 SYNCHRONIZE 和即时状态查询。首次绑定的因果论证是本候选对这些原语的组合，不是 Microsoft 对本协议的背书。权限／句柄依据缺失就拒绝，不提权。

Linux 使用原 `pidfd_open + poll(0)` 验证同样协议；Windows 路径尚待实机。`pid_reuse_before_open_substitute` 把打开旧 PID 的结果替换成一个真实存活的新进程句柄，并在宿主确认侧模拟相同数值 PID，仍必须拒绝旧运行挑战。它是确定性复用模型，**不是实际强迫操作系统复用 PID**。真实退出前／后打开、打开后退出分别由子进程 Kill／Wait 控制，不混用证据层级。

## 同一结果事务与回滚／重启

关联、报告、事实、命令结果仍保存在独立 `experiment.sqlite3` 的一个事务内。最后存续检查后保留暂停点，不加额外检查，不追求消除该空隙；新契约允许原事务在宿主重启后继续提交。检查至提交没有已证明时长上限；夹具超时只用于结束失败测试，不是产品保证。

新增 G01-C03 的控制点位于成功检查之后、提交之前：

- 回滚后旧宿主退出，再以同一报告重试：数据库先确认报告／事实／命令均未留下，重试重新查原实例并拒绝，不能继承上次检查。
- 回滚后原宿主仍存活的控制支：重新核验后只保存一次，同 ID 再取回完全相同原结果。
- Core 在暂停点被真实终止：旧 HTTP 请求的错误不作为提交依据；新 Core 打开原实验库，确认没有已提交报告／命令，再拒绝旧运行结果。任务／会话等持久记录保留；结果交回前后的完整领域快照不变。
- 原 38 支中的 Core／宿主／两者在提交后重启且丢响应：以恢复库中的原命令返回原结果，零新事实，和未提交支分开验证。

只保存历史设备报告，不改任务、会话、安排、调度或旧入口，不产生新发送；结果顺序／机会资格保持未知，实际发送时刻、精确延迟为空，不能由收到请求时刻推断。设备回调仍为替身，不证明显示或用户看见。生产库与实验库分离，以上不证明未来生产集成的同事务一致性。

## 逐支新契约结果

下面 HTTP 为新预期／实际；完整输入序列、关联摘要、源码、层级和计数见机器摘要。原分支与新增分支分组，全部新运行均为 Linux；每支 Windows 仍 NOT_RUN。`rollback` 的 503 是首次注入失败，随后活宿主重试 200 并只留一份报告。混合支分别验证已有命令 200 和未提交请求 409。

| 分组／分支 | 新预期／实际 HTTP | 最终报告数 | 结果 |
| --- | --- | --- | --- |
| 原30：`normal` | 200／200 | 1 | PASS |
| 原30：`claim_loss_cancel` | 409／409 | 0 | PASS |
| 原30：`before_call` | 409／409 | 0 | PASS |
| 原30：`during_call` | 200／200 | 1 | PASS |
| 原30：`after_return` | 200／200 | 1 | PASS |
| 原30：`request_loss` | 200／200 | 1 | PASS |
| 原30：`response_loss` | 200／200 | 1 | PASS |
| 原30：`window_close` | 200／200 | 1 | PASS |
| 原30：`api_failure` | 200／200 | 1 | PASS |
| 原30：`click_only` | 409／409 | 0 | PASS |
| 原30：`wrong_permit` | 409／409 | 0 | PASS |
| 原30：`wrong_attempt` | 409／409 | 0 | PASS |
| 原30：`wrong_core` | 409／409 | 0 | PASS |
| 原30：`wrong_host` | 409／409 | 0 | PASS |
| 原30：`wrong_database` | 409／409 | 0 | PASS |
| 原30：`wrong_call` | 409／409 | 0 | PASS |
| 原30：`conflict_command` | 409／409 | 1 | PASS |
| 原30：`conflict_attempt` | 409／409 | 1 | PASS |
| 原30：`duplicate_new_command` | 200／200 | 1 | PASS |
| 原30：`rollback` | 503／503；重试 200 | 1 | PASS |
| 原30：`core_before` | 409／409 | 0 | PASS |
| 原30：`core_after` | 200／200 | 1 | PASS |
| 原30：`host_before` | 409／409 | 0 | PASS |
| 原30：`host_after` | 200／200 | 1 | PASS |
| 原30：`both_before` | 409／409 | 0 | PASS |
| 原30：`both_after` | 200／200 | 1 | PASS |
| 原30：`mixed_core` | 已存 200／200；未存 409／409 | 1 | PASS |
| 原30：`mixed_host` | 已存 200／200；未存 409／409 | 1 | PASS |
| 原30：`mixed_both` | 已存 200／200；未存 409／409 | 1 | PASS |
| 原30：`host_restart_before_registration` | 409／409 | 0 | PASS |
| 原8：`exit_observer_delayed` | 409／409 | 0 | PASS |
| 原8：`exit_after_check_before_commit` | 200／200 | 1 | PASS |
| 原8：`committed_response_lost_restart_unregistered` | 200／200 | 1 | PASS |
| 原8：`pid_reuse_substitute` | 409／409 | 0 | PASS |
| 原8：`pid_mismatch` | 409／409 | 0 | PASS |
| 原8：`identity_unavailable` | 409／409 | 0 | PASS |
| 原8：`missing_identity` | 409／409 | 0 | PASS |
| 原8：`window_close_live_process` | 200／200 | 1 | PASS |
| 新增10：`rollback_after_check_then_host_exit` | 409／409 | 0 | PASS |
| 新增10：`rollback_after_check_same_host_retry` | 200／200 | 1 | PASS |
| 新增10：`core_restart_after_check_uncommitted` | 409／409 | 0 | PASS |
| 新增10：`first_binding_success` | 200／200 | 0 | PASS |
| 新增10：`exit_before_open` | 409／409 | 0 | PASS |
| 新增10：`exit_during_registration_before_open` | 409／409 | 0 | PASS |
| 新增10：`pid_reuse_before_open_substitute` | 409／409 | 0 | PASS |
| 新增10：`exit_after_open_before_confirm` | 409／409 | 0 | PASS |
| 新增10：`wrong_challenge` | 409／409 | 0 | PASS |
| 新增10：`stale_challenge` | 409／409 | 0 | PASS |

## 命令、回归和证据保存

Linux x86_64，内核 6.8.0-49-generic，Python 3.12.3，SQLite 3.45.1，Go 1.25.0；没有升级依赖。以下从仓库根目录运行：

```bash
I02_G01_SPIKE=1 I02_G01_CONTRACT=ADR-0058 I02_DELIVERY_PROBE=1 .scratch/toolchain/go/bin/go -C desktop test -race -count=1 -timeout 180s -v ./...
/usr/bin/python3 -m unittest discover -s tests/acceptance -v
I01_TEST_GO="$PWD/.scratch/toolchain/go/bin/go" I01_BROWSER_EXECUTABLE=/home/Parzival/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome LD_LIBRARY_PATH="$PWD/.scratch/browser-libs/extracted/usr/lib/x86_64-linux-gnu" npm test --prefix desktop
.scratch/toolchain/go/bin/go -C desktop vet ./...
# 仅交叉编译，不是 Windows 运行。
GOOS=windows GOARCH=amd64 .scratch/toolchain/go/bin/go -C desktop test -c -o ../.scratch/i02-checks/g01-accepted-windows.test.exe
# 对已保存的完整 Go 输出生成本版本独立摘要；要求源码已提交且与文件完全一致。
python3 -m spikes.i02_g01.summarize_accepted .scratch/i02-checks/g01-accepted-final-go.txt .scratch/i02-checks/g01-accepted-summary.json --go .scratch/toolchain/go/bin/go
```

初步原 38 支与新增 10 支分开跑过；随后完整矩阵与 Go 回归通过。最终源码整理只调整运行 ID 生成与证据字段、补强同事务计数断言，再跑完整最终矩阵，未删除断言或隐藏失败。Go vet 与 Windows 交叉编译通过。浏览器本次失败见开头，原日志一并保留。

原始输出在 `.scratch/i02-checks/g01-accepted-*.txt` 受控保存至复审结束；机器摘要保存哈希、字节数和脱敏结果，不提交原始日志／库／令牌／挑战值。测试只使用合成数据与临时库。第一轮、第二轮和研究文件的哈希保持原样。

## Windows 最小步骤（NOT_RUN）

仅验证进程实例与隔离事务，不需要启动 Wails 窗口或通知、配置开机启动、重启 PC。沿用 Windows 10 22H2/19045 x64、Python 3.12.3 x64、Go 1.25.0；不升级 Wails/WebView2、不安装新权限或 race 工具链。操作者使用本轮源码及证据 checkpoint，工作树须干净。

在仓库根目录 PowerShell 中，将 Python 路径改为已有锁定安装路径。建议新目录名，避免覆盖旧证据：

```powershell
$g01Python = 'D:\Tools\Python312\python.exe'
$g01Out = '.scratch\g01-accepted-windows'
if (Test-Path $g01Out) { throw '请保留旧证据并改用新的输出目录名' }
New-Item -ItemType Directory $g01Out | Out-Null
$beforeIds = @(Get-CimInstance Win32_Process | Select-Object -ExpandProperty ProcessId)
$priorSpike = $env:I02_G01_SPIKE
$priorContract = $env:I02_G01_CONTRACT
$priorPython = $env:I01_TEST_PYTHON
try {
  $env:I02_G01_SPIKE = '1'
  $env:I02_G01_CONTRACT = 'ADR-0058'
  $env:I01_TEST_PYTHON = $g01Python
  git rev-parse HEAD | Out-File -Encoding utf8 "$g01Out\commit.txt"
  go version | Out-File -Encoding utf8 "$g01Out\go.txt"
  & $g01Python --version | Out-File -Encoding utf8 "$g01Out\python.txt"
  Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber,OSArchitecture | Out-File -Encoding utf8 "$g01Out\os.txt"
  go -C desktop test -count=1 -timeout 180s -run '^TestG01(BoundedSpike|MixedCommittedAndUncommitted|RestartBeforeRegistration|RestartRevalidation|TransactionQualification|InitialBinding)$' -v 2>&1 | Out-File -Encoding utf8 "$g01Out\matrix.txt"
  $g01Exit = $LASTEXITCODE
  $g01Exit | Out-File -Encoding utf8 "$g01Out\exit-code.txt"
  Get-FileHash -Algorithm SHA256 "$g01Out\matrix.txt"
  if ($g01Exit -eq 0) {
    & $g01Python -m spikes.i02_g01.summarize_accepted "$g01Out\matrix.txt" "$g01Out\summary.json" --go go
    if ($LASTEXITCODE -ne 0) { throw '摘要校验失败，不能报 PASS' }
    Get-FileHash -Algorithm SHA256 "$g01Out\summary.json"
  }
} finally {
  $env:I02_G01_SPIKE = $priorSpike
  $env:I02_G01_CONTRACT = $priorContract
  $env:I01_TEST_PYTHON = $priorPython
}
```

预期：48 个分支通过，原 30＋原 8＋新增 10 分组完整；首次绑定成功、旧挑战／错误身份拒绝、检查前退出拒绝、检查后重启允许恰好一笔、回滚后旧宿主退出拒绝、新 Core 无原命令拒绝、有原命令返回。摘要 `environment.windows` 应是 `EXECUTED_ISOLATED`，不是硬编码 PASS。PID 复用仍标替身；它不能成为 Windows 真复用的证据。

若打开句柄权限不足、平台不符、控制点超时或任何断言失败，保存退出码、失败分支和脱敏错误，报告 FAIL／BLOCKED；不升级权限、不缩小断言、不称基础设施错误为通过，同一路径三次无新证据即停。没有运行的项目继续 NOT_RUN。

正常结束测试会结束并回收自己创建的子进程、由 OS 释放句柄并清理临时数据库。若执行被中断，只检查本次新增且对应实验的进程：

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -notin $beforeIds -and
  ($_.CommandLine -match 'spikes\.i02_g01\.server' -or $_.CommandLine -match 'TestG01SpikeHostProcess')
} | Select-Object ProcessId,Name,CommandLine
```

核实属于本轮临时目录／测试二进制后，才对具体 PID 使用 `Stop-Process -Id <PID>`；不批量终止 Python 或其他程序。原始路径和命令行留本机，回传源码 commit、锁定版本、逐支摘要、退出码和哈希。日志先脱敏，勿提交 bootstrap 令牌、挑战值、原始数据库或个人内容。

## 回传

本轮隔离候选在 Linux 满足 ADR-0058 的 48 支预期；Windows 首次绑定与存续路径等待上述实机证据。没有发现新的范围／ADR 冲突，未增加生产接纳授权。仍有生产集成原子性、完整 I-02 Windows 验收及浏览器稳定性限制。请当前治理线程核对分层结果后再授权下一步；PR #35 保持 Draft，不 Ready／merge／关闭 Issue。


## Windows 摘要换行修复

修复源码 `576916c`。本轮仅修改摘要工具及两项最小验证，没有改实验、Windows 测试断言、生产代码或产品规则，没有重跑 Go 矩阵。两轮 FAIL、研究和 `647a404` 的独立 Linux 机器摘要保持原样。

操作者回传：`exit-code.txt` 为 0、工作树干净；`matrix.txt` 原始字节 SHA-256 为 **`4CB5A5969769A27D6C5100E5B37AC6C27004162CEA58E457033177E0885D123F`**。只读核对确认 `server.py` 与 Git 内容仅有 CRLF/LF 差异。旧摘要器直接比较字节，因正常 checkout 换行转换误报 `uncommitted source`。以上是操作者证据，本 session 尚未取得原 Windows 日志／通过校验的摘要，不能仅凭退出码和哈希宣称 Windows PASS。

现在只在源码一致性比较时将 CRLF 转为 LF，不去除空白、BOM、末尾换行或其他字符，不把单独 CR 当作 LF。真正的内容修改继续报错。摘要哈希不归一化：

| 字段 | 现在的明确含义 |
| --- | --- |
| `source_commit`／每支同名字段 | `--source-commit` 指定的原矩阵运行 commit，取操作者原 `commit.txt`；不是重建摘要时的 HEAD |
| `sources_git_sha256` | 原矩阵 commit 中各实验／生产来源文件的 Git blob **原始字节** SHA-256 |
| `sources_sha256` | 继续表示当前工作区来源文件的**原始字节** SHA-256；Windows CRLF 可与 Git 哈希不同 |
| `source_comparison` | 明示只在比较时容许 CRLF→LF，不代表哈希也转换 |
| `summarizer.commit`／`summarizer.sources` | 新摘要工具的版本，以及摘要器／比较模块各自的 Git 和工作区字节哈希，独立于矩阵源码 |
| `raw_output.sha256` | 现有 `matrix.txt` 的原始字节哈希，必须仍与上述值一致，不重新编码或改写日志 |

旧 Linux 摘要的 `sources_sha256` 原本就是工作区字节哈希；由于当时没有换行差异，它也等于 Git 内容哈希。旧文件不改名、不回填新字段。新版将摘要工具从矩阵来源列表单独列出，以允许只更新工具后解析原矩阵，同时仍校验两者源码。

本轮本机验证：

```bash
python3 -m unittest spikes.i02_g01.test_source_evidence -v
python3 -m spikes.i02_g01.summarize_accepted .scratch/i02-checks/g01-accepted-final-go.txt .scratch/i02-checks/g01-newline-linux-summary.json --source-commit bc24f2a --go .scratch/toolchain/go/bin/go
```

两项最小验证 PASS：纯 LF／CRLF 差异通过且两套哈希各对应原字节；字符、空格、末尾换行缺失及单独 CR 修改全部拒绝。复用旧 Linux 输出，完整摘要检查仍得 30＋8＋10 PASS，保留原源码 `bc24f2a`、Windows NOT_RUN；没有生成新的矩阵执行证据。受控验证输出 SHA-256：`g01-newline-unit.txt` 为 `91a7e120bf6c9ee2df3e938484f74d634a791fab912c229fd15af7549086e7f4`；新临时 Linux 摘要为 `4c13136c5e8aea10ead39d30c3987ad45e08dcd9d4e819e872abc219ebb6dbae`，未替换仓库旧摘要。

### 操作者：只使用现有 matrix.txt

正常快进更新本任务分支到包含修复的 checkpoint（工作树有修改时先保留，不覆盖）；不要重跑上面的 Go／Wails 矩阵脚本。以下在原 Windows 仓库根目录执行，使用原输出目录与原 `commit.txt`，不要把它改成新 HEAD。若缺原 commit 记录，先回传缺口，不猜测运行版本。

```powershell
git pull --ff-only origin agent/implement-mvp-deterministic-recovery
$g01Python = 'D:\Tools\Python312\python.exe' # 原锁定路径
$g01Out = '.scratch\g01-accepted-windows' # 已有 matrix.txt 所在目录
$g01Expected = '4CB5A5969769A27D6C5100E5B37AC6C27004162CEA58E457033177E0885D123F'
if ((Get-Content "$g01Out\exit-code.txt" -Raw).Trim() -ne '0') { throw '原矩阵退出码不是 0' }
if ((Get-FileHash -Algorithm SHA256 "$g01Out\matrix.txt").Hash -ne $g01Expected) { throw '原日志哈希不匹配，停止并回传' }
$g01Source = (Get-Content "$g01Out\commit.txt" -Raw).Trim()
$g01Summary = "$g01Out\summary-newline-fixed.json"
if (Test-Path $g01Summary) { throw '请保留已有摘要并换用新文件名' }
& $g01Python -m spikes.i02_g01.summarize_accepted "$g01Out\matrix.txt" $g01Summary --source-commit $g01Source --go go
if ($LASTEXITCODE -ne 0) { throw '完整摘要校验失败：保留错误并回传，不报 Windows PASS' }
$g01Result = Get-Content -Encoding utf8 $g01Summary -Raw | ConvertFrom-Json
$g01Result.original_30.counts
$g01Result.prior_8.counts
$g01Result.added_10.counts
$g01Result.environment
$g01Result.source_commit
$g01Result.summarizer.commit
$g01Result.raw_output
Get-FileHash -Algorithm SHA256 $g01Summary
Get-FileHash -Algorithm SHA256 "$g01Out\matrix.txt"
```

应核对三组分别为 total/passed **30/30、8/8、10/10**，failed 均 0；`source_commit` 与原 `commit.txt` 一致；`environment.windows` 为 `EXECUTED_ISOLATED`，每支 `evidence_layer` 为 `Windows process API + isolated HTTP/SQLite; synthetic device`。PID 复用仍是替身，API 显示／用户阅读、完整 Wails／PC 重启并不因此通过。

回传新摘要及它的新 SHA-256、原矩阵不变的 SHA-256、两项 commit 与锁定环境。新摘要的哈希取实际生成结果，事先未知，不能用原日志哈希代替。若任何完整校验失败，回传准确错误和缺失分支；不要跳过校验或重跑已经通过的矩阵。当前状态为等待 Windows 摘要核对，PR #35 仍 Draft，I-02 未 PASS。
