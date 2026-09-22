# I-01 Windows 实机验收

当前没有 Windows 运行证据。下列步骤在 Windows 10 22H2 x64 实机执行，不能以 Linux 自动结果或交叉编译代替。

使用独立 checkout 和合成数据。开始前保留一个明确结束点：每轮只做下面一个路径，完成后从托盘退出；中途需要停下时也可退出，记录当前步骤，随后用 `Resume` 回到同一数据库。不要为了填满清单反复重跑已经通过的相同分支。

## 前置与启动

目标版本：Windows 10 22H2 / Build 19045 x64，Python 3.12.3 x64，Go 1.25.0 windows/amd64，Wails `v3.0.0-beta.8`（由 go.mod 锁定），Fixed WebView2 151.0.4129.78 x64。脚本检查版本、Python 位数和 WebView2 PE 架构；如果不匹配，保留输出并回传，不自行升级替代。无需安装 Wails CLI 或 Node。

代码／测试／脚本锚点为 `e262f96fb2cca99d526dac5feff30e5e53fb5a91`，见 [Draft PR #32](https://github.com/Annzival/ADHD-Support-System/pull/32)。可从其分支最新干净提交构建，脚本会记录实际 HEAD；若此前已有运行，应回到该运行记录的 commit 后再 Resume。

在已检出本任务 checkpoint 的仓库根目录打开 PowerShell。将第一行换成此前 spike 使用的固定 WebView2 目录；不要使用浮动 Evergreen 目录。

```powershell
$fixedWebView2 = 'D:\Tools\WebView2\151.0.4129.78'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case ConfirmedDuration -WebView2Path $fixedWebView2
```

脚本先运行 Python 和 Go 自动检查并构建桌面，再创建开发夹具，约 45 秒后到点。它会输出本轮 `DataDirectory`。复制这个实际目录供后续命令使用：

```powershell
$runData = '这里替换为脚本输出的 DataDirectory'
```

`Run` 是对合成行动、开始时间和测试时长的显式开发确认，不是用户方案导入或正式启用流程。如果准备过程较慢导致首次机会已错过，不能把被动界面记为成功主动送达；退出后新建一轮，可用 `-StartDelay 90` 留足时间。

## 四条短路径

每条用新的 `Run` 创建独立数据；一次只开一个宿主。清单的 `NOT_RUN` 不默认变成 PASS，也不用在每轮重复做全部项目。

| 轮次 | 操作与预期 | 主要场景 |
| --- | --- | --- |
| A：确认时长，检查点前完成 | 到点看见小窗和真实系统通知。点通知的“查看当前行动”，主窗口返回测试行动。点立即开始，会话与首次检查点同时出现；检查点前点已经完成。进入等待收尾后选全部完成，可留空实际用时，再点完成收尾。显示证据已保存、会话已结束。 | EX-01、SES-02 前分支、DESK-04 有效通知 |
| B：检查点后完成、显式跳过 | 新建 ConfirmedDuration 轮次；立即开始后等约 60 秒。检查点只提示核对，不自动完成或循环创建检查点；点已经完成，再跳过收尾。结束后再点通知中心中该轮旧通知，应提示原上下文失效并显示当前状态，无第二个会话。 | SES-02 后分支、EX-01 跳过、DESK-04 旧通知 |
| C：时长确认、原生关闭收尾 | 新建 MissingDuration 轮次；立即开始只打开时长确认。打开、取消时分别保存 Snapshot，均没有会话／检查点，干预保持未决。再确认 1 分钟后检查，观察同时建会话与检查点。报告完成后点窗口原生叉号；从托盘重开，应已保存最小证据并结束。 | EX-02、关闭等同跳过 |
| D：重启状态 | 新建 ConfirmedDuration 轮次并开始。运行下述 RestartCore，观察暂不可用及重连；会话 ID 和检查时间不变，不重复通知。报告完成后再次 RestartCore，等待收尾仍占位置。跳过收尾后从托盘退出，再 Resume 同一轮，结束状态与唯一证据不变。 | REC-03／04 适用部分、AT-02、DESK-03 |

C 轮命令：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case MissingDuration -WebView2Path $fixedWebView2
```

每轮可额外做一次“小窗原生叉号 → 托盘显示当前行动”，确认窗口仍可重开。执行中的关闭只隐藏；等待收尾时关闭会先提交跳过。不会把所有五项宿主能力标为已验收。

如果 Windows 通知不可见或不能正确跳转，记录 FAIL 或 BLOCKED 与实际现象；即使小窗可操作也不把 DESK-04 写为 PASS。通知提交成功的程序记录不等于用户已经看到通知，人工观察必须补齐。

## 保存状态与受控 Core 重启

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runData
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode RestartCore -DataDirectory $runData
```

RestartCore 只终止命令行对应本轮目录的单个 Python Core，事先保存快照；若找不到唯一匹配则不终止任何进程。宿主有限守护重启，整轮最多自动重启 3 次。命令行不会打印运行令牌。重连后再 Snapshot；比较 `database_id`、`sessions[].id`、`checkpoints[].id/due_at`、证据与成功事件数量。原窗口没有必要关闭或重新建时长。

完成并从托盘退出后，重新打开同一数据库：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Resume -DataDirectory $runData
```

此操作要求 checkpoint 和二进制哈希一致。它不是 PC 重启验收；完整 PC/开机启动回归属于后续阶段。

## 记录与回传

每轮目录中的 `observations.json` 预置 `NOT_RUN`。只把实际观察的项目改为 `PASS`、`FAIL` 或 `BLOCKED`；补充说明可另存本轮合成观察笔记。四轮合起来须覆盖表格所有要求，不要求每轮每项通过。不要把个人桌面、用户名、个人计划或令牌加入笔记。

退出托盘后收集：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runData
```

回传各轮 `evidence-summary.json`。摘要包括 commit、二进制哈希、版本、合成会话／证据、人工观察和来源文件哈希，状态固定为 `AWAITING_EVIDENCE_REVIEW`，由执行任务核验后再判断。原始 `run.json` 含本机路径，数据库和原始日志留在 `.i01-runs/`，不提交 Git 或公开发布。若需要补充原件，通过当前任务的受控方式提供；至少保留至本任务与 Draft PR 审阅完成。

只有自动与全部本阶段 Windows 证据均经核验才能报告 I-01 PASS。即便通过，也不是完整 MVP 或 dogfooding 准入，不自动进入 I-02。
