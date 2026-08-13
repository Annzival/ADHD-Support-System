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

**状态：BLOCKED。** 两个 Windows checkpoint 均在执行 `Install-WailsCli.ps1` 时得到 PowerShell 字符串终止符解析错误；必须先取得可复现的 Windows 解析与工作副本字节证据。该状态不是任何 Windows 能力的 `PASS`，也不满足 MVP 构建就绪门槛。

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

根因目前记录为 `UNCONFIRMED`：目标 commit 在 Linux PowerShell AST 中可解析，但 Windows 实机得到的解析错误与该行相关。新的 checkpoint 必须从 README 的第 3 步重新执行，且不得把原 checkpoint 的 Windows 结果与新 checkpoint 混合。

### Windows 解析阻塞更新（2026-08-13）

修正 checkpoint `6e914ade164d2799b4ab81209e9953e503287d96` 在 Windows 实机仍于新第 21 行报告同样的单引号字符串终止符错误。该行的 `'bin\wails3.exe'` 是 PowerShell 的有效单引号字符串，反斜杠不转义单引号；因此不能把症状归因为已确认的 PowerShell 语法问题，也不能继续以改写该表达式作为修复。

下一步必须采集：PowerShell 版本、`git status`、该文件相对 `HEAD` 的 diff、实际第 21 行与 Git 对象第 21 行的 Unicode 码位，以及对该文件和最小字符串片段的 PowerShell Parser 结果。采集完成前不生成 Bash 替代脚本；改用 Bash 不能修复检出后文件字节被改写或调用环境异常的可能根因。

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
