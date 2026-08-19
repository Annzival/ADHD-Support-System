# V-03：SQLite、Core 重启与 PC 重启恢复验证

> 最终结论：**PASS**（2026-08-19）。本结论只证明 Issue #18 中明确标记的合成状态与合成调度恢复机制，在指定 Windows PC 的一次真实重启中可行；不表示 MVP 构建就绪，不定义 B-03/B-04 的正式领域语义，也不将 spike 代码认定为产品实现。

## 任务边界

- 任务类型：`technical spike`；对应 [Issue #18](https://github.com/Annzival/ADHD-Support-System/issues/18)。
- SQLite 只由 Python Core 访问。Wails 仅进行机械进程守护、V-02 bootstrap 端点发现、令牌内存桥接和证据采集；它不读取数据库、不执行调度/失效判断、不持有权威状态，也不调用 LLM。
- 所有表、稳定 ID、版本、时间、状态、已处理标记和可观察记录均以 `synthetic_` 明确标记，只用于本 spike。
- Linux、WSL、源码阅读、mock、交叉编译或 Core 进程重启都不能单独证明真实 PC 重启后的 `PASS`；本次结论以阶段 B 的实机证据为准。

## 最终结果概览

| 项目 | 已核验结果 |
| --- | --- |
| 最小机制与尝试次数 | `python_sqlite_synthetic_recovery_with_one_time_bootstrap`；第 1 种最小机制通过，未启动第二次尝试。 |
| checkpoint、实现与验证 commit | `1ca7d92af59e78d749624b7788af15b0d7ee7874`。 |
| Windows 运行 ID | `run-20260819T215308Z-1ca7d92af59e`。 |
| 目标实机 | Windows 10 22H2 x64；Python 3.12.3（64 位进程）、Go 1.25.0 windows/amd64、Wails v3.0.0-beta.8、固定版 WebView2 151.0.4129.78。 |
| 真实重启与进程计数 | 启动标识已变化；恢复时 Wails 宿主 `1`、Python Core `1`。 |
| 合成恢复结果 | 同一合成 SQLite 身份与 checkpoint 一致；4 项准备检查、5 项宿主检查、6 项 Core 检查均为 `PASS`，验证失败数为 `0`。 |
| 结果摘要 | 见 [最终脱敏机器可读摘要](sqlite-restart-recovery.evidence-summary.json)。 |

## 首个最小机制

Python 标准库 `sqlite3` 使用 `BEGIN IMMEDIATE` 事务与 WAL journal：先写入已提交的合成权威状态和两条合成调度记录，再由受控异常子进程在未提交事务中写入一条故意中断的行。重新打开同一文件时，已提交内容必须保留，而未提交行必须不存在。

恢复 Core 在固定 UTC 时钟运行：未来合成记录只可通过唯一键写入一条可观察动作；已过期合成记录不逐条补发，而是只形成一条合并恢复信号；第二次扫描和 Core 正常重启后的再次扫描必须均为幂等。Wails 每次启动通过 V-02 一次性 bootstrap file 重新获得动态回环端点与临时令牌；令牌不会写入摘要、普通日志或持久化数据库。

## 阶段 A：Linux 准备

阶段 A 的平台无关检查为：

```bash
python3 -m unittest discover -s spikes/sqlite-restart-recovery/agent_core -p 'test_*.py'
python3 spikes/sqlite-restart-recovery/scripts/verify_static_contract.py
```

隔离的锁定 Go `1.25.0` 工具链还完成了 Windows x64 `go test ./...` 与 `go build -buildvcs=false`；它们只验证源代码/API，不替代目标 PC 的 Wails/WebView2/重启证据。

阶段 A 已通过：Python `unittest` 5/5（提交状态、受控异常、CLI 摘要、重复扫描、bootstrap/Core 重启）、静态契约检查，以及隔离 Go `1.25.0` 的 Windows x64 `go test ./...`、`go build -buildvcs=false`。交叉构建二进制 SHA-256 为 `8a057e52ef133bc2fa99e8ba08ca77925f0c91ef1cd3e00c22bdbf79bd908cdf`。脱敏阶段 A 摘要见 [sqlite-restart-recovery.phase-a-summary.json](sqlite-restart-recovery.phase-a-summary.json)。

## 阶段 B：Windows 10 22H2 x64 真实 PC 重启

Windows 执行者在指定 checkpoint 完成准备后执行了一次真实 PC 重启并重新登录；重启后脚本确认启动标识不同，随后才启动薄 Wails 宿主和 Python Core。核验结果如下：

- checkpoint 中的合成 SQLite 身份与第一次恢复、正常 Core 退出后的第二次恢复一致；已提交合成权威状态的稳定 ID、版本和内容保持一致。
- 初次恢复扫描恰好产生：未来一次性动作 `1`、已过期记录处理 `1`、合并恢复信号 `1`。
- Core 正常退出后的恢复扫描与重复扫描均为 `0/0/0`，最终可观察记录总数为未来动作 `1`、合并恢复信号 `1`；没有重复动作。
- 运行期使用 V-02 的 `one_time_bootstrap_file`，端点族仅为 `127.0.0.1`；普通日志不含敏感材料的检查为 `PASS`。

## 原始证据、完整性与脱敏

原始证据 ZIP 不提交 Git，也不在本文公开其内容。它由 Windows 工作副本的受控位置经约定私有渠道回传，并应保留至 Issue #18 与 Draft PR 审阅完成。

| 项目 | 已核验值 |
| --- | --- |
| 原始 ZIP 文件名 | `v03-windows-pc-restart-evidence-1ca7d92af59e-20260819T215324Z.zip` |
| 原始 ZIP SHA-256 | `1a8a28e07c687839614490adad67e8877ad153376e6eb718038cac4be0ec6398` |
| 回传摘要 SHA-256 | `3ba3f11ac75a41fea430e79d4574993c1a7f424d36629f5ce28bf21b16dcbda2` |
| ZIP CRC | `PASS` |
| 证据包内运行文件哈希 | 10 个运行文件的 SHA-256 多重集合与返回清单一致；checkpoint 及 4 个受控保留报告均有清单哈希。 |
| 实现身份 | checkpoint、运行、返回清单和摘要中的 commit、Core 源码 SHA-256、宿主二进制 SHA-256 相互一致；Core 源码哈希按 Windows CRLF checkout 形式复算通过。 |

提交的机器可读摘要只保留版本、commit、运行 ID、布尔结果、计数和 SHA-256；不包含绝对路径、Windows 账户名、进程 ID、临时令牌、Authorization header、原始日志、SQLite 字节、截图或录屏。证据中启动时间的 `Z` 与等价时区偏移表示已按同一时刻比较，不作为不同启动事件。

## Issue #18 验收映射

| Issue #18 验收项 | 本次直接证据 |
| --- | --- |
| 1. 已提交权威状态经正常/受控异常退出可恢复 | 准备与 Core 检查均为 `PASS`；第一次恢复和正常 Core 重启后的合成权威状态稳定 ID、版本、内容一致。 |
| 2. 中断写入不会形成半更新 | `synthetic_uncommitted_write_rolled_back` 与 `synthetic_interrupted_write_absent` 均为 `PASS`。 |
| 3. 未来合成调度只产生一次 | 首次恢复产生未来动作 `1`；正常 Core 重启与重复扫描均为 `0`；最终总数为 `1`。 |
| 4. 过期干预不补发、只形成一次合并恢复 | 首次恢复产生合并恢复信号 `1`；后续扫描均为 `0`；最终总数为 `1`。 |
| 5. 连续扫描与 Core 重启不重复 | 6 项 Core 检查全为 `PASS`，第二次恢复和重复扫描均无新增动作。 |
| 6. Windows 真实重启、单一宿主/Core、同一文件恢复 | 启动标识变化、进程计数 `1/1`、同一合成 SQLite 身份、回环一次性 bootstrap 均已核验。 |
| 7. SQLite/Core 与 Wails 边界 | 阶段 A 静态契约为 `PASS`；阶段 B 运行期只复用 V-02 一次性 bootstrap/回环边界，未发现 Wails 直接访问 SQLite 或执行调度、失效判断、LLM 的证据。 |
| 8. commit、摘要、环境、运行 ID 与脱敏证据对应 | checkpoint/实现/验证 commit 均为 `1ca7d92…`；环境、运行 ID、摘要、清单、ZIP CRC 与 SHA-256 均已交叉核验。 |

## 限制、风险与冲突检查

- 此 `PASS` 仅覆盖一次 Windows 10 22H2 x64 实机重启、单一用户会话、锁定版本和明确标记的合成数据；不覆盖异常断电、数据库加密、备份恢复、恶意同权限进程、其他 Windows 版本或多设备同步。
- 受控保留的 4 个准备报告以 SHA-256 纳入清单，但其原文未随回传 ZIP 发布；最终机制结论以 ZIP 中的 checkpoint、run、候选结果、验证报告、进程快照和脱敏摘要的交叉核验为依据。
- 未发现与 ADR-0008、ADR-0009、ADR-0010、ADR-0012、ADR-0016、ADR-0017、产品范围或领域模型的冲突。该技术结论不改变任何 ADR 或产品决策。
- 不标记 Ready，不合并 Draft PR，不修改 B-03/B-04，也不开始 MVP implementation。
