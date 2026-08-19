# V-03：SQLite、Core 重启与 PC 重启恢复验证

> 当前阶段结论：**READY_FOR_WINDOWS**（2026-08-19）。Linux 自动检查与 Windows x64 交叉编译预检均通过；随后仍须等待 Windows 10 22H2 x64 的一次真实 PC 重启证据。本文件只记录 Issue #18 的合成恢复机制验证；不表示 MVP 构建就绪，不定义 B-03/B-04 的正式领域语义，也不将 spike 代码认定为产品实现。

## 任务边界

- 任务类型：`technical spike`；对应 [Issue #18](https://github.com/Annzival/ADHD-Support-System/issues/18)。
- SQLite 只由 Python Core 访问。Wails 仅进行机械进程守护、V-02 bootstrap 端点发现、令牌内存桥接和证据采集；它不读取数据库、不执行调度/失效判断、不持有权威状态，也不调用 LLM。
- 所有表、稳定 ID、版本、时间、状态、已处理标记和可观察记录均以 `synthetic_` 明确标记，只用于本 spike。
- Linux、WSL、源码阅读、mock、交叉编译或 Core 进程重启都不能单独证明真实 PC 重启后的 `PASS`。

## 首个最小机制

Python 标准库 `sqlite3` 使用 `BEGIN IMMEDIATE` 事务与 WAL journal：先写入已提交的合成权威状态和两条合成调度记录，再由受控异常子进程在未提交事务中写入一条故意中断的行。重新打开同一文件时，已提交内容必须保留，而未提交行必须不存在。

恢复 Core 在固定 UTC 时钟运行：未来合成记录只可通过唯一键写入一条可观察动作；已过期合成记录不逐条补发，而是只形成一条合并恢复信号；第二次扫描和 Core 正常重启后的再次扫描必须均为幂等。Wails 每次启动通过 V-02 一次性 bootstrap file 重新获得动态回环端点与临时令牌；令牌不会写入摘要、普通日志或持久化数据库。

## 阶段 A：Linux 准备

阶段 A 仅在下列平台无关检查都通过后才可标记 `READY_FOR_WINDOWS`：

```bash
python3 -m unittest discover -s spikes/sqlite-restart-recovery/agent_core -p 'test_*.py'
python3 spikes/sqlite-restart-recovery/scripts/verify_static_contract.py
```

若隔离的锁定 Go `1.25.0` 工具链可用，还需用它运行 Windows x64 `go test ./...` 与 `go build -buildvcs=false`。它们只验证源代码/API，不替代目标 PC 的 Wails/WebView2/重启证据。

本次阶段 A 已通过：Python `unittest` 5/5（提交状态、受控异常、CLI 摘要、重复扫描、bootstrap/Core 重启）；静态契约检查；以及隔离 Go `1.25.0` 的 Windows x64 `go test ./...`、`go build -buildvcs=false`。交叉构建二进制 SHA-256 为 `8a057e52ef133bc2fa99e8ba08ca77925f0c91ef1cd3e00c22bdbf79bd908cdf`。脱敏阶段 A 摘要见 `sqlite-restart-recovery.phase-a-summary.json`。

本次只实现并验证了 1 种最小机制，没有启动第二次尝试。阶段 A 结束后会在 Issue #18 写入 Windows checkpoint 和 Draft PR 地址。这个结论只有 `READY_FOR_WINDOWS` 或 `BLOCKED` 两种可能；在收到并核验 Windows 原始证据前，不写 `PASS`。

## 阶段 B：Windows 10 22H2 x64 真实 PC 重启

Windows 执行者先运行准备脚本，再完成一次真实 PC 重启；重新登录后运行恢复验证。脚本会要求：

1. 重启后的 Windows 启动标识与检查点不同；
2. 恢复时只有一个 Wails 宿主和一个 Python Core；
3. Core 通过一次性 bootstrap 重新可达；
4. Core 返回同一合成数据库身份、提交权威状态、未来一次性动作、过期不补发、一次合并恢复信号和重复扫描幂等的脱敏摘要；
5. run、检查点、摘要、返回清单和 ZIP 的 SHA-256 可以交叉核验。

详细步骤见 [最小复现 README](../../../spikes/sqlite-restart-recovery/README.md) 和 [Windows 清单](../../../spikes/sqlite-restart-recovery/MANUAL-CHECKLIST.md)。原始 ZIP、SQLite 文件和临时 bootstrap 材料不提交 Git；仅在 Windows 工作副本的受控 `.evidence` 位置保留，并通过约定私有渠道提供。

## 验收映射与待补证据

| Issue #18 验收项 | 阶段 A 自动证据 | 阶段 B 必需证据 |
| --- | --- | --- |
| 已提交状态经正常/受控异常退出可恢复 | Python 子进程和 SQLite 测试 | 同一机制的 Windows 准备摘要。 |
| 未提交写入无半更新 | 受控异常子进程后重新打开数据库 | Windows 准备摘要。 |
| 未来合成调度只产生一次 | 固定时钟、唯一可观察键和重复扫描测试 | 重启后 Core 摘要。 |
| 已过期合成干预不补发、仅一次合并恢复 | 固定时钟与唯一合并键测试 | 重启后 Core 摘要。 |
| 重复扫描/Core 重启不重复 | 同一文件的多轮扫描与 bootstrap 重连测试 | 重启后 Wails/Core run。 |
| 真实 PC 重启、单一宿主/Core、同一文件恢复 | 不可由 Linux 替代 | 启动标识变化、进程计数、检查点与恢复 run。 |
| SQLite/Core 边界 | 静态契约检查 | 同一 host/Core 源码哈希与运行证据。 |
| 身份链与证据完整性 | 阶段 A 源码/脚本检查 | checkpoint、摘要、manifest、ZIP SHA-256。 |

## 当前限制与冲突检查

- Windows 真实重启尚未执行，因此当前不是最终通过或失败结论。
- 本机制只覆盖单台 PC、同一用户会话、锁定版本和合成数据；不覆盖异常断电、数据库加密、备份恢复、恶意同权限进程、其他 Windows 版本或多设备同步。
- 未发现与 ADR-0008、ADR-0009、ADR-0010、ADR-0012、ADR-0016、ADR-0017、产品范围或领域模型的冲突。该结论只描述技术边界，不改变任何 ADR 或产品决策。
