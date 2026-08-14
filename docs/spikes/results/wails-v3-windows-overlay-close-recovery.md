# V-01R：Wails v3 置顶小窗原生关闭恢复复验

## 任务边界与当前状态

- 任务类型：technical spike；对应 [Issue #14](https://github.com/Annzival/ADHD-Support-System/issues/14)。
- 基线：PR #13 已合并到 main@0ed8d4b，Issue #11 已关闭。V-01 只在“原生叉号关闭后无法再次显示置顶小窗”这一项失败。
- 锁定环境：Windows 10 22H2 x64、Wails v3.0.0-beta.8、Go 1.25.0、Python 3.12.3、WebView2 Fixed Version Runtime 151.0.4129.78 x64。不得升级其中任何版本。
- Linux 准备状态：READY_FOR_WINDOWS。已通过 git diff --check、Python 静态契约检查和 Python 测试替身测试；checkpoint 推送后即可交给目标 Windows PC。当前 Linux 环境没有 Go 或 PowerShell，因而未把它们的缺失伪装成 Windows 或 Wails 行为检查。
- Windows 最终状态：BLOCKED。当前仓库没有 Windows 实机运行、逐轮观察、二进制哈希或原始证据包；不能根据 Linux、源码或旧 V-01 证据外推 PASS。
- 尝试次数：1 次实现尝试，0 次 Windows 实机尝试。该实现仅为 overlay 的 WindowClosing → Cancel + Hide；在得到首次实机结果前不得开始第二次生命周期适配。

本结果文档不改变产品范围、领域模型、已有 ADR 或 Agent Core API，不宣告 Wails 正式采用，也不开始 MVP implementation。

## 首次最小实现

只在 Windows 专属验证宿主中做了以下生命周期适配：

1. overlay 注册 events.Common.WindowClosing hook；
2. hook 调用 Cancel、Hide，并记录 overlay_hidden_on_close；
3. 再次显示前检查 overlay 是否仍在 Wails 窗口表中；若默认关闭仍意外销毁它，记录 overlay_destroyed_before_show 而不是伪造恢复成功；
4. 保持原有 SetAlwaysOnTop、Show、Focus 和 overlay_shown 日志。

该改动不访问 SQLite，不保存领域状态，不执行领域调度或干预规则，不调用 LLM，也不修改 Python 测试替身、通知、开机启动、完整守护上限或单实例实现。

静态契约检查会验证上述 hook、三轮 Windows 复验脚本、脱敏摘要字段和原始 ZIP 受控保留字段。它不是 Windows 桌面行为的 PASS。

## Windows 实机执行

仅在交互式 Windows 10 22H2 x64 桌面会话执行。先切换到 Issue #14 和 Draft PR 标明的精确 checkpoint，确认工作区干净；不要从 PR #13 的旧 head 执行，也不要手工修改源码。

此复验只重新构建受本次 Go 代码影响的验证宿主，并运行关闭恢复路径。不要运行原 V-01 的 Record-ManualObservations、Test-ValidationEvidence、开机启动、通知或完整守护上限场景。

在 spikes/wails-v3-windows-thin-host 目录依序运行：

    Set-ExecutionPolicy -Scope Process Bypass
    .\scripts\Test-PowerShellScriptParsing.ps1
    .\scripts\Check-WindowsEnvironment.ps1
    .\scripts\Build-Spike.ps1
    .\scripts\Start-Spike.ps1
    .\scripts\Invoke-OverlayCloseRecovery.ps1

最后一个脚本逐轮给出固定步骤并收集：

- 3 轮“托盘显示 → 原生叉号 → 托盘再次显示”；
- 每轮首次显示和再次显示均由人工确认可见、置顶；
- 每轮原生关闭后由日志确认 overlay_hidden_on_close，并核对一个宿主、一个 Python 测试替身和健康检查；
- 3 轮后的一次托盘显式隐藏/显示；
- overlay_shown、overlay_hidden_on_close 与 overlay_destroyed_before_show 的事件关系。

无论该脚本返回 PASS、FAIL 还是 BLOCKED，都不要改代码或进行第二次尝试。先从托盘选择“退出验证宿主”，等待宿主和测试替身退出，再运行：

    .\scripts\Collect-OverlayCloseRecoveryEvidence.ps1

返回两个文件给本技术 session：

1. 原始 ZIP（只经受控私有渠道返回，不提交 Git）；
2. 同目录生成的 v01r-overlay-close-recovery-summary-<commit>.json 脱敏摘要。

如果复验脚本非零退出，它仍会写出逐轮 assessment；继续运行收集脚本即可保留 FAIL/BLOCKED 现场。只有该证据显示了与首次实现不同且明确的根因，才允许讨论第二次、仍限 overlay 生命周期的最小尝试。

## 要求的证据与判定

| 验收条件 | Windows 证据 | 当前状态 |
| --- | --- | --- |
| 3 轮原生关闭恢复 | 每轮人工观察和 overlay_shown / overlay_hidden_on_close 日志 | BLOCKED |
| 保持置顶 | 每轮首次显示、再次显示及三轮后的托盘显示观察 | BLOCKED |
| 宿主、托盘、Agent Core 单实例与健康 | 每轮原生关闭后的进程数量与 loopback 健康检查 | BLOCKED |
| 无意外销毁 | 没有 overlay_destroyed_before_show，且再次显示成功 | BLOCKED |
| 托盘显式隐藏/显示 | 三轮后的人工观察与 overlay_hidden / overlay_shown 日志 | BLOCKED |
| 薄宿主边界 | 静态契约检查和未改动的 Agent Core 接口 | Linux 静态检查待记录；Windows 行为不外推 |
| 身份与可复核性 | 环境报告、build marker、run.json、二进制 SHA-256、原始 ZIP SHA-256 与脱敏摘要相互对应 | BLOCKED |

全部必需项有对应 Windows 实机证据才可以写 PASS；任何必需项 FAIL 则整体 FAIL；环境或证据不足则整体 BLOCKED。

## 证据处理与限制

收集脚本会生成机器可读摘要，其中只包含能力状态、逐轮观察、版本、提交标识、二进制和文件 SHA-256、事件种类及进程数量；不包含绝对路径、Windows 账户名、进程 ID、原始日志正文、截图或录屏。

原始 ZIP 留在证据提供者 Windows 工作副本的 spikes/wails-v3-windows-thin-host/.evidence/packages/。审查者可在 Issue #14 或对应 Draft PR 请求，证据提供者通过本技术 session 或仓库所有者指定的私有方式提供，并以摘要中的 SHA-256 校验。证据提供者应至少保留原件至 Draft PR 复审完成且 V-01R 结论已记录；不得把原始 ZIP、截图或录屏加入 Git 或公开对象存储。

已知限制：

- Linux 环境不能操作 Windows 原生叉号、置顶、托盘或 WebView2，因此只能运行平台无关检查；
- 锁定的是 Wails beta.8 在目标机上的行为，不能推广到新版 Wails、其他 Windows 版本或正式安装器；
- 此次只复验受 overlay 生命周期改动影响的路径，不重新认证 V-01 已通过的开机启动、通知和完整守护上限。

## 冲突回报

截至 Linux checkpoint，未发现与 ADR-0008～0011、ADR-0013、产品范围或领域模型的冲突。改动仍位于可替换桌面宿主的窗口生命周期适配层；关闭或隐藏小窗不改变 Agent Core 的权威状态。若 Windows 证据表明必须修改 Agent Core、领域规则、产品范围或 ADR，立即停止并回传直接委托者，而不在本 PR 中扩张。
