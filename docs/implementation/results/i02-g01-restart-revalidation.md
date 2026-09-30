# I-02 G-01 第二轮：宿主重启识别复验

## 结论与停止点

**FAIL（隔离候选机制）。** 原 30 支全部通过，上一轮 `host_restart_before_registration` 保持原 409／零报告断言并转绿；新增 8 支中 7 PASS、1 FAIL。没有提前登记新宿主或强制 Core 重启。

新反例：Core 在结果事务内查到旧宿主进程存活 → 暂停在最后一次存续检查之后、SQLite 提交之前 → 旧宿主真实退出，新宿主已运行且未登记 → 放行事务 → 实际 200／一份实验报告，要求仍是 409／零报告。进程句柄绑定同一实例，并不能让进程存续检查与数据库提交成为同一个不可分割的动作。

本轮矩阵完成即停止。只否定本候选的完整保证，不证明所有可能机制均不可行。不将“Core 检查时还活着”替换成 ADR-0057 的重启定义，不自行修改产品／ADR，也不转入生产实现。I-02 整体未 PASS。

## 准备与证据链

启动工作树干净，沿用 [Issue #33](https://github.com/Annzival/ADHD-Support-System/issues/33)、[Draft PR #35](https://github.com/Annzival/ADHD-Support-System/pull/35) 和原分支。核实第二轮交接随 PR #39 人工合并为 `ebce4e1`，交接确实存在于远端 main，然后正常合入，无冲突。已读 AGENTS、CONTEXT、发布规则、ADR-0052/0055/0057、验收与第二轮交接、第一轮报告／机器摘要及实际实验代码。

上一轮源码 `62bc99a`、证据 `eb3863b` 和 [FAIL 报告](i02-g01-verification.md)／[原机器摘要](i02-g01-verification.json)保持原样；本轮使用新文件与新输出，不覆盖失败历史。本轮实验源码 commit `9848b29`；平台、文件与原始输出哈希见 [第二轮机器摘要](i02-g01-restart-revalidation.json)。

## 唯一候选：保留进程实例句柄，提交前同步观察

在编码前已说明以下候选；实验只增加隔离 `process_identity.py`、实验服务控制点和测试，没有修改生产 Core schema、命令白名单、回执守卫、宿主业务代码或依赖。

- 可信测试宿主在原登记请求提供自身 PID。Core 打开并一直持有操作系统进程对象句柄，给这个已打开的对象分配实例标签；许可同时引用原宿主运行标识和该实例。后续不按数值 PID 重新打开进程来判断旧许可。标签是 Core 对句柄的引用，不是声称随机字符串本身证明进程存续。
- Linux 使用 `os.pidfd_open(pid, 0)`，同步 `poll(0)`；进程退出或被回收后该保留描述符有就绪／挂断信息。打开或查询失败、实例错配、缺少句柄时拒绝新增结果，没有退回“最后登记值”放行。
- Windows 候选路径使用 `OpenProcess(SYNCHRONIZE, FALSE, pid)` 和保留的 HANDLE，`WaitForSingleObject(handle, 0)` 区分已终止、当前未终止和调用失败。无需管理员权限或调试权限；若现有权限无法打开，按依据不足拒绝，不升级权限。此路径 **NOT_RUN**。
- 已提交原命令及完整内容匹配的查询，仍先返回原持久结果；不因旧宿主已退出或运行材料变化而拒绝已提交结果读取。未提交结果沿用许可／调用关联、内容冲突、未知顺序和同事务保存逻辑。
- 结果／事实／命令结果写入隔离 SQLite 事务后，提交前做最后一次句柄检查。若此时已退出则整笔回滚；如果退出发生在检查后，SQLite 本身不会因外部进程退出而自动撤销事务。这正是本轮强制控制的竞争。

句柄不作为通知显示、用户阅读或执行先后的证据。发送顺序、机会资格仍未知，实际发送时刻／精确延迟仍为空；没有增加宿主持久结果库。

## 操作系统一手依据与目标限制

| 能力 | 一手资料与本轮使用 | 限制 |
| --- | --- | --- |
| Linux 进程描述符 | Linux man-pages 的 [pidfd_open(2)](https://man7.org/linux/man-pages/man2/pidfd_open.2.html)说明描述符引用任务，退出／回收可由 poll 观察；该接口始于 Linux 5.3。Python [os.pidfd_open](https://docs.python.org/3.12/library/os.html#os.pidfd_open)提供标准库入口 | Linux 专用；不支持或权限／资源错误时不能凭 PID 推断存活。持有描述符不是阻止进程终止的锁 |
| Windows 实例句柄 | Microsoft [Process Handles and Identifiers](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)说明句柄在进程退出后仍可保留至关闭；数值 PID 的有效期不同。用 [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)请求最小 SYNCHRONIZE 权限 | 依赖目标进程访问权限；本轮只提供代码与步骤，未在锁定 Windows 10 上验证 |
| Windows 退出观察 | Microsoft [Terminating a Process](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process)说明终止使进程对象变为 signaled；[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)允许超时 0 的立即检查，要求 SYNCHRONIZE | 就绪状态观察不包含 SQLite COMMIT，也不冻结进程。不能将单次未 signaled 当作未来仍存活保证 |

这些资料支持“句柄对应对象、可观察终止”，不提供“存续检查与 SQLite 提交原子绑定”的承诺。检查后竞争的结论来自本轮反例，不是从文档推断全部方案不可能。首次打开前的 PID 冒充／复用竞争未验证；本实验信任本机宿主登记提供自己的 PID，没有引入更强的攻击者模型。

## 可重复控制点与新增 8 支

实验的 `/spike/control` 只在测试服务存在，不进入生产路由。控制端点不持有结果事务锁，因此父测试可以在事务真正暂停后 Kill／Wait 旧宿主，启动新宿主并从其管道收到响应，最后放行。不是依靠随机睡眠或重复跑碰运气。

- `before_live_check`：事务已写入候选记录，但还没有同步查句柄；暂停后旧宿主退出，再恢复检查。`cached_exit` 的更新被确定性推迟，证明不靠缓存退出标记或新宿主登记放行。真实退出由 OS 进程完成，缓存延迟是诊断替身，不宣称实现了生产异步监视器。
- `after_live_check_before_commit`：最后一次同步存续检查已返回“存活”，SQLite 尚未提交。暂停后强制重启，再直接恢复提交。不会额外塞一次检查来回避指定的“最后检查之后”边界。
- 控制点有有界超时；没到达控制点、子进程未真实退出／未收到新宿主响应均是测试错误，不能计作反例通过。

| 新分支 | 控制、预期与实际 | 结论 |
| --- | --- | --- |
| exit_observer_delayed | 退出后推迟同步观察，旧缓存仍 false；最终查保留句柄发现退出，409／零报告，整笔实验记录回滚 | PASS；真实退出＋观测延迟控制 |
| exit_after_check_before_commit | 最后检查返回存活→旧宿主退出→新宿主已运行未登记→提交；应 409／零报告，实际 200／一份报告 | **FAIL；真实进程竞争** |
| committed_response_lost_restart_unregistered | 报告／命令已提交、响应丢失→宿主重启未登记→原命令取回；200、精确原结果、无新增记录 | PASS |
| pid_reuse_substitute | 同一数值 PID 下把实例标签换为另一实例；许可仍引用旧实例，409／零报告 | PASS；确定性替身，不是假称实际复用了 OS PID |
| pid_mismatch | 同一个宿主标签却提交另一真实 PID；409，原记录不变 | PASS |
| identity_unavailable | 关闭保留句柄后交回未提交结果；409／零报告，没有用登记值放行 | PASS；故障注入 |
| missing_identity | 登记缺 PID／句柄依据；409，原状态不变 | PASS |
| window_close_live_process | 模拟关闭界面但同一个宿主子进程保持运行；200／一份报告 | PASS；不是原生 Wails 关闭证据 |

每支核验生产领域完整快照不变，旧用户操作仍 409，设备调用仅一次、重发 0。拒绝分支还核对整个实验报告／事实／命令快照与事务前相等。提交后重试分支比对完整原处理结果，而不只检查返回码。

## 原 30 支回归

原断言未放宽；逐支输入、关联判断、报告数和重启边界在机器摘要的 `original_30.cases`，与新增 `new_8.cases` 分开。以下分组完整列出原 30 支，全部 PASS：

| 原分支 | 本轮核验 |
| --- | --- |
| normal、claim_loss_cancel、before_call、during_call、after_return | 结果先保存与调用前／中／后回应；已取消未执行尝试仍不调用，历史记录不恢复操作 |
| request_loss、response_loss、window_close、api_failure、click_only | 请求／响应丢失、同进程关闭、明确设备负结果、仅点击；关联和未知口径不退化 |
| wrong_permit、wrong_attempt、wrong_core、wrong_host、wrong_database、wrong_call | 六种关联错配均拒绝 |
| conflict_command、conflict_attempt、duplicate_new_command、rollback | 冲突内容不覆盖、同报告不重复、故障整笔回滚 |
| core_before、core_after、host_before、host_after、both_before、both_after | 两类进程分别及共同在提交前／后重启，未提交拒绝与原命令返回分开 |
| mixed_core、mixed_host、mixed_both | 已提交与未提交记录并存：旧持久结果、任务／会话／有效调度保留，未提交不补存 |
| host_restart_before_registration | 原来 200／一份报告改为 409／零报告；新宿主仍未登记，Core 未重启 |

上一轮报告里的 FAIL 是当时事实，保留不改；本轮转绿仅证明句柄能弥补那一个先退出再处理请求的空档，不能覆盖新增的检查后竞争。

## 命令、回归与证据

在仓库根目录，沿用已验证工具，不安装或升级环境：

```bash
# 完整矩阵和 Go 回归：本候选有一个真实失败，预期非零退出。
I02_G01_SPIKE=1 I02_DELIVERY_PROBE=1 .scratch/toolchain/go/bin/go -C desktop test -race -count=1 -timeout 120s -v ./...
# 最小新反例：仍要求拒绝，不将观察到的保存改成预期。
I02_G01_SPIKE=1 .scratch/toolchain/go/bin/go -C desktop test -race -count=1 -timeout 30s -run '^TestG01RestartRevalidation$/^exit_after_check_before_commit$' -v
/usr/bin/python3 -m unittest discover -s tests/acceptance -v
I01_TEST_GO="$PWD/.scratch/toolchain/go/bin/go" I01_BROWSER_EXECUTABLE=/home/Parzival/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome LD_LIBRARY_PATH="$PWD/.scratch/browser-libs/extracted/usr/lib/x86_64-linux-gnu" npm test --prefix desktop
.scratch/toolchain/go/bin/go -C desktop vet ./...
```

Linux 进程句柄和隔离 HTTP／SQLite 实测；Python 46 方法通过、浏览器 13 项通过，既有 Go 送达／桥接回归及原四支诊断通过。没有顺带修复浏览器间歇连接问题；上一轮两支连接错误和未定位原因仍保留。本轮 Go vet、Windows Go 测试二进制交叉编译通过，不等于 Windows Python 句柄路径或原生窗口通过。

原始输出在 `.scratch/i02-checks/g01-r2-*.txt` 受控保留至复审结束，文件哈希及字节数进入独立机器摘要。临时库由测试清理，不提交令牌、个人内容或原始库。摘要记录真实 OS 退出与替身注入的区别；源码哈希包含未改变的生产 Core／桥／pump，便于核对隔离边界。

## 锁定 Windows 10 最小执行步骤（NOT_RUN）

沿用 Windows 10 22H2/19045 x64、Python 3.12.3 x64、Go 1.25.0；不升级已有 Wails beta.8／Fixed WebView2 151.0.4129.78。本轮无需启动 Wails 窗口、不改登录启动或系统设置，只运行隔离子进程与句柄等待路径。

在干净的本轮 checkpoint 仓库根目录：

```powershell
$env:I02_G01_SPIKE = '1'
$env:I02_DELIVERY_PROBE = '1'
$env:I01_TEST_PYTHON = 'D:\Tools\Python312\python.exe' # 已核验安装路径
New-Item -ItemType Directory -Force .scratch\g01-r2 | Out-Null
$beforeIds = @(Get-CimInstance Win32_Process | Select-Object -ExpandProperty ProcessId)
go -C desktop test -count=1 -timeout 120s -run '^TestG01(BoundedSpike|MixedCommittedAndUncommitted|RestartBeforeRegistration|RestartRevalidation)$' -v 2>&1 | Out-File -Encoding utf8 .scratch\g01-r2\windows-matrix.txt
$testExit = $LASTEXITCODE
$testExit | Out-File -Encoding utf8 .scratch\g01-r2\exit-code.txt
Get-FileHash -Algorithm SHA256 .scratch\g01-r2\windows-matrix.txt
Remove-Item Env:I02_G01_SPIKE
Remove-Item Env:I02_DELIVERY_PROBE
Remove-Item Env:I01_TEST_PYTHON
```

有既有 race C 工具链时可另加 `-race` 并记录；没有则不为本轮安装。预期原反例转绿、退出观测延迟支拒绝、已提交原命令返回、指定最后检查后竞争仍报 FAIL。若 Windows 拒绝打开句柄或控制点超时，应记录具体限制，不把基础设施错误写成反例通过、不扩大权限。

正常结束测试只终止并回收自己创建的 Core／宿主子进程，释放句柄、删除临时数据库。若超时／异常退出，检查本次新增进程：

```powershell
Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -notin $beforeIds -and
  ($_.CommandLine -match 'spikes\.i02_g01\.server' -or $_.CommandLine -match 'TestG01SpikeHostProcess')
} | Select-Object ProcessId,Name,CommandLine
```

仅对核实属于本轮临时目录／测试二进制的具体 PID 做 `Stop-Process -Id <该PID>`；不批量结束 Python 或其他应用。保留受控日志后再清理本轮临时残留，不删除其他实验目录。回传源码 commit、锁定环境、退出码、逐支脱敏摘要与 SHA-256，原始路径／命令行留本机；不提交令牌。无需为本轮重启 PC、增加后台监控或采集桌面内容。

Windows 路径尚未执行，API 返回／通知显示／阅读时刻均没有新证据；Linux 结论不外推 Windows PASS。

## 可复用部分、未证明部分与候选取舍

可复用：原许可／调用关联、幂等原结果查询、冲突拒绝、未知顺序处理；新增的保留 OS 实例句柄能够拒绝**已在最后检查时退出**的旧宿主结果，也能在依据缺失时拒绝新增事实。这比依赖新宿主登记更强，但弱于当前要求。

仍未证明且已有反例：最后检查完成到 COMMIT 的空隙。再插入一次相同检查只移动“最后检查”位置，不提供本候选缺少的原子衔接；本轮不以减少暂停时长、重复运行没碰到失败或事后删除已提交事实换取全绿。

维持当前产品边界时，此候选不能直接用于生产，需要另行授权研究能否让生命周期边界与提交协同；本轮没有证明这样的机制存在或不存在。若选择接受“最后观测存活即可保存”的较弱语义，会改变已确认边界，须治理明确决定；本 session 未采取或推荐自动改变。没有新增 ADR 文本冲突，只有机制不能完整满足既定规则的证据。

请当前治理线程核对这份 FAIL 和具体代价后再判断下一阶段授权。本轮到此停止，PR #35 保持 Draft，不 Ready／merge／关闭 Issue、不进入 I-03/I-04。
