# V-03 SQLite、Core 重启与 PC 重启恢复最小验证包

这是 Issue #18 的独立 `technical spike` 阶段 A 产物。它只验证**明确标记的合成状态与合成调度记录**能否在 SQLite、Core 重启与一次真实 Windows PC 重启后恢复；不是 MVP 代码，不定义正式领域对象、状态机、命令、事件或验收语义。

## 验证边界

本包只包含以下合成记录：

- 一个带稳定 ID、版本和内容的 `synthetic_authority_state`；
- 一个未来的 `synthetic_future_action`，带计划时间、失效时间、状态和已处理标记；
- 一个已过期的 `synthetic_expired_intervention`，带相同的技术字段；
- 仅用于判定重复的 `synthetic_observable` 记录。

固定的合成时钟为 UTC：检查点写入时是 `2030-01-01T09:00:00Z`，恢复扫描时是 `2030-01-01T10:30:00Z`。这些名称、字段和值只服务于本 spike，不能提升为正式领域词汇或产品状态。

Python Core 是 SQLite 的唯一访问者。Wails 宿主只执行机械的进程启动/停止、V-02 一次性 bootstrap file 端点发现、临时令牌内存桥接和脱敏证据写入；它不打开数据库，不计算到期或失效，不决定任何合成记录的结果，也不调用 LLM。

本包不包含用户方案、下一步行动、执行会话、正式干预 UI、真实 LLM、PydanticAI、消息渠道、联网服务、多用户、多设备、备份恢复、数据库加密或正式产品迁移。

## 首个且唯一的恢复机制

1. Python Core 以 SQLite WAL 事务写入合成检查点；提交后的权威合成状态会被重新打开核验。
2. 同一 Core 通过单独子进程在未提交事务中写入故意中断的合成行，并以受控异常退出；重新打开后必须没有半更新行。
3. Windows 重启前，`Prepare-RebootCheckpoint.ps1` 调用这个 Core 准备命令，记录脱敏检查点、当前 Windows 启动标识和数据库身份；该脚本本身不读取数据库。
4. 重启后，真实 Wails 宿主通过 V-02 的一次性 bootstrap file 重新启动 Core。Core 用固定合成时钟恢复数据库：未来记录只形成一次可观察动作；已过期记录不补发，只形成一次合并恢复信号；随后再做一次扫描和一次 Core 正常重启，均不得重复。
5. PowerShell 只检查宿主/Core 进程数、启动标识变化和脱敏结果。`Collect-Evidence.ps1` 生成摘要、原始证据 ZIP 与 SHA-256；不打包 SQLite 文件、bootstrap 文件、令牌或绝对路径。

首次机制通过即停止。只有失败证据明确指向不同的基础设施根因时，Issue #18 才允许第二次最小尝试；本分支当前没有第二种机制。

## 文件与自动检查

| 路径 | 用途 |
| --- | --- |
| `agent_core/synthetic_core.py` | Python SQLite 合成恢复 Core 和仅回环测试 API。 |
| `agent_core/test_synthetic_core.py` | 平台无关的提交、受控异常、重复扫描、bootstrap 与 Core 重启测试。 |
| `main_windows.go` | 真实 Wails 薄宿主；不直接读写数据库。 |
| `scripts/verify_static_contract.py` | 校验锁定版本、SQLite/Core 责任边界、bootstrap 形状、禁项和 PowerShell ASCII。 |
| `scripts/Prepare-RebootCheckpoint.ps1` | 重启前准备合成 SQLite 检查点与启动标识。 |
| `scripts/Start-RecoveryValidation.ps1` | 重启后启动 Wails/Core，采集单实例与恢复候选结果。 |
| `scripts/Collect-Evidence.ps1` | 生成脱敏摘要、返回清单和受控原始 ZIP 的 SHA-256。 |
| `MANUAL-CHECKLIST.md` | Windows 执行者只需完成的有限步骤。 |

PowerShell 脚本刻意只含 ASCII。V-01 的 Windows 证据已表明，Windows PowerShell 5.1 读取含中文的 UTF-8 无 BOM 脚本时可能失败；中文说明因此只放在 Markdown 文档中。

Linux 阶段 A 必须运行：

```bash
python3 -m unittest discover -s spikes/sqlite-restart-recovery/agent_core -p 'test_*.py'
python3 spikes/sqlite-restart-recovery/scripts/verify_static_contract.py
```

如有锁定的隔离 Go `1.25.0` 工具链，还会运行 Windows x64 的 `go test` 和 `go build`。这只能检查源代码/API，绝不替代 Windows PC 重启的最终证据。

## Windows 10 22H2 x64 有限步骤

只在 Issue #18 阶段 A 更新指定的 checkpoint、交互式 Windows 10 22H2 x64 桌面会话中执行。不要用 WSL、Windows 11、无桌面远程会话或其他 checkpoint 替代。所需锁定版本为 Go `1.25.0` x64、Python `3.12.3` x64（实际进程 `processBits=64`）、Wails `v3.0.0-beta.8` 和 WebView2 Fixed Version Runtime `151.0.4129.78` x64；不要升级这些版本。

先在仓库根目录确认 Issue #18 记录的 checkpoint，再运行：

```powershell
git rev-parse HEAD
Set-ExecutionPolicy -Scope Process Bypass
cd spikes\sqlite-restart-recovery
.\scripts\Test-PowerShellScriptParsing.ps1
.\scripts\Install-WailsCli.ps1
.\scripts\Install-WebView2FixedRuntime.ps1
.\scripts\Check-WindowsEnvironment.ps1
.\scripts\Build-Spike.ps1
.\scripts\Prepare-RebootCheckpoint.ps1
```

`Prepare-RebootCheckpoint.ps1` 成功后会明确打印“safe to restart”及检查点路径。此时只做一次真实 PC 重启（可使用 Windows 开始菜单的“重启”，或在同一交互式会话中运行 `Restart-Computer`）。不要先运行恢复脚本，也不要手改数据库、时钟、端口、令牌、日志或结果文件。

重新登录同一 Windows 用户后，在同一 checkout 中运行：

```powershell
cd spikes\sqlite-restart-recovery
.\scripts\Start-RecoveryValidation.ps1
$run = Get-ChildItem .evidence\runs -Directory | Sort-Object Name | Select-Object -Last 1
.\scripts\Collect-Evidence.ps1 -RunDirectory $run.FullName
```

执行后只经约定的私有渠道回传：checkpoint SHA、`v03-evidence-summary-*.json`、对应 ZIP 原件和脚本输出的 SHA-256。不要把 SQLite 文件、bootstrap 文件、临时令牌、原始日志正文、绝对路径、Windows 账户名、进程 ID、截图或录屏贴进 Issue 或提交 Git。

## 停止点

- Linux 自动检查通过时，只能报告 `READY_FOR_WINDOWS`；不能从进程级测试外推真实 PC 重启的 `PASS`。
- Windows 证据缺失、启动标识未变化、进程数不为一、摘要/哈希不完整时，报告 `BLOCKED`。
- 任一必需恢复行为失败时，保留现场并报告 `FAIL`；不启动第二种机制，除非有不同且明确的基础设施根因。
- 一次可核验的 Windows 重启结果后停止；不标记 MVP 构建就绪，不合并 PR，不修改 B-03/B-04，也不开始 MVP implementation。
