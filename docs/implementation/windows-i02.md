# I-02 Windows 操作与证据手册

本手册对应 Issue #33 / Draft PR #35 的确定性实现。**G-01 迟到回执接纳仍未启用；不能据其他场景通过宣称 I-02 PASS。** 当前 Linux 检查不证明原生通知、焦点、置顶、托盘、登录启动或 PC 重启已通过。只有实际做过的操作才填写 PASS；不需要为旧 I-01 证据改写结论。

## 环境与一次运行

沿用 Windows 10 22H2 / 19045 x64、Python 3.12.3 x64、Go 1.25.0、Wails beta.8、Fixed WebView2 151.0.4129.78 x64。脚本继续执行版本、位数、干净源码、二进制哈希检查。没有安装／升级步骤，也无需管理员权限。每一轮使用新目录，同一轮恢复必须使用原目录，不能重新 seed。

在本分支最终干净 checkpoint 的仓库根目录打开 Windows PowerShell。下例两个路径换成操作者原有锁定安装路径：

```powershell
$pythonPath = 'D:\Tools\Python312\python.exe'
$webviewPath = 'D:\Tools\WebView2Fixed151'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ConfirmedDuration -PythonExecutable $pythonPath -WebView2Path $webviewPath
```

Run 先运行 Python 和 Go 自动测试，构建正式 Windows 宿主，再创建显式合成夹具并启动。记下输出 `DataDirectory`；后续将它赋给 `$runDirectory`。这些都是测试行动，不是正式导入设置。为兼容现有工具，目录仍在 `.i01-runs/`，二进制名仍为 `i01-desktop.exe`；`run.json` 与摘要的 stage 为 I02，名称不代表沿用旧构建证据。

每个关键操作前后保存快照：

```powershell
$runDirectory = 'D:\你的仓库\.i01-runs\本轮目录'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Snapshot -DataDirectory $runDirectory
```

快照来自同一 SQLite 数据库，只含合成资料；记录人工观察的按钮、窗口、通知表现与操作顺序。脚本不能自动证明用户看到或窗口获得焦点。

## 分轮操作

每轮结束从托盘退出，按文末 Collect。下一轮用 Run 新目录。原始失败也保留，不在旧目录重建。

| 轮次／夹具 | 操作顺序与预期 | 对应场景／观察字段 |
| --- | --- | --- |
| A / ConfirmedDuration | 到点出现真实通知和小窗；点击通知回到对应行动。立即开始→检查点到达→继续并确认 1 分钟；会话 ID 不变、旧检查点保留且有后继。完成→收尾选部分完成→输入 12 分钟；重启 Core 后草稿仍在，确认后只一份 partial／720 秒证据。追加更正，原证据保留 | EX-01、SES-01/02/03/07、DESK-03/04；arrivalAndCorrectNotification、continueCheckpoint、factCorrection 等 |
| B / MissingDuration | 打开立即开始→取消，两次快照无会话。选择我已经开始→取消→再确认剩余 1 分钟；会话来源为 already_started，实际开始未知。分别在主窗或小窗暂停→关闭收尾；保存 paused 证据和一个包，活动位置释放。主窗从包继续→确认剩余时长，新会话引用原包；再次暂停生成新包 | EX-02/03、SES-04、REC-05；cancelDurationLeavesPending、alreadyStarted、pausePacket、resumePacket、nativeCloseSkipsClosure |
| C / ConfirmedDuration | “我已经完成”直接等待收尾、没有检查点。确认部分完成或显式跳过；用另一次新 Run 验证另一支。未填时长保持未知，不能作为通知促成开始 | EX-04、SES-03；retrospectiveComplete、finishClosure、skipClosure |
| D / MultiplePlans | 先改期 A 到明确的未来时间，保存前可取消；确认后旧时间不改写且后继引用同一行动。点击旧通知只显示现状，不能重新操作旧安排。B 到点仍保留原约定时间。另一轮选今天不做 A，确认不创建会话或明天安排 | EX-05/06、DESK-04；reschedule、skipToday、staleNotificationShowsCurrentContext |
| E / ConfirmedDuration | 首次送达后不回应，30 秒测试宽限后最多一次较弱跟进（不重新显示／聚焦小窗）；再等待不出现第三次。关闭小窗后只从托盘手动恢复。此值是夹具参数，不是产品默认建议 | EX-07/08、DESK-01；weakFollowup、overlayCloseAndReopen。迟到回执部分仍为 G-01 待决 |
| F / ShortWindow | 3 分钟窗口：一轮完全不回应，到期原入口消失、无结果证据；一轮开始后不回应检查点，到窗口结束只结束跟踪；一轮开始→暂停但不收尾，到窗口结束只依据暂停报告自动保存最小证据与包。三轮分别新建目录 | EX-09、SES-05/06、REC-02/03/04；automaticClosure、unknownTrackingEnd |
| G / MultiplePlans | A 未回应时 B 到点：主窗保留 A，置顶只显示 B；另轮 A 已开始时 B 到点：小窗仍为 A，不得建第二会话。暂停 A 后，主窗对照旧版本 P 与当前 Q：分别测试继续旧包仍引用 P，或按当前计划归档旧包再明确开始 B。暂不决定后重启不得重新主动呈现同一上下文 | EX-10、REC-06/07/08/09、DESK-05；singleForeground、oldVersionChoice、deferRecovery、recoveryCarrier |
| H / MultiplePlans，600 秒时长 | A 开始后先做下方真实 PC 重启，再在恢复主窗口独立展开上次执行与当前计划；取消切换不改变 A；确认切换和 B 检查时间后，仅 B 活动，A exit_reason=user_selected_switch，A 无收尾／结果证据／包。重启 Core 后同一 B，旧 A 通知／检查点不能操作 | REC-10/11/12、DESK-02/05；recoverySwitch、pcRestart、processSupervisor |

夹具启动示例：

```powershell
# B：缺估时
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MissingDuration -PythonExecutable $pythonPath -WebView2Path $webviewPath
# D/G：P 中的 A 与 Q 中的 B；B 比 A 晚 90 秒
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath
# F：窗口 180 秒，检查点 60 秒
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case ShortWindow -PythonExecutable $pythonPath -WebView2Path $webviewPath
# H：保留足够的真实重启操作时间（窗口仍是 4 小时测试窗口）
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Run -Case MultiplePlans -DurationSeconds 600 -SecondDelay 90 -PythonExecutable $pythonPath -WebView2Path $webviewPath
```

无窗口／无估时、本地次日零点、安静时段、离线跟进、全部写入故障与竞争由 Run 中的可控时钟／临时库测试覆盖；不要求操作者等到零点，不伪造人工结果。需要检查 Windows 无窗口入口时可用 `-Case WithoutWindow`，它仍有已确认估时；不把它称为正式设置。

## 五项宿主与真实 PC 重启

1. 同一轮再次运行 `-Mode Resume -DataDirectory $runDirectory`：只激活原窗口，不增加宿主或 Core。关闭主窗留托盘、小窗叉号关闭后从托盘恢复，反复三次，仍置顶。执行中关闭不改变会话；等待收尾关闭必须先保存最小证据才隐藏。
2. 托盘选择“启用本用户登录时启动”；主窗必须显示已启用。该项仅写当前用户 Run 键 `ADHDSupportI02`，保存本轮完整启动参数，不改领域状态。
3. A 执行中保存重启前记录：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode BeforeReboot -DataDirectory $runDirectory
```

4. 用户自行保存其他应用工作并正常重启 PC、重新登录。不要再次 Run 或重建数据库；等待登录启动的原宿主出现。
5. 执行重启后核对：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode AfterReboot -DataDirectory $runDirectory
```

脚本要求系统启动时间变化、宿主/Core 各 1、数据库身份一致，并保存前后完整合成状态。人工还要核对同一会话及检查时间、被动或过期状态、不重放旧通知。若重启耗时跨过领域期限，应按对应已确认期限退出，不要求已经到期的会话仍执行中。

6. 在同一轮受控终止 Core，观察受限守护自动重启、状态仍来自同库：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode RestartCore -DataDirectory $runDirectory
```

最多三次自动重启、退避 1/2/4 秒；第 4 次受控退出后停止守护，UI 不能显示提交成功。检查上限另开一轮，避免污染 H 的剩余步骤。日志保留 core_connected/core_disconnected/core_restart_limit_reached。恢复测试不是断电或数据库损坏测试。

7. 完成后托盘选择“关闭本用户登录时启动”，主窗确认成功，再从托盘退出。若宿主不能打开，当前用户 PowerShell 的对应清理命令是：

```powershell
Remove-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'ADHDSupportI02' -ErrorAction SilentlyContinue
```

只移除此应用启动值；不要删除整个 Run 键或其他启动项。保留本轮数据和失败日志供核验。

## 收集与结束

`observations.json` 是本轮观察模板；仅修改做过的字段为 PASS／FAIL，其余保留 NOT_RUN，无法执行写 BLOCKED。每项用一个另存的简短步骤记录说明本轮做了哪个参数分支，避免把单次操作当作所有变体。

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I02 -Mode Collect -DataDirectory $runDirectory
Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $runDirectory 'evidence-summary.json')
```

Collect 要求宿主已退出；记录最终状态、源码 commit、环境、二进制哈希、数据库 ID、观察及文件哈希，包括本轮重启和中间快照。回传摘要、合成快照、人工观察和脱敏桌面事件；原始 `run.json` 含本机路径、SQLite 文件等继续本机受控保留，不提交仓库。不要附个人方案、屏幕内容或令牌。

本阶段退出点是完成本轮步骤并保存证据，不自动进入 I-03 或正式观察。若 G-01 仍未确认，其他项的 Windows 结果单独记录，整体保持未 PASS，无需为等待决定反复执行同一轮。
