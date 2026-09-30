# I-02 Windows 实机验收：逐轮操作手册

这份手册把启动后的按钮、等待时间、预期现象、快照和结束步骤逐项列出。一次只做一轮；**可以先完成 A 轮并回传，再继续其他轮次，不需要一次做完。** 同一轮恢复用原数据库，另一条互斥分支用新目录。

只有实际观察和核验过的项目才能报告通过。当前 Windows 生产验收尚未完成；旧 Windows 隔离 48/48、Linux 自动测试或交叉构建不能替代本手册。沿用 [Issue #33](https://github.com/Annzival/ADHD-Support-System/issues/33) / [Draft PR #35](https://github.com/Annzival/ADHD-Support-System/pull/35)，不进入 I-03／I-04 或正式 dogfooding。

## 0. 你已经启动过、随后从托盘退出：先保存这次记录

从托盘“退出开发验收”会结束宿主及其 Core；原测试目录和数据库仍保留。**不要在这个目录再次 Run，不要删除数据库，也不要把没有观察过的项填 PASS。**

如果还没更新代码，先在 Windows 仓库根目录的 PowerShell 记录当前版本，找到刚才输出的 `DataDirectory`：

```powershell
git rev-parse HEAD
Get-ChildItem -LiteralPath .i01-runs -Filter run.json -Recurse |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 5 @{Name='DataDirectory';Expression={$_.DirectoryName}},LastWriteTime
```

优先用刚才终端输出的目录；上面的列表只帮你定位，不自动认定“最新目录”就是本次。将下面占位文字换成这次实际路径：

```powershell
$runDirectory = '这里替换为刚才的 DataDirectory'
$record = Get-Content -LiteralPath (Join-Path $runDirectory 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$record | Select-Object stage,case,commit
notepad (Join-Path $runDirectory 'observations.json')
```

预期 stage 为 I02、case 为 ConfirmedDuration，commit 与本次启动的版本一致。只有这次确实完整看过的现象才填写 PASS；因步骤不清楚而尚未执行的项保持 NOT_RUN，不把这次退出算成测试失败。关闭记事本后，宿主已退出，可直接收集这次中断的证据：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Collect -DataDirectory $runDirectory
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory 'evidence-summary.json')
```

先保留这次 `evidence-summary.json` 及整个目录，再在两轮之间更新代码。新手册涉及文档 commit，脚本仍会核对 **完整 HEAD**；即使程序代码没变，更新手册后也不能直接把旧轮次当成新版本继续。

如果已经更新过代码而 Collect 提示版本不符，停在这里，回传本轮记录的 commit、当前 HEAD 和报错；不回退／覆盖工作树，不改 run.json 绕过核对。

也可以在原 commit、原二进制和有效期内 Resume 继续原轮次，但退出后无法补观察当时的首次通知，旧尝试不应重放。没有看过的首次呈现需要在新轮次验证。若只想按本手册从 A1 开始，先收集旧轮次，再用新目录启动 A。

## 1. 一次性准备

### 1.1 更新代码并核对环境

确认应用已经从托盘退出，在仓库根目录、同一个 PowerShell 窗口执行：

```powershell
git branch --show-current
git status --short
```

确认分支正确且 status 无输出后，再执行：

```powershell
git pull --ff-only
git status --short
git rev-parse HEAD
```

分支应为 `agent/implement-mvp-deterministic-recovery`，更新前后的 status 均无输出。若有不明修改、分支不对或 pull 失败，停在这里并回传，不清理或提交未知文件。**从一轮 Run 到该轮 Collect 期间不要 pull，也不要重建二进制。**

脚本检查下列锁定环境，无需新增安装或管理员权限：

| 项目 | 要求 |
| --- | --- |
| Windows | Windows 10 22H2 / Build 19045 x64 |
| Python | 3.12.3 x64 |
| Go | 1.25.0 windows/amd64 |
| Wails | go.mod 中的 v3.0.0-beta.8 |
| WebView2 | Fixed Version 151.0.4129.78 x64，目录直接含 msedgewebview2.exe |

沿用你已经使用的两个路径：

```powershell
$pythonPath = 'E:\Python\Python312\python.exe'
$webviewPath = 'E:\GPTProjects\ADHD-Support-System-onWin\spikes\wails-v3-windows-thin-host\.tools\webview2-fixed-151.0.4129.78-x64\Microsoft.WebView2.FixedVersionRuntime.151.0.4129.78.x64'
Test-Path -LiteralPath $pythonPath
Test-Path -LiteralPath (Join-Path $webviewPath 'msedgewebview2.exe')
```

后两条都应返回 True。换了 PowerShell 窗口后，需要重新设置这些变量。

### 1.2 记下本批次目录

只创建父目录，不提前创建各轮子目录；它们由 Run 创建。

```powershell
$batchDirectory = Join-Path (Get-Location).Path ('.i01-runs\I02-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $batchDirectory | Out-Null
$batchDirectory
```

记下最后输出。后面的命令会将 `$runDirectory` 设为本轮子目录，保证 Snapshot／Resume／Collect 指向同一轮。重新打开 PowerShell 时，回仓库根目录，恢复两个路径变量，并把 `$batchDirectory` 设回记下的父目录；不要重新创建已有轮次。

兼容现有工具的目录名仍是 `.i01-runs`，二进制仍叫 `desktop/bin/i01-desktop.exe`；run.json 和摘要的 stage 是 I02。这些名字不代表旧构建。

## 2. 每轮通用的记录和结束规则

| 命令／操作 | 做什么 |
| --- | --- |
| Run | 检查锁定环境，运行 Python／Go 自动测试，构建正式宿主，新建合成测试库并启动。每轮只执行一次 |
| Snapshot | 保存当前合成库状态；不提交执行结果。文件名 snapshot-时间戳.json，不覆盖旧快照 |
| RestartCore | 仅终止本轮 Python Core，由仍运行的宿主尝试重启；不是 PC 重启 |
| Resume | 用原数据库及原二进制重新打开；应用仍运行时可验证单实例 |
| Collect | 托盘退出后保存最终状态并生成 evidence-summary.json；不自动宣布 PASS |
| 窗口右上角叉号 | 隐藏该窗口，进程仍在；等待收尾时会先按“跳过收尾”保存 |
| 托盘“退出开发验收” | 真正退出应用；与窗口叉号不同，等待收尾可以保留到再次打开 |

每轮启动后打开步骤记录，写明轮次和参数分支；每份快照后补一行“步骤编号、观察、对应快照文件名”。不需要手工编辑／比较数据库 JSON，回传后由实现任务核对 ID、引用、状态及计时依据。

```powershell
notepad (Join-Path $runDirectory 'steps.txt')
```

上面命令在本轮 Run 完成、`$runDirectory` 已设置后使用。若记事本问是否新建，选新建。steps.txt 只记合成操作，不写私人资料；Collect 不自动包含它，所以回传时另附该文件。

人工观察记录在 `observations.json`：

| 值 | 用法 |
| --- | --- |
| PASS | 自己实际观察到该字段的完整要求；库内断言仍由回传证据核验 |
| FAIL | 执行过，但现象与预期不同 |
| BLOCKED | 被前置错误挡住，无法执行 |
| NOT_RUN | 尚未执行或本轮不负责，保留原值 |

只替换值，不删除字段，不整份批量改 PASS。每个互斥变体都要保留自己的目录和摘要；某一轮 PASS 不代表该字段的其他分支也已验证。

## 3. 先看各轮终点

| 轮次 | 本轮操作 | 正常结束点 |
| --- | --- | --- |
| A | 首次通知、关闭重开窗口、开始、续行、部分完成、收尾草稿重连、更正 | 已保存部分完成和更正；收集后即可先回传 |
| B | 缺估时取消、已经开始、暂停／原生关闭、从包继续 | 两次暂停证据与新旧包引用保留 |
| C1 / C2 | 回顾式完成后确认部分完成／显式跳过 | 两个独立目录；无检查点 |
| D1 / D2 | 改期／今天不做 | 两个独立目录；点击旧通知只显示现状 |
| E | 无回应的弱跟进、小窗关闭重开、真正退出再恢复 | 无第三次开始提醒，不重放旧尝试 |
| F1 / F2 / F3 | 三分钟期限：无回应／未知跟踪结束／暂停自动收束 | 各自结束但不推断用户结果 |
| G1 / G2 | 两项到点：无会话／A 已开始 | 单一前台，无第二活动会话 |
| G3 / G4 | 旧包与当前计划：继续 P／归档再开始 Q | 两个独立目录，引用各自方案版本 |
| H | 单实例、登录启动、真实 PC 重启、取消／确认切换、Core 守护 | 同库恢复；只有 B 活动；关闭启动项并收集 |

A～H 是分组；带数字的分支需各开新目录。每轮通常只需几分钟，H 需要正常重启电脑。四小时是夹具有效窗口，不要求连续操作四小时。没有个人方案、LLM 或桌面活动采集。

## 4. A 轮：先完成这一轮即可回传

### A1. 启动

先读 A2～A4，知道要看什么后再执行：

```powershell
$runDirectory = Join-Path $batchDirectory 'A'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

Run 自动检查和构建完成后打开主窗口，并输出 DataDirectory；确认与 `$runDirectory` 相同。合成开始时间从建库后起算，约 90 秒后到点，不含先前构建时间。首个检查点为开始后 60 秒，跟进宽限为夹具的 30 秒。若窗口未出现或脚本报错，停在 A1。

### A2. 看首次通知，返回正确行动

1. 等到约定时间，不提前操作。
2. 观察置顶“当前行动”小窗及 Windows 系统通知。通知在其他普通窗口前仍可见；不要把网页文本当成系统通知。
3. 点击通知中的“查看当前行动”。横幅消失可按 Win+A，从通知中心找到这轮应用通知。
4. 主窗口应打开／获得焦点，显示“开发验收：在空白文档写下一行测试文字”，并提示从系统通知返回对应行动。
5. 不先点击“立即开始”，保存下方快照，便于核对原生 API 报告和首次机会。

没看到真实通知时如实记 FAIL／BLOCKED，不能因为按钮可用而填通知成功。此操作也不证明用户读过通知。

现在保存快照，并在本轮 `steps.txt` 记下“A2：首次送达，尚未回应”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### A3. 关闭主窗口再重开：不是退出应用

1. 点主窗口右上角叉号；主窗口隐藏，托盘图标仍在（可能在右下角 `^` 隐藏图标中）。
2. 托盘选择“显示主窗口”。应回到同一行动，没有因窗口关闭新增一次首次通知。
3. 保存快照。日志／快照中的同次报告去重由回传核验，不要求自己查 PID。

如果已经出现夹具允许的那一次 30 秒弱跟进，单独记录它；它不等于窗口重开发送了一次新首次通知。

现在保存快照，并在本轮 `steps.txt` 记下“A3：主窗关闭后重开，宿主未退出”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### A4. 立即开始，等检查点，再继续

1. 点击“立即开始”。已有确认时长，不应再要求填写时长。
2. 应显示“执行会话已建立。检查时间：…”和两个操作“已经完成”“暂停并保存恢复包”。记下显示的检查时间。
3. 等约 60 秒，直到出现“约定的检查时间已到。可完成、继续或暂停。”。系统不应自动宣布完成。
4. 点击“继续并确认下一检查时间”，在“本次预计时长（分钟）”填 1。
5. 点击“确认时长并开始”。应继续当前会话，并显示新的检查时间；不是开启第二个会话。

现在保存快照，并在本轮 `steps.txt` 记下“A4：确认续行后，旧检查点与后继待核验”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### A5. 部分完成草稿经过一次 Core 重连

1. 点击“已经完成”，应显示等待收尾。只报告完成尚未释放活动会话。
2. 在结果选择框选“部分完成”，“实际用时（分钟，可留空）”填 12。
3. **暂不点“完成收尾”，也不点窗口叉号。** 在当前窗口保留草稿，回 PowerShell 保存快照：

现在保存快照，并在本轮 `steps.txt` 记下“A5：等待收尾，草稿部分完成／12 分钟未提交”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode RestartCore -DataDirectory $runDirectory
```

4. 返回应用，等待恢复连接。短暂“正在重新连接”可能很快消失；最终应恢复“已连接智能体核心”。
5. 在同一个窗口核对：仍是等待收尾，部分完成和 12 分钟草稿保留。若草稿不见或重连失败，停在 A5 并记录，不重新填写后声称草稿通过。
6. 点击“完成收尾”。应显示“已保存执行证据，会话已结束”和“已确认部分完成，行动没有被标为全部完成”。12 分钟换算 720 秒以及仅一份证据由快照核验。

现在保存快照，并在本轮 `steps.txt` 记下“A5：重连后确认部分完成”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### A6. 追加事实更正

1. 从托盘“显示主窗口”，在已保存证据下点击“追加事实更正”。
2. 更正结果选“部分完成”；内容填“测试更正：补充一条合成说明”，原因填“核验追加更正，不覆盖原事实”。
3. 点击“保存更正”。主窗口应显示新增更正文字，原部分完成提示保留。

现在保存快照，并在本轮 `steps.txt` 记下“A6：更正保存，原始事实仍保留”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `arrivalAndCorrectNotification`
- `g01WindowClose`
- `startAndFirstCheckpoint`
- `continueCheckpoint`
- `completionAfterCheckpoint`
- `awaitingClosureSurvivesRestart`
- `finishClosure`
- `factCorrection`

A2～A4 的送达、机会、进入及 QPC 指标由同库快照核验；`g01NormalDelivery` 不要求自己比较 JSON。回传后再确认它，先保留 NOT_RUN 并在 steps.txt 写“指标待核对”。A5 重启是等待收尾草稿验证，不把它填写为执行中守护已通过。

**A 轮完成并 Collect 后可以到此停止，先发摘要和步骤记录。**

## 5. B 轮：缺估时、已经开始、暂停包接续

### B1. 启动

```powershell
$runDirectory = Join-Path $batchDirectory 'B'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MissingDuration -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

到点后从小窗或主窗口进入。同一轮只能有一个活动会话。

### B2. 打开／取消两类时长确认

1. 在尚未开始时保存快照。
2. 点击“立即开始”，应出现时长确认表单；点击“取消”，应仍可开始，不显示会话。
3. 点击“我已经开始”，也应要求确认从现在起多久后检查；点击“取消”，仍没有会话。
4. 保存快照；两次取消的无半更新由回传核验。

现在保存快照，并在本轮 `steps.txt` 记下“B2：两次取消，不应建立会话”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

步骤 1 的快照也用同一 Snapshot 命令，按先后在 steps.txt 标明“B2 取消前／后”。

### B3. 明确已经开始，暂停并用原生关闭收尾

1. 再点“我已经开始”，填剩余 1 分钟，点“确认时长并开始”。应建立会话，现实开始时间仍保持未知；应用不能回推你实际何时开始。
2. 点击“暂停并保存恢复包”，应进入等待收尾。
3. 不填写进展或用时，点**当前窗口右上角叉号**，不是托盘退出。
4. 从托盘“显示主窗口”重开。应已结束并显示“已暂停并保存恢复包”。如果仍等待收尾，记录 FAIL，不要补点“跳过收尾”掩盖原生关闭问题。

现在保存快照，并在本轮 `steps.txt` 记下“B3：原生关闭保存最小暂停证据／包”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### B4. 重新打开原库，才进入恢复包选择

从托盘“退出开发验收”，保持本轮目录，执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Resume -DataDirectory $runDirectory
```

1. 从托盘“显示主窗口”，找到“恢复上下文”；展开“上次执行”和“当前计划”。
2. 应看到“上次暂停…”及进展未知，点击“从此暂停包继续”。
3. 填剩余 1 分钟，点“确认时长并开始”。应建立接续会话，新会话引用旧包，旧包只使用一次；不是复活原会话。
4. 再点“暂停并保存恢复包”。在等待收尾的“已取得的进展”填“测试：已写一行”，点击“完成收尾”。应保存第二次暂停及新包，原记录仍在。

现在保存快照，并在本轮 `steps.txt` 记下“B4：从包接续，再次暂停”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `cancelDurationLeavesPending`
- `alreadyStarted`
- `startAndFirstCheckpoint`
- `pausePacket`
- `resumePacket`
- `nativeCloseSkipsClosure`

## 6. C／D／E：互斥分支分开做

### C1. 回顾式完成，确认部分完成

```powershell
$runDirectory = Join-Path $batchDirectory 'C1'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点后点击“我已经完成”，直接进入等待收尾，不先点击“立即开始”。
2. 应没有执行中检查时间；现实开始／结束保持未知。
3. 选择部分完成，用时留空，点击“完成收尾”。应显示部分完成，行动未被标为全部完成。

现在保存快照，并在本轮 `steps.txt` 记下“C1：回顾式部分完成”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `retrospectiveComplete`
- `finishClosure`

### C2. 回顾式完成，显式跳过收尾

```powershell
$runDirectory = Join-Path $batchDirectory 'C2'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点后点击“我已经完成”，直接等待收尾。
2. 不填用时，点击“跳过收尾”。应显示会话已结束；原明确完成报告保存，未填内容保持未知。
3. 不把“跳过收尾”说成没有执行；没有检查点且不计通知促成开始，由快照核验。

现在保存快照，并在本轮 `steps.txt` 记下“C2：回顾完成后显式跳过”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `retrospectiveComplete`
- `skipClosure`

### D1. 改期并点击旧通知

```powershell
$runDirectory = Join-Path $batchDirectory 'D1'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

本夹具包含 P 中行动 A“写下一行测试文字”和 Q 中行动 B“开发验收：第二个测试行动”，B 比 A 晚 90 秒；合成当前版本为 Q，不是方案导入功能。

1. A 到点后保留系统通知，不清空通知中心。从托盘打开主窗口。
2. 在 A 下点“改到具体时间”，打开表单后先点“取消”；保存快照，A 仍可操作。
3. 再打开改期表单，填本机今天一个明确的未来开始时间（建议现在后 10 分钟；若跨日期请一并选择日期），窗口结束可留空。
4. 点“确认改期”。原 A 开始入口应消失，不创建会话；新安排不覆盖原时间，也不改其他安排。
5. 从 Win+A 点击**本轮 A 的旧通知**。应提示原通知上下文失效，并读取当前状态；不能重新执行原 A。
6. 等 B 原约定时间到达，B 应按原时间出现。不要为了 A 改期再顺延 B。

现在保存快照，并在本轮 `steps.txt` 记下“D1：A 改期／旧通知失效／B 原时刻”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `reschedule`
- `staleNotificationShowsCurrentContext`

步骤 2 的取消前后也分别 Snapshot，快照内后继行动引用由回传核验。若通知中心已没有旧通知，该点击支保持 NOT_RUN／BLOCKED，不能用普通打开主窗替代。

### D2. 今天不做，不生成明天安排

```powershell
$runDirectory = Join-Path $batchDirectory 'D2'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. A 到点后从主窗口，在 A 下点击“今天不做”（此按钮直接提交，不另弹确认）。
2. A 开始入口消失；没有会话，没有完成／失败提示。
3. 等 B 按原约定出现；不要求启动 B。快照核验只记录本次不执行，不自动创建明天后继。

现在保存快照，并在本轮 `steps.txt` 记下“D2：本次不执行，B 仍独立”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `skipToday`

### E. 弱跟进、小窗重开和宿主真正重启

```powershell
$runDirectory = Join-Path $batchDirectory 'E'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点记录首次小窗和真实通知，**不点击执行按钮，也不点击通知**。
2. 点小窗叉号关闭，保持应用和托盘运行。
3. 从首次成功送达约 30 秒后，最多出现一次较弱跟进；不应因跟进重新弹出或聚焦小窗。
4. 再等至少 60 秒，不应出现第三次开始提醒。记录实际等待起止时间；30 秒是合成夹具，不是产品默认建议。
5. 托盘“显示当前行动”，应能手动打开小窗；叉号关闭／托盘重开三次，仍为同一行动且置顶。
6. 保存退出前快照。

现在保存快照，并在本轮 `steps.txt` 记下“E：首次及一次弱跟进后，无第三次开始提醒”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

7. 从托盘“退出开发验收”，再用原库 Resume：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Resume -DataDirectory $runDirectory
```

8. 应恢复当前权威状态，不重发旧开始尝试。恢复上下文可能按规则首次呈现，需记下通知文字并与旧开始提醒区分；不能将“允许的恢复通知”误认成旧提醒重放。
9. 保存恢复后快照。本步骤不能用人工观察猜测是否命中了未提交迟到竞争；那部分由生产自动控制点验证。

现在保存快照，并在本轮 `steps.txt` 记下“E：宿主真正退出／重开，同库且旧尝试不重放”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `weakFollowup`
- `overlayCloseAndReopen`
- `g01HostRestartNoReplay`

## 7. F 组：三分钟期限的三个独立目录

每轮 ShortWindow 的窗口从约定开始起算 180 秒；不是脚本启动后 180 秒。首次检查为开始后 60 秒。到期看不到显式解释时也保存实际界面和快照，不自行推断执行结果。

### F1. 完全不回应

```powershell
$runDirectory = Join-Path $batchDirectory 'F1'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ShortWindow -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点后不点开始／完成／暂停，也不回应跟进。
2. 等到约定开始时间后至少 180 秒，再留几秒供页面刷新。
3. 原开始入口应消失，没有完成／失败／暂停执行证据。系统只知道期限已过，结果未知。

现在保存快照，并在本轮 `steps.txt` 记下“F1：无回应，窗口到期”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节托盘退出和 Collect。

F1 没有专用观察字段，不借用 unknownTrackingEnd（它要求曾开始会话）。在 steps.txt 记录 F1 现象，所有不负责的字段仍 NOT_RUN。

### F2. 开始后不回应检查点

```powershell
$runDirectory = Join-Path $batchDirectory 'F2'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ShortWindow -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点立即开始，确认会话和检查时间，保存执行中快照。
2. 检查点到达后不点击任何操作；最多一次较弱跟进，不自动创建后继检查点。
3. 等窗口到期。应释放活动会话，不宣称完成／暂停／失败，也不生成恢复包。未知跟踪结束的退出原因由快照核验。

现在保存快照，并在本轮 `steps.txt` 记下“F2：检查点无回应，期限结束跟踪”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `unknownTrackingEnd`

### F3. 明确暂停，但不处理收尾

```powershell
$runDirectory = Join-Path $batchDirectory 'F3'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ShortWindow -StartDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 到点立即开始，随后点击“暂停并保存恢复包”，进入等待收尾。
2. 不填写、不点完成／跳过、不点窗口叉号、不从托盘退出，保持应用运行到窗口结束。
3. 到期应自动结束收尾，只依据原暂停报告保存最小证据和一个恢复包，未填进展／用时未知。

现在保存快照，并在本轮 `steps.txt` 记下“F3：暂停报告后期限自动收束”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `automaticClosure`
- `pausePacket`

本地次日零点、无窗口截止计算、安静时段、离线跟进、逐写失败／竞争由可控时钟自动测试覆盖；不改 OS 时间，不让操作者等到半夜。可选 `-Case WithoutWindow` 仅用于查看无窗口的已确认估时入口，不冒充正式设置。

## 8. G 组：单一前台与旧版本选择

### G1. A 未回应时 B 到点

```powershell
$runDirectory = Join-Path $batchDirectory 'G1'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. A 到点时不回应，主窗口保留 A 的未决入口。
2. 再等约 90 秒，B 到点。小窗应优先显示 B；主窗口仍可看到 A 与 B 的未决记录，不同时争抢两个小窗。
3. 不创建会话，保存快照和所见标题。

现在保存快照，并在本轮 `steps.txt` 记下“G1：A 未回应，B 成为前台”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `singleForeground`

### G2. A 已开始时 B 到点

```powershell
$runDirectory = Join-Path $batchDirectory 'G2'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -DurationSeconds 600 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. A 到点立即开始，检查时间约 10 分钟后，留足时间观察 B。
2. B 到点后小窗仍优先显示 A 会话；主窗可查看 B，但不能偷偷创建第二活动会话。
3. 在主窗口 B 下点击“立即开始”，应提示“已有执行会话或等待收尾，请先处理当前会话”；A 仍在，原检查时间不变。不要先结束 A 再执行这一检查。

现在保存快照，并在本轮 `steps.txt` 记下“G2：活动 A 与 B 到点，第二会话被拒绝”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `singleForeground`

G1、G2 的 PASS 分开保留。G2 退出时不必伪造完成；原库保持活动会话即可。

### G3. 暂不决定后，选择继续旧 P 的暂停包

```powershell
$runDirectory = Join-Path $batchDirectory 'G3'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -DurationSeconds 600 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. A 到点立即开始，点击“暂停并保存恢复包”，进展填“测试：P 已写一行”，点击“完成收尾”。
2. 等到 B 的约定开始时间后，从托盘退出，再 Resume 原库：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Resume -DataDirectory $runDirectory
```

3. 主窗找到“恢复上下文”，分别展开“上次执行”“当前计划”；应能分开查看 P 的上次行动与当前 Q 的 B。
4. 点击“暂不决定”，保存快照。此项是实际持久选择，不是关窗口。
5. 从托盘退出，再次 Resume 同库。同一上下文不得再次主动呈现；主窗仍可被动找到“稍后处理上次上下文”。
6. 点击“从此暂停包继续”，填剩余 1 分钟并确认。应新建引用旧 P 的接续会话，原包只使用一次；当前 Q 不被自动改写。

现在保存快照，并在本轮 `steps.txt` 记下“G3：暂不决定经重启保留，再明确接续 P”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `oldVersionChoice`
- `deferRecovery`
- `resumePacket`
- `recoveryCarrier`

步骤 4 和步骤 5 后也各 Snapshot，按编号在 steps.txt 区分。若重启期间上下文确实变化（例如跨期限），记录变化，不把新上下文误算为旧上下文重复呈现。

### G4. 归档旧包，再明确开始当前 Q

```powershell
$runDirectory = Join-Path $batchDirectory 'G4'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -DurationSeconds 600 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. 重复 G3 的步骤 1～2：暂停 A 完成收尾，等 B 到点，退出后 Resume。
2. 主窗展开上次执行和当前计划，点击“按当前计划继续，归档此包”。
3. 此按钮只归档包，不应自动建立 B 会话；先保存快照。
4. 在 B 下点击“立即开始”。应明确建立引用 Q 的会话，旧 P 证据／包仍保留，不覆盖旧事实。

现在保存快照，并在本轮 `steps.txt` 记下“G4：归档 P 包后，明确开始 Q”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `oldVersionChoice`
- `recoveryCarrier`

## 9. H 轮：单实例、登录启动、真实 PC 重启和原子切换

本轮用 10 分钟首次检查，四小时窗口；只有本轮需要真正重启电脑。先保存其他应用工作，确认能够正常重启及重新登录。每个控制点失败就停，不连续重试消耗守护额度。

### H1. 启动 A、验证单实例及窗口

```powershell
$runDirectory = Join-Path $batchDirectory 'H'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -StartDelay 90 -DurationSeconds 600 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

1. A 到点后立即开始，记下检查时间，保存执行中快照。
2. 应用仍运行时执行 Resume（同目录），应只激活原主窗口，不打开第二套宿主／Core：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Resume -DataDirectory $runDirectory
```

3. 从托盘分别显示主窗口／当前行动；执行中的窗口叉号只隐藏，重开三次会话和检查时间保持，小窗仍置顶。
4. 这里没有等待收尾，不应因关窗保存完成／暂停证据。进程计数和同一会话由下方重启记录核验。

### H2. 启用登录启动，保存重启前证据

1. 托盘选“启用本用户登录时启动”。
2. 打开主窗，应显示“已启用本用户登录时启动。”。不需要管理员权限，也不改变领域状态。
3. 等到 B 到点（比 A 晚 90 秒）再保存，保证重启后当前计划有 B 可选。
4. 执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode BeforeReboot -DataDirectory $runDirectory
```

脚本应保存 before-reboot.json 和状态快照，要求宿主／本轮 Core 各一个。失败则停止，不继续 PC 重启。

### H3. 真正重启电脑，恢复变量和同库

1. 自己从 Windows 开始菜单正常重启 PC，保存其他应用工作。不要只注销或重启 Core。
2. 重新登录后，等待本应用按启动项自动出现；**不要再次 Run 或主动 Resume 来代替登录启动**。没有启动就记录 BLOCKED／FAIL。
3. 在仓库根目录重新打开 PowerShell。变量已丢失，恢复第 1.1 节两个路径，并执行：

```powershell
$batchDirectory = '这里替换为重启前记下的批次父目录'
$runDirectory = Join-Path $batchDirectory 'H'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode AfterReboot -DataDirectory $runDirectory
```

4. 应核对实际系统启动时间改变、宿主／Core 各一个、同一 database_id；保存 after-reboot.json 和状态快照。
5. 主窗仍基于原库，活动会话及原检查时间保留，不重新发送旧尝试。原检查点已到达时保留 due 也可以；跨过领域期限则按期限结束，不要求过期会话仍执行中。
6. 主窗口“上次执行”“当前计划”应可分别展开；若没有可切换的活动 A 与当前 B，停在 H3 说明实际状态，不清库重建来冒充恢复。

### H4. 先取消，再确认切换到 B

1. 点击“切换到当前计划（旧结果保持未知）”。
2. 在时长确认表单点“取消”；A 应仍活动且检查时间不变。保存快照。
3. 再打开切换表单，填 10 分钟，点“确认时长并开始”。
4. 应只有 B 执行中，A 结果未知，没有为 A 虚构完成／暂停／收尾或包。A 的 exit_reason=user_selected_switch 及原子状态由同库快照核验。

现在保存快照，并在本轮 `steps.txt` 记下“H4：取消保持 A；确认后仅 B 活动”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

步骤 2 和步骤 4 后各存一份 Snapshot。没有明确点击确认不得自动切换。

### H5. 执行中重启一次 Core

先记下 B 显示的检查时间，再执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode RestartCore -DataDirectory $runDirectory
```

等待恢复“已连接智能体核心”，B 与原检查时间不变；旧 A 的通知／检查点不能重新变成操作入口。若还有 A 旧通知，从通知中心点击并记录失效提示；已消失则该点击支 NOT_RUN。

现在保存快照，并在本轮 `steps.txt` 记下“H5：一次 Core 守护后仍是同一 B”（记录规则见第 2 节）：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

### H6. 关闭启动项，结束本轮

1. 托盘选择“关闭本用户登录时启动”，主窗确认“已关闭登录时启动。”。
2. 按第 11 节填写、托盘退出、Collect。不能带着测试库启动项直接丢弃目录。

本轮负责：

本轮做完后，按第 11 节填写观察、托盘退出和 Collect。本轮负责以下字段；只有亲眼完成整项要求才填 PASS，数据库内部细节由回传快照核验：

- `singleInstance`
- `overlayCloseAndReopen`
- `autostart`
- `pcRestart`
- `recoveryCarrier`
- `recoverySwitch`
- `processSupervisor`
- `coreRestartKeepsSameSessionAndCheckpoint`

启动项只使用当前用户 Run 键 ADHDSupportI02，记录完整本轮启动参数。若宿主无法打开，可只清除此应用值：

```powershell
Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'ADHDSupportI02' -ErrorAction SilentlyContinue
```

不要删除整个 Run 键或其他应用项。记录是否使用了备用清理。

## 10. 守护上限与 G-01 自动证据的边界

### 10.1 守护上限：另开 J 轮，不污染 H

如需完整核验上限，另开本轮；H5 一次重启通过不等于上限通过。

```powershell
$runDirectory = Join-Path $batchDirectory 'J'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -StartDelay 90 -DurationSeconds 600 -PythonExecutable $pythonPath -WebView2Path $webviewPath -DataDirectory $runDirectory
```

到点开始后，逐次执行 RestartCore。前 3 次每次都等重连后再做下一次，保存一次 Snapshot／步骤记录；预期退避 1／2／4 秒，时间只是配置，不要求手工秒表证明精确时长。第 4 次受控退出后应停止自动守护，UI 明确不可用，不能显示保存成功。日志应留 core_connected／core_disconnected／core_restart_limit_reached。

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode RestartCore -DataDirectory $runDirectory
```

上面命令一次只执行一次，不写循环批量终止，不终止所有 Python。每次成功重连才继续。到达预期第 4 次停止后从托盘退出、Collect；UI 不可用属于这一支预期，不是要求无休止重连。processSupervisor 上限证据在 J 的 steps.txt 与日志注明；本轮没有真实 PC 重启，不填 pcRestart。

### 10.2 G-01 及时间指标由哪些证据核对

Run 已运行当前生产 Core／HTTP／Go pump 的自动层；保留 automatic-tests.txt，不额外要求重跑旧隔离矩阵。错关联、未提交重启、同命令已存返回、检查后退出、回滚不继承资格、故障与竞争通过自动控制点证明，人工不用快速点按钮“碰”某个顺序。

- A2 快照核对同次原生 API 报告；delivered=true 只代表 API 返回成功，不证明显示／阅读。api_return_at 和 received_at 保留各自含义。
- A2～A4 核对正常机会／明确进入，耗时用共同 QPC；time_basis=windows_qpc_v1，有缺失／失效／跨 Core 运行期或精度边界不确定时为 null／unknown，其他事实保留。不按墙钟差或自己感觉的秒数核对，不改 OS 时间。缺 QPC 依据原因由回传审查。
- A3 验证窗口关闭未退出；E 验证真正退出、同库恢复且旧尝试不重放；不把这两支混成一次“重启”。
- 生产库字段／引用、正常机会、迟到未知、去重及原子性由快照与当前源码核验；系统通知、焦点、置顶和实际重启需要操作者观察。自动设备替身不能代替实机。

## 11. 每轮填写观察、退出、收集、回传

### 11.1 填写本轮记录

```powershell
notepad (Join-Path $runDirectory 'observations.json')
notepad (Join-Path $runDirectory 'steps.txt')
```

只按该轮“负责字段”和实际所见修改 PASS／FAIL／BLOCKED。数据库内部待核对的项目在 steps.txt 标“待核对”，观察字段先保留 NOT_RUN，回传后再确认，不要求你替技术执行者验证 JSON。未执行的其他轮次保持 NOT_RUN。

steps.txt 至少写：轮次／分支、步骤编号、点击或等待、所见文字、对应快照文件名、最后完成步骤、失败／未做项。记录合成内容即可。例：`A3 主窗叉号隐藏后托盘重开，同一行动；出现一次弱跟进，未出现新首次；snapshot-….json`。

### 11.2 托盘退出，Collect

在 Windows 右下角（含 ^ 隐藏区）找到本应用，托盘菜单选择“退出开发验收”。主窗口叉号不是退出，Collect 若说宿主仍在则先确认托盘。然后执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Collect -DataDirectory $runDirectory
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory 'evidence-summary.json')
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory 'steps.txt')
```

Collect 生成本轮 evidence-summary.json，记录 commit、环境、二进制哈希、database_id、状态、观察及输出文件哈希；它不会自动宣布 I-02 PASS。允许失败／部分完成时收集，不要求所有项 PASS 才回传。

### 11.3 回传哪些文件

先回传 A 一轮即可：

1. 轮次、源码 commit，以及完成到哪个步骤／哪些未做。
2. 本轮 evidence-summary.json 与其 SHA-256。
3. steps.txt 与其 SHA-256。
4. 本轮 snapshot-*.json；H 另附 before/after-reboot*.json。
5. 如有错误，自动日志末尾或脱敏 desktop-evidence.jsonl 的对应事件；保留原文件与哈希。

原 run.json 含本机路径，bootstrap 可能含令牌，SQLite 及完整原始日志继续本机受控保留，不直接公开。只回传合成且已脱敏的材料；不附个人方案、屏幕私人内容或令牌。原始数据不提交 Git。快照可能较多，可以先发摘要与 steps.txt，需要的对应快照再按步骤提供。

## 12. 报错、暂停和结论边界

脚本报错停在该步骤，回传轮次／步骤、执行命令、错误末尾、应用是否打开。不要反复 Run，手改数据库、run.json 或清空目录来通过。前置阻塞不继续依赖操作；Collect 本身失败也可以只回报错误。

中途可以从托盘退出，记下最后步骤并保留目录。同一 HEAD、原二进制和有效期内可 Resume；关闭 PowerShell 后先恢复变量。已更新代码或超出期限时，不继续旧操作，先回传本轮身份和状态，已有成功证据不抹掉。窗口叉号会在等待收尾时执行跳过，托盘退出能保留等待收尾，暂停前确认用哪一种。

本手册只补操作说明，不修改产品规则、生产代码、测试断言或锁定依赖。本轮用户反馈仅确认曾启动并退出，尚不能据此标记通知或窗口 PASS。P2 审核通过是用户回传，Windows 生产测试仍等待实际证据；历史两轮 FAIL、研究及隔离 PASS 保留原结论。旧浏览器 ECONNRESET 原因仍未知，Windows 成功也不证明该原因消失。

## 场景对照

| 轮次 | 主要场景 |
| --- | --- |
| A | EX-01，SES-01/02/03/07，DESK-03/04，G01 正常／窗口关闭与 OBS-01 时间依据 |
| B | EX-02/03，SES-04，REC-05 |
| C1/C2 | EX-04，SES-03 |
| D1/D2 | EX-05/06，DESK-04 |
| E | EX-07/08，DESK-01，G01 真正退出／重开 |
| F1/F2/F3 | EX-09，SES-05/06，REC-02/03/04 |
| G1/G2 | EX-10，DESK-05 |
| G3/G4 | REC-06/07/08/09，DESK-05 |
| H | REC-10/11/12，DESK-02/03/05 |
| J | Python 守护上限与不可用状态 |

[37 项及生产路径映射](results/i02-production-coverage.md)与[生产结果及限制](results/i02-g01-production-integration.md)继续有效。只有必要自动检查、Windows 证据及独立审查均满足，才可报告完整 I-02 PASS；PR 保持 Draft，不自行 Ready／merge／关闭 Issue。
