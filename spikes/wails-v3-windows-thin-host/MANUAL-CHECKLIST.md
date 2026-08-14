# V-01 Windows 人工观察清单

先完成 `README.md` 的准备和“运行 A”启动步骤。每项都按照实际观察填写；失败时记录实际行为，不尝试修改代码。

| ID | 操作 | 通过观察 | 需要保留的证据 |
| --- | --- | --- | --- |
| A1 | 在主窗口点关闭。 | 主窗口隐藏；通知区域仍可见图标；宿主进程没有退出。 | 截图（可选）和 `host-events.jsonl` 中的 `main_window_hidden_on_close`。 |
| A2 | 右键托盘图标，选择“显示主窗口”。 | 原主窗口恢复并获得前台焦点。 | `main_window_shown` 日志。 |
| A3 | 从托盘选择“显示置顶演示小窗”，再选择“隐藏置顶演示小窗”。 | 小窗能够显示和隐藏。 | `overlay_shown`、`overlay_hidden` 日志。 |
| A4 | 再显示小窗，切换到任意普通窗口。 | 小窗仍在普通窗口上方；隐藏小窗后，测试替身没有重启或停止。 | 一张同时含普通窗口和小窗的截图（可选）；守护日志。 |
| A5 | 从托盘选择“发送带操作的演示通知”，在 Windows 通知中点“打开演示上下文”。 | 主窗口被激活。 | 通知截图（可选）；`notification_response_received`、`notification_context_routed`，以及 `agent-core-events.jsonl` 的 `notification_context_received`。 |
| A6 | 从托盘选择“启用开机启动（下次登录）”；执行一次真实“注销后重新登录”；确认启动；然后从托盘选择“禁用开机启动”。 | 登录后只存在一个宿主和一个测试替身；禁用后注册表值已移除。 | 登录后的任务管理器截图（可选）；`autostart_enabled`、`second_instance_activated`（若有）和 `autostart_disabled`。 |

然后运行 README 指定的单实例和守护场景脚本。对于“明确退出”，必须在运行 A 的托盘菜单选择“退出验证宿主”，并让 `Test-ValidationEvidence.ps1` 检查无宿主和测试替身进程。运行 B 中的连续异常达到重启上限后，不需要手工修复或再次启动测试替身。

最后运行 `Record-ManualObservations.ps1`。该脚本逐项要求 `PASS`、`FAIL` 或 `BLOCKED`，并让你附上已经存在的截图/录屏文件名；它不要求自行设计判断标准。
