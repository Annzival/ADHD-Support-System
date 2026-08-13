# V-01：Wails v3 Windows 薄桌面宿主验证结果

## 任务与证据边界

- 任务类型：`technical spike`；对应 [Issue #11](https://github.com/Annzival/ADHD-Support-System/issues/11)。
- 规范：[两阶段验证计划](../plans/wails-v3-windows-thin-host.md)。
- 该文档只整理 V-01 证据；不决定产品范围、领域模型、MVP 构建就绪或 Wails 的正式采用。
- Linux、WSL、mock、源代码检查和交叉编译均不能作为 Windows 桌面能力 `PASS` 的依据。

## 锁定候选

| 项目 | 候选 | 记录方式 |
| --- | --- | --- |
| Windows | Windows 10 22H2 x64，基线 `10.0.19045` | 实机环境脚本记录 DisplayVersion、版本、UBR 和架构。 |
| Wails | `v3.0.0-beta.8`，release commit `81a149919f91f2149d3fe9be5a27472ae7617b8e` | `wails3 version` 与 Go module。 |
| Go | `go1.25.0` | `go version`。 |
| WebView2 | Fixed Version Runtime `151.0.4129.78` x64 | 运行脚本记录 `msedgewebview2.exe` 文件版本和目录。 |
| Python | `3.12.3` x64 | `py -3.12` 解释器和版本。 |

锁定依据保存在 `spikes/wails-v3-windows-thin-host/versions.json`。WebView2 采用 Fixed Version，是为了使该 spike 的运行时版本可复现；它不构成正式安装器方案。

## 阶段 A：Linux 准备

**状态：READY_FOR_WINDOWS。** 最小验证代码、版本锁定、运行/清理脚本、人工清单、平台无关检查、Draft PR 和 Issue 关联均已经完成；Windows 环境检查与宿主构建也已在目标机通过。最终验证脚本 checkpoint 为 `505cc712c7887dd4e4c3277716d4b340e11297ab`；它不等同于最终 B 宿主二进制构建 commit，二者的对应关系见下文。此阶段状态只表示准备完整，不表示任何 Windows 桌面能力 `PASS`，也不满足 MVP 构建就绪门槛。阶段 B 的单实例结果见下文。

阶段 A 产物预期包括：

- 最小 Windows 专属 Wails 宿主和静态前端；
- 仅回环监听的 Python 智能体核心测试替身；
- 带健康检查、单次异常重启、指数退避、重启上限、明确退出和日志记录的机械性进程守护；
- Windows 环境、构建、单实例、守护场景、人工观察、证据汇总、打包与清理 PowerShell 脚本；
- 不把领域状态、SQLite、领域调度、干预规则或 LLM 放进 Wails 的静态边界检查；
- Linux 平台无关测试记录。

阶段 A 绝不把任一 Windows 桌面能力写成 `PASS`。

### 准备脚本修正记录（2026-08-13）

Windows 实机在执行 `Install-WailsCli.ps1` 时报告第 20 行的 PowerShell 字符串终止符解析错误。原 checkpoint 的同一文件在 Linux PowerShell AST 解析中未复现，因而不能将该 Linux 结果外推为 Windows 通过。

为消除实机错误所涉的嵌套 `Join-Path ((& ...).Trim())` 调用形式，后续 checkpoint 将先获取 `GOPATH`，再以具名 `-Path` 和 `-ChildPath` 参数构造 `wails3.exe` 路径；同一风险形式也从 `Check-WindowsEnvironment.ps1` 移除。静态契约检查禁止重新引入该形式。

先前根因一度记录为 `UNCONFIRMED`；现由 Windows PowerShell 5.1 Parser 输出和文件编码证据确认是 UTF-8 无 BOM 与 Windows PowerShell 5.1 的源文件读取规则不兼容，而不是该行 `Join-Path` 或单引号字符串的语法错误。

### Windows 解析阻塞更新（2026-08-13）

修正 checkpoint `6e914ade164d2799b4ab81209e9953e503287d96` 在 Windows 实机仍于新第 21 行报告同样的单引号字符串终止符错误。该行的 `'bin\wails3.exe'` 是 PowerShell 的有效单引号字符串，反斜杠不转义单引号。

Windows 诊断确认：工作副本与 `HEAD` 的第 21 行 Unicode 码位一致，最小字符串可由 Parser 解析；完整脚本的 Parser 输出中文乱码。全部 `.ps1` 文件原先均为 UTF-8 无 BOM 且包含中文。后续 checkpoint 已将它们统一改为 UTF-8 with BOM，并用静态契约检查强制该格式。Windows PowerShell 官方文档说明：无 BOM 时，Windows PowerShell 将源文件按遗留 ANSI 代码页读取；含非 ASCII 字符的 UTF-8 无 BOM 脚本可能失败。

编码修正实机预检（checkpoint `bdcebf45836fa25effa309799cf21f30653cfbd1`）：Windows 工作副本已检出该精确 SHA，执行 `Test-PowerShellScriptParsing.ps1` 返回 `PowerShell parser: OK (12 scripts)`。该证据仅证明 PowerShell 源文件可解析；安装、构建、Windows 宿主行为和阶段 B 各项仍未执行。

后续 Windows 实机在 `Install-WailsCli.ps1` 的第 6 行得到 `ConvertFrom-Json` 错误，并显示 `versions.json` 中中文内容被错误解码。该文件原先也是 UTF-8 无 BOM；先前预检没有读取配置，因此未捕获这一相邻失败路径。后续 checkpoint 必须将 `versions.json` 保存为 UTF-8 with BOM、在所有读取该文件的脚本中显式指定 `-Encoding UTF8`，并使预检使用默认 Windows PowerShell 5.1 配置读取路径反序列化该文件。

配置编码修正实机预检（checkpoint `a071281db522e828ab3e1738a19b2cd70562a34b`）：Windows 工作副本已检出该精确 SHA，`Test-PowerShellScriptParsing.ps1` 通过。该预检覆盖全部 12 个 PowerShell 脚本的 Parser 和 `versions.json` 的默认 Windows PowerShell 5.1 读取/反序列化路径；它不代表安装、构建或任一 Windows 桌面能力通过。

随后 Windows 实机已完成 `go install` 并显示 `v3.0.0-beta.8`，但 `Install-WailsCli.ps1` 在版本检查处对 `$null` 调用 `.Trim()`。Wails v3 的 `version` 命令使用 Go `println` 输出版本，写入标准错误；脚本原先只读取标准输出。将两个流重定向到 PowerShell 管道后，Windows PowerShell 5.1 在 `$ErrorActionPreference = 'Stop'` 下仍将该 stderr 包装为 `NativeCommandError`。后续 checkpoint 改以 .NET `System.Diagnostics.Process` 直接读取两个流，并检查退出码和空版本文本。

Wails 版本读取修正实机验证（checkpoint `20d17b47fb28d5090cec7d663500cabe8e3fe3c3`）：Windows 输出 `已安装并锁定 wails3 v3.0.0-beta.8：E:\Jetsbrain\go\GoPath\bin\wails3.exe`。该证据证明 Wails CLI 安装与锁定版本校验通过；WebView2、环境检查、构建和全部 Windows 宿主能力仍未执行。

Windows 环境检查失败诊断：目标机报告 `Version=10.0.19045`、`BuildNumber=19045`、`DisplayVersion=22H2`、`UBR=7548`，但 `OSArchitecture` 在中文系统中本地化为 `64 位`。原脚本将该展示文本与英文 `64-bit` 比较，产生误报；后续 checkpoint 改用语言无关的 `[Environment]::Is64BitOperatingSystem`，并以 `BuildNumber=19045` 验证基线。

环境报告实机检查（checkpoint `24a82008b51b64485adb268c4d3d0975cb92edb2`）：Windows、Go、Python、Wails 和 WebView2 的五项检查均返回 `passed=true`，但 Wails 的 `actual.version` 混入 PowerShell `NativeCommandError` 文本。该记录路径仍使用原生命令管道，未复用安装脚本的安全版本读取；后续 checkpoint 必须重新生成无污染的环境报告，才作为阶段 A 的锁定版本证据。

干净环境报告实机验证（checkpoint `51adb5f97d1206a03150536de990ca034edfb424`）：全部检查 `passed=true`，`errors=[]`。实际环境为 Windows 10 22H2 x64、`Version=10.0.19045`、`BuildNumber=19045`、`UBR=7548`；Go `go1.25.0`；Python `3.12.3` x64；Wails `v3.0.0-beta.8` 且 `exitCode=0`；WebView2 Fixed Version Runtime `151.0.4129.78` x64。此证据仅覆盖阶段 A 环境准备，不代表构建或 Windows 宿主能力通过。

构建脚本失败诊断：Windows 已通过 Go 测试与 Python 测试替身（`..`），但 Python `unittest` 将成功摘要写入 stderr，Windows PowerShell 5.1 在 `$ErrorActionPreference = 'Stop'` 下将其作为 `NativeCommandError`。后续 checkpoint 必须以统一的 .NET `Process` 运行器执行 `go mod download`、`go test`、Python 测试与 `go build`，以进程退出码而非 PowerShell stderr 流判定构建成功。

统一进程运行器的后续 Windows 构建失败：`go mod download` 报告未找到模块。原因是 .NET `ProcessStartInfo` 没有显式设置 `WorkingDirectory`；PowerShell 的 `Push-Location` 不保证改变已启动进程的工作目录。后续 checkpoint 必须固定为 spike 根目录，使 `go mod download`、测试和 `go build` 都从包含 `go.mod` 的目录执行。

Windows 构建实机验证（checkpoint `e806479c4470d265e6d1ef50e41b03dc7905df7b`）：Go 测试与两个 Python 测试均通过，生成 `bin\\wails-v3-windows-thin-host.exe`。构建报告记录二进制 SHA-256 为 `A81088882DB593CE0EBCE9E3547584181638F2104576C8FAC702253055BDCCB8`、Go `go1.25.0 windows/amd64` 和 Python `3.12.3`。此证据证明宿主可在目标 Windows 环境构建，不代表任一运行时桌面能力通过。

运行 A 后的单实例检查失败诊断：第二实例退出码为 `0`，但脚本按 `Win32_Process.ExecutablePath` 匹配的宿主计数为空，因此不能判断是 WMI 路径可见性问题还是单实例机制未激活。后续 checkpoint 改为在启动前后按验证二进制的进程名计数，并且必须在当前运行的 `host-events.jsonl` 中观察到 `second_instance_activated`，才将单实例写为通过。

配置加载失效诊断（Windows 实机，宿主构建 checkpoint `e806479c4470d265e6d1ef50e41b03dc7905df7b`）：`host-stderr.log` 记录 `read .spike-run.json: invalid character 'ï' looking for beginning of value`。Windows PowerShell 5.1 用 `Set-Content -Encoding UTF8` 写入了 BOM，而 Go JSON 解码未去除 BOM；宿主因此回退到 `.evidence\unconfigured`，没有采用锁定的 Python、WebView2 路径和计划证据目录。先前汇总脚本读取计划目录，导致 `eventKinds=[]`，并将单实例误报为 `FAIL`。

该误报已被实际日志证伪：`.evidence\unconfigured\host-events.jsonl` 在 `2026-08-13T08:06:06Z` 记录 `second_instance_activated`，同一检查的脚本报告也记录第二实例 `exit=0` 且启动前后均为同一宿主 PID。故不能将 Wails 单实例能力写为失败，也不能把这份回退配置运行写为通过。后续 checkpoint 会使 `Start-Spike.ps1` 写 BOM-free JSON、宿主显式去除 BOM 并在无法加载配置时失败退出；汇总脚本会将此类运行统一标为 `BLOCKED`。修正后必须重新构建并重跑受影响的运行，旧运行只保留为诊断证据。

有效配置运行的单实例实机验证（运行目录 `run-20260813T162942Z-ebe507d8ad38`）：`Invoke-SingleInstanceCheck.ps1` 已成功写出 `single-instance-check.json`。该结果属于新宿主构建和由启动脚本确认的证据目录，待最终 ZIP 回传时与环境/构建报告一并核对。

同一有效运行中，`Invoke-ProcessSupervisorScenario.ps1 -Scenario SingleCrash` 首次报“预期生命周期未出现”。根因在验证脚本：该脚本把单次崩溃同时当作“最后一次崩溃”，错误预期测试替身不重启；而单次异常验收本应验证一次按 `1s` 退避的重启。后续 checkpoint 修正预期并保证失败时仍写出部分 JSON 报告；不改变守护器、Python 测试替身或宿主行为。重跑已通过，旧错误输出不作为守护失败证据。

`RestartLimit` 的第一轮随后又出现同类观察假阴性。现场事件显示 `controlled_crash_requested` 后依次出现 `supervisor_unexpected_exit`（退出码 `71`）、`supervisor_restart_backoff`（`1s`）、新 PID 的 `supervisor_agent_started` 与 `supervisor_health_check_passed`，但原脚本把每 `200ms` 一次、单次可等待 `2s` 的 HTTP 健康轮询观察到“不健康”当作必需条件。短暂端口中断会被单次请求跨越，故报告可出现 `observedUnhealthy=false` 与“已重启且健康”同时为真的组合。

后续 checkpoint 将同一运行目录中新增的、有序宿主守护事件作为首要断言：每轮必须观察到旧 PID 异常退出；需要重启时还必须有期望退避、新 PID 启动和该 PID 健康通过；达到上限时必须有 `supervisor_restart_limit_reached` 且没有后续启动。HTTP 仅保留为崩溃前的就绪保护。新增的 PowerShell 回放测试使用这次 Windows 现场的快速重启轨迹，避免重新引入“必须捕获瞬时不健康窗口”的错误。

首次使用事件等待器时，Windows 在首条事件尚未追加的正常短暂窗口报 `无法将参数绑定到参数“Events”，因为该参数为空数组`。根因是 PowerShell 对必填数组参数默认拒绝空集合；这发生在等待器内部，尚未对守护器作出生命周期断言。后续 checkpoint 为该参数显式允许空集合，使它返回“尚未观察到异常退出”的待继续结果并继续轮询；回放测试覆盖空事件尾部。

该失败现场已经消耗当前 B 宿主的一次重启计数；为了使新脚本仍能按 `1s`、`2s`、`4s` 验证完整重启上限，修正后必须退出当前 B 宿主并启动新的 B 运行。此时还会重新构建一次：构建脚本将记录二进制 SHA-256 与构建 commit，启动脚本会校验该标记并在运行清单分别写入 `hostBuildCommit`、`startupScriptCommit` 与二进制 SHA-256，避免把仅更新脚本后的 Git `HEAD` 误标为宿主二进制的来源。`Cleanup-Spike.ps1` 会保留全部失败现场证据。

证据汇总脚本会同时记录 `hostBuildCommit` 与 `verificationCommit`；这允许仅升级证据脚本时保留已经构建、运行的宿主证据，不把两者混为同一 commit。

### Linux 已完成检查

| 检查 | 结果 | 说明 |
| --- | --- | --- |
| Go 守护单元测试 | 通过 | 覆盖异常退出重启、退避、重启上限和明确退出不重启。 |
| Go `vet` | 通过 | 只检查平台无关守护代码。 |
| Python 测试替身测试 | 通过 | 覆盖健康检查、通知上下文转交和受控异常退出。 |
| 静态边界与交付检查 | 通过 | 确认锁定版本、必需脚本、loopback 绑定与无 SQLite/LLM/领域调度引用。 |
| PowerShell 语法解析 | 通过 | 在 Linux 上使用 PowerShell 解析全部 `.ps1`；不等同于 Windows 执行。 |
| Windows x64 编译预检 | 通过 | 使用锁定 Go/Wails 做交叉编译，只用于发现 API/编译错误，绝不作为桌面行为证据。 |

阶段 A 的剩余不确定性全部属于 Windows 实机：WebView2 Fixed Version 装载、系统托盘、窗口置顶、通知激活、真实登录开机启动和 Windows 子进程生命周期尚未运行。

## 阶段 B：Windows 10 22H2 x64 实机证据

**总体状态：FAIL。** 除置顶小窗的原生关闭后不可恢复外，其余必需能力与宿主边界均有 Windows 实机或平台无关边界证据支持 `PASS`。根据验证计划，任一必需能力 `FAIL` 即整体为 `FAIL`；本结果不宣告 Wails 正式采用，也不开始正式 implementation。

### 证据包与目标环境

- 返回包：`v01-windows-evidence-505cc712c788-20260813T175900Z.zip`，SHA-256 为 `4a94d998d753c5c8c4f00d5ba65c8d11bc48e33762851762d58bbf2bfc0949e0`；已验证 ZIP 完整性。原始 ZIP 不提交仓库，以避免提交本机绝对路径和潜在私人桌面材料。
- 可复核的脱敏机器可读摘录见 [证据摘要](wails-v3-windows-thin-host.evidence-summary.json)，其中按能力列出状态、运行标识、构建/验证 commit、来源文件 SHA-256 与结论；[小窗原生关闭观察](wails-v3-windows-thin-host.overlay-observation.json) 是不含私人路径或桌面材料的补充人工记录。
- 目标机：Microsoft Windows 10 家庭中文版，`10.0.19045` / Build `19045` / DisplayVersion `22H2` / UBR `7548` / x64。
- 工具实测：Go `go1.25.0 windows/amd64`、Python `3.12.3 amd64`、Wails `v3.0.0-beta.8`、WebView2 Fixed Version Runtime `151.0.4129.78` x64。
- 最终验证脚本 commit：`505cc712c7887dd4e4c3277716d4b340e11297ab`。最终 B 运行 `run-20260813T172503Z-505cc712c788` 的宿主二进制构建 commit 为 `05a964966865ca0ad008eb47d6aa58493a34a2fb`、SHA-256 为 `B3616DC4E0B000BA6530D2CF2824365B73AE7587E6FE080D44E4AC3AE2480F08`。该二进制与验证脚本 commit 之间未变更 `main_windows.go` 或 `agent_core/`。
- 有效运行：A 为 `run-20260813T162942Z-ebe507d8ad38`；B 的最终重启上限运行是 `run-20260813T172503Z-505cc712c788`。包内保留较早的 B 运行作为验证脚本诊断记录，不将其假阴性视为守护失败。

#### 原始 ZIP 的受控位置、访问与保留

- 受控位置：证据提供者的 Windows 工作副本中 `spikes/wails-v3-windows-thin-host/.evidence/packages/` 下的同名 ZIP；为避免暴露本机目录，绝对路径不进入仓库。原件不在 Git、PR 文件或公开对象存储中。
- 访问方式：产品治理审查者可在 PR #13 或 Issue #11 请求原件；证据提供者通过同一技术 session 或仓库所有者指定的私有传输方式提供，接收者必须以本节 SHA-256 校验。该 ZIP 曾通过本技术 session 的受控附件通道返回，但该通道不是仓库归档，也不对其服务端保留期作出声明。
- 保留：证据提供者至少保留至 PR #13 的产品治理复审完成、Issue #11 关闭且 #14 的基线决定已经记录。仓库当前没有获批的私有制品库；此后是否受控归档或删除，由证据提供者和仓库所有者明确确认。不得将原件复制进仓库。

| 必需项 | 状态 | Windows 实机证据与结论 |
| --- | --- | --- |
| 托盘、关闭与单实例 | PASS | `manual-observations.json` 的 `tray_close_keeps_host`、`tray_restores_main` 均为 `PASS`；A 的 `host-events.jsonl` 有 `main_window_hidden_on_close`、`main_window_shown`、明确退出和守护停止。`single-instance-check.json` 记录第二实例 `exit=0`、启动前后为同一 PID `24752`、`second_instance_activated=true`。 |
| 置顶小窗 | FAIL | 菜单的显示/隐藏和保持置顶（人工 A3/A4）均通过，日志有 `overlay_shown` / `overlay_hidden`。但用户在目标机重复观察到：显示小窗后点击原生标题栏叉号，再选“显示置顶演示小窗”不再显示；重启宿主才可恢复。该正常关闭路径使同一小窗不能再次显示，故能力整体不通过。 |
| 开机启动 | PASS | 人工 A6 为 `PASS`：真实注销/登录后观察到一个宿主和一个测试替身并已禁用启动项。A 日志记录 `autostart_enabled`、登录后的 `host_starting` / 测试替身健康，以及 `autostart_disabled`。 |
| 可交互通知与上下文返回 | PASS | 人工 A5 为 `PASS`；A 宿主日志记录 `notification_sent`、`notification_response_received`、`notification_context_routed`，同运行的 `agent-core-events.jsonl` 记录 `notification_context_received`，上下文标识为 `v01-demo-context-001`。 |
| Python 进程守护 | PASS | A 的 `process-supervisor-SingleCrash.json` 通过一次异常后的重启；最终 B 的 `process-supervisor-RestartLimit.json` 通过四次受控异常：`9264→2620`（`1s`）、`2620→7060`（`2s`）、`7060→12964`（`4s`），第 4 次异常后记录 `supervisor_restart_limit_reached` 且无新 PID。A 日志还记录 `supervisor_explicit_stop_completed`；最终候选汇总在清理后记录宿主与测试替身进程数均为 `0`、`orphanCheck=PASS`。 |
| 宿主边界 | PASS | 静态边界检查通过：Wails 宿主和测试替身不含 SQLite、LLM、领域调度或权威状态，测试替身只绑定 `127.0.0.1`。Windows 通知上下文也经 localhost 测试替身接收。Windows 宿主二进制对应的 `main_windows.go` / `agent_core/` 与已检查版本未发生后续变更。 |

### 置顶小窗失败根因、影响与替代路线

根因是验证宿主创建 overlay 后没有为 `events.Common.WindowClosing` 注册钩子。Windows 原生叉号触发默认关闭监听器，该监听器把窗口标记为已销毁并从 Wails 窗口表移除；随后 `showOverlay()` 虽调用 `Show()`，但销毁窗口仍持有非空实现对象，无法重新运行创建流程。主窗口已有“取消关闭并隐藏”的钩子，overlay 没有，源码与 Windows 实机现象一致。

影响是用户一次常规关闭小窗后，托盘的“显示置顶演示小窗”失效，必须重启宿主，因而不能作为可靠的当前下一步行动/立即开始呈现入口。

不破坏智能体核心边界的最小替代路线是：在同一可替换薄宿主内，为 overlay 注册与主窗口等价的关闭钩子，取消原生关闭并调用 `Hide()`；或禁用/隐藏 overlay 的原生关闭按钮，只保留托盘“隐藏”动作。两者都不访问 SQLite、不保存领域状态，也不改变 localhost API。该 spike 未实现或复测该路线；若产品治理线程决定继续，应以新任务重新验证“显示 → 原生关闭 → 再显示”路径。若该路径在后续 Wails 版本仍不可靠，可在不改变智能体核心协议的前提下评估另一桌面宿主。

### 冲突与未决风险

- 没有发现与产品范围、领域模型或 ADR-0008～0011 的冲突。失败发生在桌面宿主的窗口生命周期适配层；报告的替代路线保持 Wails/未来宿主可替换、智能体核心唯一状态源和 loopback API 边界。
- 未决风险：本次只能证明锁定 Wails beta.8 在这台 Windows 10 22H2 x64 目标机上的行为；beta 版本升级、其他 Windows 版本、正式安装器/更新路径均不在本次验证范围内。
- Windows PowerShell 5.1 对 UTF-8 BOM 和原生命令 stderr 的兼容性问题已在验证脚本中处理，但这只是 spike 工具链风险记录，不构成正式产品安装器设计。

后续由产品治理主线程依据本结果决定是否修复后复验、升级/更换宿主或更新 MVP 构建就绪门槛；本技术 session 不作 Wails 正式采用决定。
