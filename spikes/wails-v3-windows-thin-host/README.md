# V-01 Windows/Wails 薄桌面宿主最小验证包

这是 V-01 `technical spike` 的阶段 A 产物，不是 MVP 功能或正式桌面实现。宿主只处理系统托盘、窗口、开机启动、通知回调和 Python 测试替身的机械性进程生命周期；不访问 SQLite、不保存权威领域状态、不做调度或干预规则，也不调用 LLM。

## 锁定候选

完整的机器可读锁定见 [versions.json](versions.json)。候选是：Windows 10 22H2 x64（基线 `10.0.19045`，实机 UBR 会采集）、Wails `v3.0.0-beta.8`、Go `1.25.0`、WebView2 Fixed Version Runtime `151.0.4129.78` x64、Python `3.12.3` x64。

WebView2 选择 Fixed Version，是为了不让 Evergreen 自动更新改变这次 spike 的二进制版本；它只下载到本工作副本的 `.tools/`，不安装正式产品。

## Windows 执行步骤

在交互式 Windows 10 22H2 x64 桌面会话完成。不要在 WSL、远程无桌面会话或其他 Windows 版本中替代本验证。

1. 获取 Issue #11 注明的精确 checkpoint，并确认：

   ```powershell
   git rev-parse HEAD
   ```

   输出必须与 Issue #11 的待执行 commit SHA 完全相同。

2. 安装锁定的 [Go 1.25.0 x64 MSI](https://go.dev/dl/go1.25.0.windows-amd64.msi) 和 [Python 3.12.3 x64](https://www.python.org/ftp/python/3.12.3/python-3.12.3-amd64.exe)。Python 安装时启用 Python Launcher；完成后重新打开 PowerShell。

3. 在本目录运行：

   ```powershell
   Set-ExecutionPolicy -Scope Process Bypass
   .\scripts\Install-WailsCli.ps1
   .\scripts\Install-WebView2FixedRuntime.ps1
   .\scripts\Check-WindowsEnvironment.ps1
   .\scripts\Build-Spike.ps1
   ```

   任一脚本非零退出时停止，不要手工修改代码追求通过；保留 `.evidence\preparation\` 的文件。

4. 运行 A：

   ```powershell
   .\scripts\Start-Spike.ps1
   ```

   按 [人工观察清单](MANUAL-CHECKLIST.md) 完成 A1–A6。A6 的真实注销/重新登录后，继续在同一个工作副本运行：

   ```powershell
   .\scripts\Invoke-SingleInstanceCheck.ps1
   .\scripts\Invoke-ProcessSupervisorScenario.ps1 -Scenario SingleCrash
   ```

   然后从托盘菜单选择“退出验证宿主”。等待宿主和测试替身都退出。这是“明确退出且不重启”的唯一正常退出操作，不要用任务管理器替代。

5. 运行 B（专门覆盖连续异常、退避和重启上限）：

   ```powershell
   .\scripts\Start-Spike.ps1
   .\scripts\Invoke-ProcessSupervisorScenario.ps1 -Scenario RestartLimit
   .\scripts\Cleanup-Spike.ps1
   ```

   `RestartLimit` 预期依次记录 `1s`、`2s`、`4s` 退避，并在第 4 次受控异常后停止重启。`Cleanup-Spike.ps1` 只停止本目录精确匹配的宿主/测试替身并移除本 spike 的开机启动值；它保留全部证据。

6. 在完成 A、B 两次运行后，记录观察、汇总并打包：

   ```powershell
   .\scripts\Record-ManualObservations.ps1
   .\scripts\Test-ValidationEvidence.ps1
   .\scripts\Collect-Evidence.ps1
   ```

   将最后一个脚本输出的 ZIP、人工观察中填写的截图/录屏（如有）和命令失败输出返回本技术 session。Windows 工作副本不提交、不推送。

## 证据与清理

- `.evidence\runs\`：每次运行的 JSON、JSONL 和宿主/测试替身日志；ZIP 仅打包当前 commit 的运行。
- `.evidence\preparation\`：环境与构建预检日志。
- `.tools\webview2-fixed-*`：仅用于这次验证的 Fixed Version Runtime。如需删除该大文件，最后运行：

  ```powershell
  .\scripts\Cleanup-Spike.ps1 -RemoveFixedRuntime
  ```

  此操作不会删除 `.evidence\`。

`Test-ValidationEvidence.ps1` 只生成候选证据汇总，不会自行判定 Windows 能力最终 `PASS`。最终结论必须由收到证据的同一 Linux 技术 session 写入中文结果文档。
