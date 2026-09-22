# I-01 复审修复：Windows 定向回归

2026-09-23：本轮已在 `21b4a24` 实机通过并核验。已回传的操作者无需重做；本手册保留供复现。当前只等待独立代码复审，详见[结果报告](results/mvp-first-vertical-slice.md)。

针对 `3c80071` 复审的送达重试和收尾草稿问题。旧 A／B／C／D 实机证据继续保留；不要求重做四轮。本轮只确认新宿主仍能正常呈现，以及真实 Core 断连后收尾输入不变。领取／回执丢包由 Run 内的 Go 自动测试精确注入，人工不需要制造网络丢包。

## 1. 更新并启动新一轮

先从托盘退出原应用。在 Windows 仓库根目录的同一 PowerShell 窗口执行：

```powershell
git pull --ff-only
git status --short
git rev-parse HEAD
```

若拉取报错或状态非空，先回传输出，不继续。保留旧证据目录。沿用之前正确的 `$fixedWebView2` 和 `$pythonExe`；变量已丢失时，按 [Windows 手册 0.2](windows-i01.md#02-只填写两个本机路径) 填写实际路径。

```powershell
$batchDir = Join-Path (Get-Location).Path ('.i01-runs\review-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $batchDir | Out-Null
$runR = Join-Path $batchDir 'R'
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Run -Case ConfirmedDuration -StartDelay 90 -WebView2Path $fixedWebView2 -PythonExecutable $pythonExe -DataDirectory $runR
```

Run 会先运行 Python／Go 自动检查；报错则停在此处，回传错误。本轮过程中不要再更新代码。

## 2. 通知、开始与收尾草稿

1. 到点后确认系统通知和小窗出现；点击通知“查看当前行动”，应回到正确行动。确认没有同一开始提醒的重复呈现。
2. 点击“立即开始”，看到会话与检查时间后点击“已经完成”。本轮不要求赶在首次检查之前。
3. 等待收尾界面中选择 **部分完成**，实际用时填写 **12 分钟**。不要提交或关闭窗口。
4. 保存快照，然后只重启 Core：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runR
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode RestartCore -DataDirectory $runR
```

5. 等待连接恢复，确认仍是同一会话的等待收尾，结果仍为“部分完成”、用时仍为“12”。较快重连可能看不到离线文案，记录实际现象即可。若约 15 秒仍未恢复或输入变化，停止后续提交，回传实际现象。
6. 恢复后保存第二份快照，随后在界面点击“完成收尾”：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Snapshot -DataDirectory $runR
```

预期：显示已结束、已确认部分完成。最终证据应为 partial、720 秒，行动不标为全部完成；这部分由回传后核验，不需要手工编辑 JSON。

## 3. 记录并回传

```powershell
notepad (Join-Path $runR 'observations.json')
```

按实际情况填写 `arrivalAndCorrectNotification`、`startAndFirstCheckpoint`、`awaitingClosureSurvivesRestart`、`finishClosure`，仅使用 PASS／FAIL／BLOCKED／NOT_RUN。输入是否保留、是否出现重复提醒，用回传消息文字描述；**不增加 JSON 字段**。失败也可以收集，不要为通过补做其他操作。

保存记录，从托盘“退出开发验收”，执行：

```powershell
powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01 -Mode Collect -DataDirectory $runR
```

使用 [Windows 手册的打包命令](windows-i01.md#用命令把已完成轮次打成一个包)，第一行改为 `$completedRuns = @($runR)`。回传 ZIP、SHA-256，以及“通知是否重复；断连恢复后是否仍为部分完成／12分钟；提交后显示什么”。不回传整个运行目录或 run.json。

旧 Windows PASS 不自动覆盖新实现。收到本轮证据并完成复审前，保持 Draft，不合并、不进入 I-02。
