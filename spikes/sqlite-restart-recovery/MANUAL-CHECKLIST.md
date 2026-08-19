# V-03 Windows PC 重启执行与回传清单

自动检查覆盖合成状态提交、未提交事务回滚、Core 重启、未来合成动作一次性产生、过期合成干预不补发、合并恢复信号一次性产生和重复扫描。执行者不需要输入数据库查询、端口、令牌或合成时间。

| 步骤 | 操作 | 通过观察 | 失败时保留 |
| --- | --- | --- | --- |
| W1 | 对照 `git rev-parse HEAD` 与 Issue #18 指定 checkpoint。 | SHA 完全一致。 | 实际 SHA。 |
| W2 | 运行 PowerShell 解析、锁定环境和构建脚本。 | 每项零退出；Python 实际 `processBits=64`；环境、构建和静态检查报告位于 `.evidence\preparation`。 | 控制台输出和 preparation 目录。 |
| W3 | 运行 `Prepare-RebootCheckpoint.ps1`。 | 输出 `safe to restart`；检查点含合成准备摘要与重启前启动标识。 | 检查点和 preparation 目录。 |
| W4 | 在同一交互式 Windows 会话执行一次真实 PC 重启并重新登录。 | 不在重启前运行恢复脚本。 | 无法重启时停止并说明原因。 |
| W5 | 运行 `Start-RecoveryValidation.ps1`。 | 输出 `Recovery evidence run complete`；候选、进程计数和验证报告均为 PASS；启动标识变化。 | 整个对应 run 目录。 |
| W6 | 运行 `Collect-Evidence.ps1`。 | 输出脱敏摘要路径和原始 ZIP SHA-256。 | 脱敏摘要、ZIP、SHA-256。 |

执行后只需回传：

1. checkpoint SHA；
2. `v03-evidence-summary-<sha>.json`；
3. 对应 ZIP 原件和脚本输出的 SHA-256；
4. 若失败，失败命令、退出码和保留的证据位置。

不要回传 SQLite 文件、bootstrap 文件、临时令牌、`.spike-run.json`、原始日志正文、绝对路径、Windows 账户名、进程 ID、截图或录屏。
