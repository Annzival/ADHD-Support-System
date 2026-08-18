# V-02 Windows 执行与回传清单

这份清单只要求有限操作。自动脚本承担 HTTP、WebSocket、拒绝、超时、Core 重启和日志检查；执行者不需要手工输入端口、令牌或假上下文。

| 步骤 | 操作 | 通过观察 | 失败时保留 |
| --- | --- | --- | --- |
| W1 | 将 git rev-parse HEAD 与 Issue #17 checkpoint 对照。 | SHA 完全一致。 | 实际 SHA。 |
| W2 | 运行 PowerShell 解析、环境和构建脚本。 | 每个命令为零退出；环境和构建报告写入 .evidence\preparation。 | 控制台输出和 .evidence\preparation。 |
| W3 | 运行 Start-Spike.ps1，等待 Wails 窗口自动结束。 | 输出 Evidence run complete；最新运行的 candidate-results.json 与 validation-report.json 都为 PASS。 | 整个对应运行目录。 |
| W4 | 运行 Collect-Evidence.ps1。 | 输出脱敏摘要路径和原始 ZIP SHA-256。 | 脱敏摘要、ZIP、SHA-256。 |

执行后只需回传：

1. checkpoint SHA；
2. v02-evidence-summary-<sha>.json；
3. 对应 ZIP 原件和脚本输出的 SHA-256；
4. 若失败，失败命令、退出码和保留的证据位置。

不要把临时令牌、.spike-run.json 内容、原始日志正文、绝对路径、Windows 账户名、进程 ID、截图或录屏直接粘贴到 Issue 或 Git。
