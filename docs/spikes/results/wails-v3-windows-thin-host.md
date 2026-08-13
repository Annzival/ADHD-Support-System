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

**状态：BLOCKED。** Windows PowerShell 5.1 已通过脚本解析、配置反序列化和 Wails CLI 安装/版本校验，但环境检查将中文系统本地化的架构文本误判为非 x64。修正 checkpoint 必须在 Windows 上通过环境检查，才可重新开始阶段 B。该状态不是任何 Windows 能力的 `PASS`，也不满足 MVP 构建就绪门槛。

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

**总体状态：BLOCKED（等待用户在指定 checkpoint 的交互式 Windows 桌面会话执行）。**

| 必需项 | 状态 | 必需的 Windows 实机证据 | 当前证据 |
| --- | --- | --- | --- |
| 托盘、关闭与单实例 | BLOCKED | 关闭后托盘常驻、托盘恢复、第二实例不独立运行。 | 尚未收到。 |
| 置顶小窗 | BLOCKED | 显示、隐藏、保持置顶，且不改变测试替身状态。 | 尚未收到。 |
| 开机启动 | BLOCKED | 启用、真实注销/登录启动、单实例、禁用。 | 尚未收到。 |
| 可交互通知与上下文返回 | BLOCKED | 通知操作、正确窗口激活、上下文标识转交到测试替身。 | 尚未收到。 |
| Python 进程守护 | BLOCKED | 健康检查、单次异常重启、连续异常、`1s/2s/4s` 退避、重启上限、明确退出、无孤儿进程。 | 尚未收到。 |
| 宿主边界 | BLOCKED | 代码与运行证据证明没有 SQLite、领域调度、干预规则、LLM 或权威状态。 | Linux 静态检查待阶段 A 完成；不能替代 Windows行为。 |

## 阶段 B 填写区

收到证据后补充：

- Windows 精确版本、DisplayVersion、UBR、架构、WebView2/Go/Wails/Python 实际版本；
- Windows 执行 commit SHA 与 Issue #11 checkpoint SHA 是否一致；
- 每项 `PASS`、`FAIL` 或 `BLOCKED` 的脚本日志、人工观察、截图/录屏摘要和受控证据位置；
- 若有 `FAIL`：最小根因、影响和至少一条不破坏 localhost API、唯一状态源与薄宿主边界的替代路线；
- 未决风险，以及是否出现与产品范围、领域模型或 ADR-0008～0011 的冲突。

在全部必需项和边界检查均有 Windows 实机 `PASS` 前，不宣告 Wails 正式采用，也不开始正式 implementation。
