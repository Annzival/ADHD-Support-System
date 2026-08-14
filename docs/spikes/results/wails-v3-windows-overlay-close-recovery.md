# V-01R：Wails v3 置顶小窗原生关闭恢复复验

## 最终结论

- 最终状态：`PASS`。
- 回答范围：在 Wails `v3.0.0-beta.8`、Windows 10 22H2 x64 上，overlay 使用 `WindowClosing → Cancel + Hide` 后，已在实机连续完成 3 轮“显示 → 点击原生叉号 → 再次显示”，并保持置顶、宿主/Agent Core 单实例和薄宿主边界。
- 尝试次数：1 次最小实现尝试、1 次 Windows 实机复验；首次通过即停止，未进行第二次生命周期适配。
- 本结论仅回答 Issue #14 的技术验证问题；不等同于正式采用 Wails，不改变产品范围、领域模型、既有 ADR 或 Agent Core API，也不启动 MVP implementation。
- 关联：[Issue #14](https://github.com/Annzival/ADHD-Support-System/issues/14)、[Draft PR #15](https://github.com/Annzival/ADHD-Support-System/pull/15)。

对应的脱敏机器可读摘要见 [wails-v3-windows-overlay-close-recovery.evidence-summary.json](wails-v3-windows-overlay-close-recovery.evidence-summary.json)。原始 ZIP 未提交 Git。

## 前置条件与实现范围

- 基线：PR #13 已合并到 `main@0ed8d4b`，Issue #11 已关闭；本复验从其后的 `main` 建立独立分支 `agent/spike-wails-overlay-close-recovery`。
- 实现 checkpoint：`f5a3a22887d31d49f3434bdcd6b142116d8ac0b2`。
- overlay 注册 `events.Common.WindowClosing` hook，执行 `Cancel()`、`Hide()` 并记录 `overlay_hidden_on_close`。
- 再次显示前确认 overlay 仍在 Wails 窗口表中；若默认关闭仍导致销毁，则记录 `overlay_destroyed_before_show`，不会伪造恢复成功。
- 保留原有 `SetAlwaysOnTop`、`Show`、`Focus` 和 `overlay_shown` 记录。

未升级 Wails、Go、Python 或 WebView2；未实现第二套宿主；未修改 SQLite、领域状态、领域调度、干预规则、LLM、通知、开机启动、完整守护上限或 Agent Core 接口。

## Windows 实机环境与身份链

| 项目 | 已核验值 |
| --- | --- |
| 操作系统 | Microsoft Windows 10 家庭中文版 `10.0.19045`，22H2，UBR 7663，x64 |
| Wails | `v3.0.0-beta.8` |
| Go / Python | Go 1.25.0 / Python 3.12.3（windows/amd64） |
| WebView2 | Fixed Version Runtime `151.0.4129.78` x64 |
| 实现、验证脚本、收集脚本 commit | 均为 `f5a3a22887d31d49f3434bdcd6b142116d8ac0b2` |
| 验证宿主二进制 SHA-256 | `29ED44E540819D96C3BCA95161AC56F9C709DFBC02E6184A84F073C35AC4F5D3` |
| 运行标识 | `run-20260814T235712Z-f5a3a22887d3` |

已重新计算原始 ZIP 的 SHA-256，结果为 `5124e91a7c2c6a299dc42744d8176961c7f7f31da97cbaa30158721cbf9cd421`，与回传值一致。摘要、`run.json`、构建报告和回传清单中的 commit/二进制哈希相互一致；5 个来源文件的 SHA-256 也均与 ZIP 内容相符。

## 验收证据

| Issue #14 验收项 | Windows 实机证据 | 结论 |
| --- | --- | --- |
| 显示且保持置顶 | 3 轮人工观察均为 `PASS`；7 条 `overlay_shown` 记录均为 `alwaysOnTop=true`。 | PASS |
| 原生叉号关闭转隐藏 | 3 轮人工观察均为 `PASS`；日志有 4 条 `overlay_hidden_on_close`，均为 `closeCancelled=true`。 | PASS |
| 再次显示同一 overlay 且置顶 | 3 轮人工观察均为 `PASS`；3 个要求轮次均可从日志重建为关闭后再次 `overlay_shown`。 | PASS |
| 连续完成 3 轮 | 逐轮摘要的第 1、2、3 轮均为 `PASS`；每轮的显示前、关闭转隐藏、再次显示、日志和关闭后进程快照均通过。 | PASS |
| 3 轮后的托盘显式隐藏/显示 | 人工观察均为 `PASS`；有对应 `overlay_hidden`、`overlay_shown` 记录，显示后仍置顶。 | PASS |
| 单实例和健康 | 每轮关闭后的快照及最终托盘循环快照均为：宿主 1、Agent Core 测试替身 1、loopback 健康检查通过。 | PASS |
| 无意外销毁 | `overlay_destroyed_before_show` 记录数为 0；未见新增宿主或 Agent Core 实例。 | PASS |
| 薄宿主边界 | 静态契约检查继续确认宿主未访问数据库、未执行领域调度/干预规则、未调用 LLM；Agent Core 接口未变。 | PASS |
| 身份和可复核性 | 环境报告、构建报告、运行元数据、逐轮结果、来源文件哈希、ZIP 哈希及脱敏摘要已交叉核验。 | PASS |

日志包含一个不属于所需 3 轮的额外关闭/隐藏动作。它同样带有 `closeCancelled=true`，之后仍恢复为置顶显示，且没有产生销毁或额外实例。现有收集脚本按事件偏移确认每个观察步骤，而非为日志动作分配轮次 ID；因此此处以 3 个可独立重建的完整序列和逐轮人工/进程证据判定 PASS，不把日志总数错误表述为“恰好 3 次关闭”。这是一项审计粒度限制，不是本次最小修复的失败证据。

## 自动检查

以下平台无关检查在 Windows 复验证据归档前后均保持通过；它们不替代 Windows 桌面行为证据：

    git diff --check
    python3 spikes/wails-v3-windows-thin-host/scripts/verify_static_contract.py
    python3 -m unittest discover -s spikes/wails-v3-windows-thin-host/agent_core -p 'test_*.py'

静态契约检查覆盖 `WindowClosing → Cancel + Hide`、`overlay_hidden_on_close`、`overlay_shown`、`overlay_destroyed_before_show`、三轮复验脚本、受控原始 ZIP 保留字段及薄宿主禁止项。

## 证据保留与脱敏

- 脱敏摘要只保留能力状态、逐轮观察、运行/提交标识、版本、SHA-256、事件种类和进程数量；已检查不含绝对路径、Windows 账户名、进程 ID、原始日志正文、截图或录屏。
- 原始包名：`v01r-windows-overlay-close-recovery-f5a3a22887d3-20260815T000125Z.zip`；其 SHA-256 如上。
- 原始 ZIP 保留在证据提供者 Windows 工作副本的 `spikes/wails-v3-windows-thin-host/.evidence/packages/` 受控位置，不提交 Git 或公开对象存储。审查者可通过 Issue #14 或 Draft PR 请求原件，并以该 SHA-256 校验私有传输的副本。
- 证据提供者至少保留原件至 Issue #14 的 Draft PR 复审完成且 V-01R 结论已记录。
- ZIP 内环境与构建报告在压缩阶段保留来源逻辑名 `preparation/`，archive 采用其文件名作为顶层成员；已按内容 SHA-256 核验 3 个直接成员和 2 个压缩阶段成员，未发现完整性差异。

## 限制、风险与冲突回报

- 本结论仅来自 1 台 Windows 10 22H2 x64 目标机、1 次交互式实机运行；不能外推到其他 Windows 版本、Wails 版本、WebView2 版本或正式安装器。
- 仅复验受本次窗口生命周期改动影响的关闭恢复路径；不重新认证原 V-01 已通过且未受改动影响的开机启动、通知和完整守护上限。
- 逐轮收集脚本不为每个事件写入轮次 ID；额外有效事件已如实记录。若未来需要更强的审计自动化，应单独评估事件关联字段，但不属于本次首次通过后停止的范围。
- 未发现与 ADR-0008～0011、ADR-0013、产品范围或领域模型的冲突。改动仍局限于可替换桌面宿主的窗口生命周期适配层；关闭/隐藏 overlay 不改变 Agent Core 的权威状态。

V-01R 的 `PASS` 不自行改变任何产品治理结论或宣告 Wails 正式采用；是否将本复验纳入更高层决策，仍由直接委托者或产品治理线程决定。
