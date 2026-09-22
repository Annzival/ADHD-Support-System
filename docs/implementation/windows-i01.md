# I-01 Windows 实机验收：逐轮操作手册

这份手册用于实际操作和回传证据。共 A、B、C、D 四轮，每轮使用独立测试数据，一次只运行一轮。**可以先完成 A 轮并回传，确认流程可用后再做其余轮次；不必一次做完。**

目前仅收到 Windows 准备阶段的失败反馈，尚未确认桌面验收通过。本手册不会把脚本运行成功当作 I-01 PASS。

## 先看本轮要做什么

| 轮次 | 本轮只验证什么 | 正常结束时看到什么 |
| --- | --- | --- |
| A | 到点通知 → 立即开始 → 检查点前报告完成 → 完成收尾 | 已保存执行证据，会话已结束 |
| B | 等检查点到达 → 报告完成 → 跳过收尾 → 点击旧通知 | 提示原通知失效，仍显示已结束状态 |
| C | 打开／取消时长确认 → 确认开始 → 报告完成 → 点击窗口叉号 | 从托盘重开后，会话已经结束 |
| D | 执行中重启 Core → 等待收尾时重启 Core → 结束后退出并重开应用 | 原会话和检查时间保留，结束后仍只有原证据 |

只使用合成行动“开发验收：在空白文档写下一行测试文字”。不需要真实学习／求职方案。每轮启动后的等待时间设为 90 秒；默认开始后的首次检查为 60 秒。四小时是每轮测试数据的有效窗口，不是要求连续测试四小时。

## 0. 一次性准备

### 0.1 确认代码和环境

在 Windows 仓库根目录打开 PowerShell。后面所有命令都在这个目录、这个 PowerShell 窗口执行。

先确认应用已经从托盘退出，再运行：

```powershell
git branch --show-current
git pull --ff-only
git status --short
git rev-parse HEAD
```

预期：分支为 `agent/implement-mvp-first-slice`；`git status --short` 没有输出。记下最后一条的提交号。若分支不同、拉取失败或仍有变更，先把输出发回当前任务，不删除或提交不明文件。根目录 `.evidence/`、`.tools/`、`.i01-runs/` 已忽略，保留原处即可。

**同一轮从 Run 到 Collect 期间不要再拉取代码。** Snapshot、Resume、Collect 会核对本轮启动时的 commit；更新代码应放在两轮之间。已完成的轮次可以来自不同 commit，回传时分别保留身份即可。

脚本会检查下列锁定环境，不需要另装 Wails CLI 或 Node：

| 项目 | 要求 |
| --- | --- |
| Windows | Windows 10 22H2 / Build 19045 x64 |
| Python | 3.12.3 x64 |
| Go | 1.25.0 windows/amd64 |
| Wails | go.mod 中的 v3.0.0-beta.8 |
| WebView2 | Fixed Version 151.0.4129.78 x64，沿用此前验证的目录 |

### 0.2 只填写两个本机路径

把下面两行换成自己的实际路径。WebView2 路径应是**直接包含 `msedgewebview2.exe` 的目录**。若当前窗口已设置正确的 `$fixedWebView2`，保留原值，不用换成示例。

```powershell
$fixedWebView2 = 'D:\Tools\WebView2\151.0.4129.78'
$pythonExe = 'D:\Tools\Python312\python.exe'
Test-Path (Join-Path $fixedWebView2 'msedgewebview2.exe')
Test-Path $pythonExe
```

后两条都应返回 `True`。显式指定 `$pythonExe` 可以避免 `py` 并非 Python Launcher 时的选择器问题；版本／位数校验仍会执行。

### 0.3 为四轮准备不同的目录名

复制执行一次。这里只创建本批次的父目录，**不要提前创建 A、B、C、D 子目录**，它们由各轮 Run 创建。

```powershell
$batchDir = Join-Path (Get-Location).Path ('.i01-runs\' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $batchDir | Out-Null
$runA = Join-Path $batchDir 'A'
$runB = Join-Path $batchDir 'B'
$runC = Join-Path $batchDir 'C'
$runD = Join-Path $batchDir 'D'
$batchDir
```

记下最后输出的批次目录。命令里的 `$runA` 始终指 A 轮，其他类推；不必反复复制脚本输出的 `DataDirectory`。

如果已经有有效的本轮运行，不要重新 Run。将对应变量（例如 `$runA`）设为那次输出的实际 `DataDirectory`，继续该轮尚未完成的步骤。已完成的有效轮次可以直接回传，不必为改用这份文档重做。

关闭 PowerShell 后，变量会消失。重新打开时先回到仓库根目录，重新设置 0.2 的两个路径，再恢复已有批次：

```powershell
$batchDir = '这里替换为之前记下的批次目录'
$runA = Join-Path $batchDir 'A'
$runB = Join-Path $batchDir 'B'
$runC = Join-Path $batchDir 'C'
$runD = Join-Path $batchDir 'D'
```

## 每轮共用的记录规则

- **Run**：新建测试数据、检查环境、运行自动测试、构建并启动桌面。不要用它继续已有轮次。
- **Snapshot**：保存此刻的数据库状态，不改变执行结果。文件名为本轮目录中的 `snapshot-时间戳.json`；保留所有快照即可，**无需手工编辑或比较 JSON**，回传后由我核验。
- **RestartCore**：仅终止本轮的 Python Core，保留桌面，让宿主尝试重连。不是重启电脑。
- **Resume**：退出应用后，重新打开本轮原数据库。不是开始新一轮。
- **Collect**：应用从托盘退出后，保存最终状态并生成本轮 `evidence-summary.json`。

人工观察填在每轮的 `observations.json`。下文给出打开命令和本轮要填写的字段。用记事本仅替换引号中的 `NOT_RUN`，保留字段名、引号、逗号和其他内容：

| 填写值 | 何时使用 |
| --- | --- |
| `PASS` | 自己实际看到了该字段要求的全部现象 |
| `FAIL` | 已执行该操作，但结果与预期不同 |
| `BLOCKED` | 被前置错误或环境问题挡住，无法执行 |
| `NOT_RUN` | 本轮不负责或还没做，保持原值 |

例如，只有亲眼确认通知出现且能返回正确行动，才把 `"arrivalAndCorrectNotification": "NOT_RUN"` 改为 `"arrivalAndCorrectNotification": "PASS"`。**不要把整份文件批量改成 PASS。**

若中途出错，停止依赖该步骤的后续操作，记录轮次、步骤编号和实际现象，按文末“遇到错误或需要暂停”处理。

## A 轮：检查点前完成，再完成收尾

### A1. 启动

确认上一轮宿主已退出，执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case ConfirmedDuration -StartDelay 90 -WebView2Path $fixedWebView2 -PythonExecutable $pythonExe -DataDirectory $runA
```

预期：自动检查和构建通过，桌面主窗口打开，显示测试行动和等待时间。开始时间按夹具创建时起算，约 90 秒后到点；不包含此前构建耗时。

如果脚本报错或窗口没有出现，停在 A1，回传错误，不把本轮记为通过。

### A2. 看通知并返回行动

1. 等待约定开始时间，不提前点击“立即开始”。
2. 到点后观察：置顶小窗出现，Windows 系统通知也出现。
3. 点击通知中的“查看当前行动”。若横幅已消失，按 `Win+A` 打开通知中心，找到本应用通知并展开。
4. 预期主窗口打开或获得焦点，显示这条测试行动。注意不要点其他应用或旧轮次的通知。

只有四步都符合预期，才可把本轮 `arrivalAndCorrectNotification` 记为 PASS。

### A3. 开始，然后在首次检查前报告完成

先读完这三步再操作，期间不需要切回 PowerShell：

1. 点击“立即开始”。
2. 确认出现“执行会话已建立”和具体检查时间；下方可见会话与检查点标识。
3. 在 60 秒检查时间到达前点击“已经完成”。预期出现“已记录完成报告，正在等待收尾”。

现在回 PowerShell，保存**A 轮第 1 份快照：等待收尾**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runA
```

如果检查点已经先到达，如实记录这一点；该次不算“检查点前完成”，不要为了通过而修改记录。

### A4. 完成收尾

1. 返回应用，结果保持“全部完成”。
2. “实际用时”留空即可。
3. 点击“完成收尾”。
4. 预期显示“已保存执行证据，会话已结束”和“已确认全部完成”。

### A5. 填观察记录并收集

```powershell
notepad (Join-Path $runA 'observations.json')
```

按实际情况填写以下四项，其他字段保持原值，保存后关闭记事本：

| 字段 | 本轮 PASS 依据 |
| --- | --- |
| `arrivalAndCorrectNotification` | A2：小窗、真实通知、点击后正确行动与焦点 |
| `startAndFirstCheckpoint` | A3：开始后同时显示会话与首次检查点 |
| `completionBeforeCheckpoint` | A3：首次检查前报告完成并进入等待收尾 |
| `finishClosure` | A4：完成收尾后显示持久结束 |

在 Windows 右下角托盘找到本应用图标（可能在 `^` 隐藏图标中），打开菜单并选择“退出开发验收”。**主窗口叉号不等于退出应用。** 然后执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runA
```

A 轮结束。现在可以按文末方式回传 A 轮，或在有余力时继续 B 轮。

## B 轮：检查点后完成、跳过收尾、打开旧通知

### B1. 启动并进入执行

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case ConfirmedDuration -StartDelay 90 -WebView2Path $fixedWebView2 -PythonExecutable $pythonExe -DataDirectory $runB
```

1. 等待约 90 秒到点。
2. **本轮先不点系统通知，也不要清空通知中心**，留待 B4 检查旧通知。
3. 从小窗或托盘“显示主窗口”进入应用，点击“立即开始”。
4. 确认会话与首次检查点出现。

### B2. 等到首次检查点

等待约 60 秒，直到界面出现“约定的检查时间已到”。此时应仍由你选择“已经完成”，系统不应自己宣布完成，也不应自动创建下一检查点。

保存**B 轮第 1 份快照：检查点已到**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runB
```

### B3. 报告完成并跳过收尾

1. 点击“已经完成”，确认出现等待收尾界面。
2. 不填可选字段，点击“跳过收尾”。
3. 确认显示“已保存执行证据，会话已结束”。
4. 保存**B 轮第 2 份快照：打开旧通知之前**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runB
```

### B4. 打开这轮已过期的通知

1. 按 `Win+A` 打开 Windows 通知中心。
2. 找到**本轮先前保留的开始或检查点通知**，展开后点击“查看当前行动”。
3. 预期应用提示“原通知上下文已失效，当前显示的是 Core 最新状态”，仍然是已结束结果，不出现新的会话或新的“立即开始”。
4. 保存**B 轮第 3 份快照：打开旧通知之后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runB
```

如果旧通知已被系统清掉、无法点击，将此项记为 BLOCKED 并说明，不把它记为 PASS。三份快照会用于核对没有额外会话或证据。

### B5. 填观察记录并收集

```powershell
notepad (Join-Path $runB 'observations.json')
```

| 字段 | 本轮 PASS 依据 |
| --- | --- |
| `startAndFirstCheckpoint` | B1：开始后显示会话及首次检查点 |
| `completionAfterCheckpoint` | B2～B3：检查点到达后明确报告完成 |
| `skipClosure` | B3：跳过收尾后稳定结束 |
| `staleNotificationShowsCurrentContext` | B4：旧通知返回失效提示及当前结束状态 |

保存文件，从托盘选择“退出开发验收”，再收集：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runB
```

## C 轮：取消时长确认、确认开始、原生叉号跳过收尾

### C1. 启动未确认时长的对照轮次

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case MissingDuration -StartDelay 90 -WebView2Path $fixedWebView2 -PythonExecutable $pythonExe -DataDirectory $runC
```

等待约 90 秒到点。进入主窗口，应显示“尚未确认本次时长”。

### C2. 打开确认但不提交

点击“立即开始”。预期只打开时长确认界面，尚未显示执行会话。保持该界面，保存**C 轮第 1 份快照：确认界面打开但未提交**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runC
```

### C3. 取消

点击界面中的“取消”。预期返回未开始状态，仍可再次选择“立即开始”。保存**C 轮第 2 份快照：取消后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runC
```

这两份快照应均没有会话／检查点，开始干预保持未决；不需要你手工核对 JSON，我会在回传后检查。

### C4. 确认开始并检查小窗可重开

1. 再次点击“立即开始”。输入 **5 分钟**，给后续操作留出时间。
2. 点击“确认时长并开始”。预期出现会话及约 5 分钟后的检查时间。
3. 从托盘菜单选择“显示当前行动”，在小窗标题栏点击原生 `×`。
4. 再从托盘选择“显示当前行动”。预期小窗能再次出现，仍显示同一执行会话。
5. 保存**C 轮第 3 份快照：确认开始后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runC
```

此时仍在执行中，关闭小窗只应隐藏，不是报告完成或结束会话。

### C5. 用主窗口叉号关闭收尾

1. 从托盘“显示主窗口”，点击“已经完成”。
2. 确认主窗口已显示等待收尾界面。
3. 保存**C 轮第 4 份快照：关闭前的等待收尾**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runC
```

4. 返回主窗口，**不点“完成收尾”或“跳过收尾”**，直接点击主窗口标题栏原生 `×`。
5. 从托盘“显示主窗口”重新打开。预期已保存最小证据，会话已结束。

如果出现保存错误或重开后仍等待收尾，如实记 FAIL；不要再补点跳过，把失败路径伪装成原生关闭通过。

### C6. 填观察记录并收集

```powershell
notepad (Join-Path $runC 'observations.json')
```

| 字段 | 本轮 PASS 依据 |
| --- | --- |
| `cancelDurationLeavesPending` | C2～C3：打开／取消不显示会话，仍可开始；快照待核验 |
| `startAndFirstCheckpoint` | C4：确认 5 分钟后才显示会话和对应检查点 |
| `overlayCloseAndReopen` | C4：执行中的小窗原生关闭后能从托盘重开 |
| `nativeCloseSkipsClosure` | C5：等待收尾时原生关闭，重开后已结束 |

保存文件，从托盘“退出开发验收”，执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runC
```

## D 轮：Core 重启和应用重新打开后的状态

本轮包含 **2 次 Core 重启、1 次完整应用退出再打开**。不重启电脑，不用任务管理器手工寻找进程。若重启失败，停止该步骤后回传，不连续重试消耗宿主的 3 次自动重启限额。

### D1. 启动并开始

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case ConfirmedDuration -StartDelay 90 -WebView2Path $fixedWebView2 -PythonExecutable $pythonExe -DataDirectory $runD
```

到点后点击“立即开始”，确认出现会话与首次检查时间。先保存**D 轮第 1 份快照：执行中，重启之前**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
```

### D2. 第一次重启：执行中

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode RestartCore -DataDirectory $runD
```

1. 保持桌面打开，等待恢复连接。重连较快时，不一定能肉眼看见“暂不可用”。
2. 确认原会话标识和检查时间仍相同；没有让你再次确认一段新的时长，没有重放先前已送达的通知。
3. 若恰好跨过首次检查时间，新出现的首次检查提示可以是正常到点，不把它误认为重复通知；记录实际时序即可。
4. 重连成功后保存**D 轮第 2 份快照：执行中，重启之后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
```

若约 15 秒后仍未恢复连接，将本步记 FAIL 并停止；15 秒只是人工排查等待上限，不是产品期限。

### D3. 第二次重启：等待收尾

1. 在应用点击“已经完成”，确认进入等待收尾。
2. **不要关闭窗口，也不要完成／跳过收尾。**
3. 保存**D 轮第 3 份快照：等待收尾，重启之前**，随后执行第二次重启：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode RestartCore -DataDirectory $runD
```

4. 等待连接恢复。预期仍显示等待收尾，未静默结束、未创建另一会话。
5. 保存**D 轮第 4 份快照：等待收尾，重启之后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
```

### D4. 结束后退出并重新打开同一轮

1. 点击“跳过收尾”，确认显示会话已结束。
2. 保存**D 轮第 5 份快照：结束后，退出之前**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
```

3. 从托盘菜单选择“退出开发验收”。
4. 执行 Resume，**不要执行 Run**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Resume -DataDirectory $runD
```

5. 预期应用仍显示原会话已结束，没有新的开始提示或重复结果。
6. 保存**D 轮第 6 份快照：应用重新打开后**：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runD
```

### D5. 填观察记录并收集

```powershell
notepad (Join-Path $runD 'observations.json')
```

| 字段 | 本轮 PASS 依据 |
| --- | --- |
| `coreRestartKeepsSameSessionAndCheckpoint` | D2：重连后同一会话与检查时间，未重放旧通知 |
| `awaitingClosureSurvivesRestart` | D3：重连后仍等待收尾，未静默释放 |
| `endedStateSurvivesRestart` | D4：重新打开同一数据库后仍结束，无新增结果；数量由快照核验 |

保存文件，再次从托盘“退出开发验收”，执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runD
```

六份快照按时间顺序分别对应 D1、D2、D3 重启前、D3 重启后、D4 退出前、D4 重开后。RestartCore 另写的 `before-core-restart.json` 可能被第二次重启覆盖，因此不能用它代替上述六份快照。

## 最终回传什么

### 完成一轮即可回传，不用等四轮齐全

每轮 Collect 成功后，需要的文件是：

| 文件 | 用途 |
| --- | --- |
| `evidence-summary.json` | 本轮 commit、构建身份、环境、人工观察与结束结果 |
| 所有 `snapshot-*.json` | 上述指定步骤的中间状态，由我比较身份、检查时间与数量 |
| `final-state.json` | 最终完整合成状态，用于与中间状态交叉核验 |
| `desktop-evidence.jsonl`（若生成） | 原生呈现请求、通知回调与 Core 连接的有限事件 |

以上文件由本次合成测试生成。不需要提供截图或录屏；若某步异常且截图能说明问题，可另行只截应用窗口。

**不回传整个运行目录。** `run.json` 含本机路径；SQLite 数据库、工具目录、原始自动测试日志继续在本机保留。上表文件若曾被手工添加个人内容，先移除那部分再回传。

### 用命令把已完成轮次打成一个包

下面默认收集 A 轮。完成更多轮后，把第一行改为对应目录，例如 `@($runA, $runB, $runC, $runD)`。仅填写已经 Collect 成功的轮次。

```powershell
$completedRuns = @($runA)
$ErrorActionPreference = 'Stop'
$returnDir = Join-Path $batchDir ('return-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $returnDir | Out-Null
foreach ($dir in $completedRuns) {
    if (-not (Test-Path (Join-Path $dir 'evidence-summary.json'))) {
        throw "Collect has not completed: $dir"
    }
    $roundName = Split-Path $dir -Leaf
    $targetDir = Join-Path $returnDir $roundName
    New-Item -ItemType Directory -Path $targetDir | Out-Null
    Copy-Item (Join-Path $dir 'evidence-summary.json') $targetDir
    Copy-Item (Join-Path $dir 'final-state.json') $targetDir
    Get-ChildItem -LiteralPath $dir -Filter 'snapshot-*.json' -File | Copy-Item -Destination $targetDir
    $desktopLog = Join-Path $dir 'desktop-evidence.jsonl'
    if (Test-Path $desktopLog) { Copy-Item $desktopLog $targetDir }
}
$zipPath = $returnDir + '.zip'
Compress-Archive -Path (Join-Path $returnDir '*') -DestinationPath $zipPath
Get-FileHash -Algorithm SHA256 $zipPath
$zipPath
```

将最后输出的 ZIP 文件上传到**当前 I-01 执行任务**，同时发一段简短说明。不要把包提交到 Git 或公开贴到 Issue／PR。可按下面格式填写：

```text
已完成轮次：A（或 A、B、C、D）
未完成／受阻步骤：无（或 B4：通知中心找不到本轮旧通知）
与预期不同的现象：无（或具体描述）
ZIP SHA-256：粘贴 Get-FileHash 输出的 Hash
```

我收到后核对各轮 commit、版本、人工记录及快照，回报哪些已通过、哪些仍缺证据。不需要你手工计算事件数量或判断整体 I-01 PASS。原始文件至少保留至本任务和 [Draft PR #32](https://github.com/Annzival/ADHD-Support-System/pull/32) 审阅完成。

## 遇到错误或需要暂停

### 脚本报错

停在当前步骤，不重复运行后续命令。回传：轮次／步骤（例如 A1）、执行命令、报错末尾，以及应用是否已打开。省略用户名、无关本机路径等私人信息；不要贴令牌或完整环境变量。若 observations.json 已存在，将受阻项记 BLOCKED，实际行为错误记 FAIL，其余保持 NOT_RUN。

Collect 本身失败时不用强行打包；先发错误即可。若只是桌面某个观察失败，但仍能退出并 Collect，可回传失败摘要，不必所有项目 PASS 才能交付证据。

### 中途休息

可以从托盘“退出开发验收”，记录最后完成的步骤，保留本轮目录。尚在四小时测试窗口内、源码和二进制未变时，可用对应轮次的 Resume 继续；等待收尾时从托盘退出可保留状态，**点击窗口叉号会按跳过收尾处理**，两者不同。

已经超过本轮窗口，或期间更新了代码／二进制时，先回传停在哪一步，不再操作旧界面或手改数据库。未通过的部分需要怎样重做，由当前任务结合已有证据安排，不自动要求四轮从头再来。

## 场景对照与结论边界

| 轮次 | 主要场景 |
| --- | --- |
| A | EX-01，SES-02 完成前分支，DESK-04 有效通知 |
| B | SES-02 完成后分支，EX-01 显式跳过，DESK-04 旧通知 |
| C | EX-02，关闭收尾等同跳过，小窗关闭重开补充回归 |
| D | REC-03／04 本阶段适用部分，AT-02，DESK-03 重连整合 |

Run 中的自动测试另外检查本阶段原子性、并发、认证和重试；其通过不能替代上述人工桌面观察。只有自动检查与 Windows 证据核验均满足本阶段范围，才能报告 I-01 PASS；这也不等于完整 MVP 或正式 dogfooding 准入，不自动进入 I-02。
