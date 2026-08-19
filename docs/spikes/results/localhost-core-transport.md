# V-02：localhost Core 传输、端口发现与临时令牌验证

> 当前状态：**BLOCKED（待 Python x64 最小 Windows 复验）**。2026-08-19 的 Windows 运行期传输检查为 PASS，但其环境摘要只记录 Python 版本，未记录实际 Python 进程位数；而 Python `3.12.3` x64 是 V-02 的锁定约束。因此该历史 PASS 在新的证据身份链补齐前不构成当前最终结论。该复验只覆盖环境身份，不改变传输结论、产品范围、领域模型或 ADR。

## 任务边界

- 任务类型：technical spike；对应 [Issue #17](https://github.com/Annzival/ADHD-Support-System/issues/17)。
- 本文只记录 localhost 传输与启动边界证据，不定义 B-03 的领域 API，也不修改产品范围、领域模型或 ADR。
- Core 测试替身只处理预生成的假上下文 ID；没有 SQLite、调度、LLM、正式产品状态或正式领域命令。
- Windows 10 22H2 x64 是唯一可判定最终结果的环境。Linux、WSL、mock、源码阅读或交叉编译不能单独构成最终 PASS。

## 阶段 A：Linux 准备

**当前状态：READY_FOR_WINDOWS（2026-08-18）。**

已准备的一种最小握手机制是一次性 bootstrap file：Wails 宿主提供临时文件路径，Python Core 在 127.0.0.1:0 绑定并生成每运行令牌后原子写入端点与令牌，宿主读取后立即删除该文件。宿主只将令牌保留在内存，并用 HTTP Authorization 头和同样的 WebSocket 升级头完成假上下文往返。

阶段 A 只能在平台无关检查通过后更新为 READY_FOR_WINDOWS 或 BLOCKED。它绝不代表 Wails、WebView2、Windows 进程启动或 Windows 网络行为已通过。

本次已通过的阶段 A 检查：

- `python3 -m unittest discover -s spikes/localhost-core-transport/agent_core -p 'test_*.py'`：3 项 Core 假协议测试通过，覆盖动态回环交接、HTTP/WebSocket 认证与拒绝、旧连接/旧令牌失效及延迟交接；
- `python3 spikes/localhost-core-transport/scripts/verify_static_contract.py`：通过，确认锁定版本、一次性握手、边界禁项、日志排除和脚本 ASCII 约束；
- 使用临时隔离的锁定 Go `1.25.0` 工具链执行 `GOOS=windows GOARCH=amd64 go test ./...` 与 `go build -buildvcs=false`：均通过。

最后一项仅验证 Windows 目标源码能够交叉编译，不能替代真实 Windows 的 Wails、WebView2、进程启动或网络集成证据。Windows checkpoint 将在 Issue #17 的阶段 A 更新和 Draft PR 中以提交 SHA 锁定。

## 阶段 B：Windows 10 22H2 x64 实机核验

历史执行 checkpoint：`5cc2c4f5c9dae70f59a0e5c7a0b01febc36d8bee`。回传的脱敏摘要、原始 ZIP 与用户声明的 SHA-256 均已由本 session 核验。目标环境记录为 Windows 10 家庭中文版 `10.0.19045` / `22H2` x64，Go `1.25.0`、Python `3.12.3`、Wails `v3.0.0-beta.8`、WebView2 Fixed Version Runtime `151.0.4129.78`；但该历史摘要没有 `actual.python.processBits`，所以需要一次最小 Windows 复验。

| Issue #17 验收项 | 预期证据 | 当前记录 |
| --- | --- | --- |
| 1. 仅回环且动态端口 | `loopback_dynamic_endpoint=PASS`；候选证据的 endpoint family 为 `127.0.0.1`；Core 事件记录 3 次 `core_bound_loopback`。 | PASS |
| 2. 受限握手、无端口扫描/固定端口 | `handshakeMethod=one_time_bootstrap_file`；`bootstrap_deleted_after_read=PASS`；宿主事件有 2 次 `bootstrap_consumed`，归档内 handoff 文件数为 0。源码静态契约要求动态回环端点。 | PASS |
| 3. 认证 HTTP 与 WebSocket 假上下文往返 | `authenticated_http_round_trip=PASS`、`authenticated_websocket_round_trip=PASS`；假上下文 ID 为预生成的 `v02-fake-context-0001`。 | PASS |
| 4. 缺失、错误、上一运行令牌拒绝 | HTTP / WebSocket 的 missing、incorrect、previous-run 共 6 项拒绝检查均为 PASS；Core 事件有 6 次 `authentication_rejected`。 | PASS |
| 5. Core 不可用或握手超时不伪造就绪 | `bootstrap_timeout_is_not_ready=PASS`、`core_unavailable_is_not_ready=PASS`；诊断类别为 `bootstrap_timeout_not_ready`、`core_unavailable_not_ready`。 | PASS |
| 6. 一次 Core 重启后重新连接 | `old_websocket_invalid_after_restart`、`new_run_material_changed`、两项 previous-run 拒绝与两项 reconnected 往返均为 PASS；Core 事件有 1 次 `controlled_restart_requested`。 | PASS |
| 7. 无原始令牌与薄宿主边界 | `ordinary_logs_exclude_material=PASS`；独立扫描归档 JSON / JSONL / log 未发现 `token`、`authorization` 或 `credential` 的 JSON 字段；静态契约重跑通过，且未发现 SQLite、调度、LLM、前端持久化或正式领域实现。 | PASS |
| 8. 身份链与可复核性 | 历史实现与验证脚本 commit、摘要、manifest、run.json、validation report 和 5 个运行期文件哈希一致；但历史环境证据未记录实际 Python 进程位数。新 checkpoint 必须记录 `actual.python.processBits=64` 并刷新摘要。 | BLOCKED（复验待执行） |

历史 `validation-report.json` 的 17 项必需检查均为 PASS，`failureCount=0`；历史 `candidate-results.json` 的 17 项检查也均为 PASS。只使用了一种握手机制，没有尝试第二种机制。新的 Windows 复验必须以包含 Python `processBits=64` 的环境报告重新建立身份链后，才能恢复最终 PASS。

## 原始证据、脱敏摘要与完整性核验

已提交的脱敏机器可读摘要见 `localhost-core-transport.evidence-summary.json`。该文件不含原始日志正文、绝对路径、Windows 账户名、PID、临时令牌或 Authorization header。

复核补充：`versions.json` 锁定 Python `architecture=amd64` 与 `processBits=64`，README 也将 Python 3.12.3 x64 列为前置条件。历史摘要只含 `Python 3.12.3` 字符串，不能证明该进程不是 32 位。`Check-WindowsEnvironment.ps1` 现通过 Python 实际运行 `struct.calcsize("P") * 8` 记录 `actual.python.processBits`；`Collect-Evidence.ps1` 会拒绝缺少该字段或不是 64 的环境报告，并将该值写入脱敏摘要。

- 回传脱敏摘要 SHA-256：`cbc6cea4738ad82641dafb6385e2b31864b012c3ed3ddc8c494eab7c298a3bd8`；
- 原始 ZIP：`v02-windows-evidence-5cc2c4f5c9da-20260819T181300Z.zip`；其 SHA-256 为 `c267883693792cf4c637d640625e36a5916ae6893e29e6be2f4429b8e1d4cb1a`，与回传值完全一致；ZIP CRC 检查通过；
- ZIP 内 `run.json`、`candidate-results.json`、`validation-report.json`、`host-events.jsonl`、`core-events.jsonl` 的 SHA-256 均与 return manifest 和摘要重算一致；
- 环境、构建、静态契约 3 份准备期报告遵循 `Collect-Evidence.ps1` 的既定设计，仅以 SHA-256 记录在 manifest / 摘要中，保留在 Windows 受控位置而不复制入 ZIP；这限制了远程对其原始字节的重算能力，但不影响其与 checkpoint、运行期证据和收集脚本的哈希关联；
- Windows Core 源码哈希 `BDEB7C0442E8F25BD017764B96C1E237DE3C16ECE1F81A11A51358EEA5F13D32` 精确等于该 checkpoint Git blob 的 CRLF 工作树转换哈希；Linux LF blob 哈希为 `D8312A35CA2BF6C07DF5F6885F1B5BFC6357417A5960D733976EA204D1EE4AF8`。仓库没有 `.gitattributes`，因此这是 Windows 工作树换行差异，不是源码身份冲突；
- 原始 ZIP 继续保留在 Windows 工作副本 `spikes/localhost-core-transport/.evidence/packages` 的受控位置，经私有渠道访问；不得提交 Git 或发布到公开对象存储。保留至少至 Issue #17 和 Draft PR #20 完成审查。

## 当前复验结论

- 当前最终状态：**BLOCKED**，仅因 Python x64 的实际进程位数未在历史 Windows 环境报告中记录；这不是一次性 bootstrap file、HTTP、WebSocket、临时令牌或 Core 重启的失败。
- 复验要求：在包含此修正的新 checkpoint 上运行 PowerShell 解析、环境检查、构建、宿主验证和证据收集。新脱敏摘要必须显示 `targetEnvironment.tools.python.processBits=64`，且新的环境、构建、静态契约、run 与 validation 证据必须使用同一 checkpoint。
- 历史尝试：1 种握手机制（`one_time_bootstrap_file`）、1 次可核验的 Windows 候选运行。旧 checkpoint `a5dabefaac334ae1c40e3c2fee67f509492a10d6` 曾在 Build 阶段暴露 Windows 对旧 WebSocket 写入报告 `ConnectionResetError` 的测试兼容性问题；它在启动宿主前停止，未构成握手失败。
- 限制与风险：一次性 bootstrap file 只用于同一台 PC、同一用户会话的启动交接，不声称防御拥有相同用户权限的恶意本地进程；结论不能外推到其他 Windows、Wails、Go、Python 或 WebView2 版本。准备期报告虽受控保留并按哈希关联，但未包含在回传 ZIP 中。
- ADR / 产品范围冲突：未发现与 ADR-0008、ADR-0009、ADR-0010、ADR-0011、既有产品范围或领域模型的冲突；未修改这些内容。

本结果不自行宣告 MVP 构建就绪、不将 Draft PR 标记为 Ready、不合并 PR，也不启动 V-03 或 MVP implementation。
