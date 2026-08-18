# V-02：localhost Core 传输、端口发现与临时令牌验证

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

## Windows 结果模板

以下每项由 candidate-results.json、validation-report.json、环境/构建报告和脱敏摘要填入；未返回 Windows 证据前保持“待执行”。

| Issue #17 验收项 | 预期证据 | 当前记录 |
| --- | --- | --- |
| 1. 仅回环且动态端口 | loopback_dynamic_endpoint=PASS，环境与运行元数据。 | 待执行 |
| 2. 受限握手、无端口扫描/固定端口 | one_time_bootstrap_file、bootstrap_deleted_after_read=PASS。 | 待执行 |
| 3. 认证 HTTP 与 WebSocket 假上下文往返 | 两个 authenticated 轮转检查为 PASS。 | 待执行 |
| 4. 缺失、错误、上一运行令牌拒绝 | 六个 rejected 检查为 PASS，且不返回假上下文。 | 待执行 |
| 5. Core 不可用或握手超时不伪造就绪 | bootstrap_timeout_is_not_ready 与 core_unavailable_is_not_ready 为 PASS。 | 待执行 |
| 6. 一次 Core 重启后重新连接 | old WebSocket、run material 与两个 reconnect 检查为 PASS。 | 待执行 |
| 7. 无原始令牌与薄宿主边界 | ordinary_logs_exclude_material、静态契约报告、Git 忽略规则。 | 待执行 |
| 8. 身份链与可复核性 | checkpoint、host 二进制 SHA-256、Core 源码 SHA-256、脚本 commit、环境、源文件哈希、ZIP SHA-256。 | 待执行 |

## 原始证据与脱敏

Windows 收集脚本生成：

- 机器可读脱敏摘要：只含能力状态、假上下文 ID、版本、commit、SHA-256 和诊断类别；
- 原始 ZIP：保留在 Windows 工作副本的 .evidence\packages 受控位置，不提交 Git 或公开对象存储；
- 原始 ZIP SHA-256：由 Collect-Evidence.ps1 输出并由本 session 核验；
- 访问方式：经 Issue #17 / Draft PR 约定的私有渠道传递，接收后先核对 SHA-256；
- 保留期：至少至 Issue #17 与其 Draft PR 完成审查并记录最终结论。

## 最终结论模板

- 最终状态：待 Windows 证据返回后填写 PASS / FAIL / BLOCKED。
- 尝试次数：待填写；首次机制通过即停止。
- checkpoint 与身份链：待填写。
- 逐项验收结论：待填写。
- 限制与风险：一次性 bootstrap file 不声称防御拥有同一用户权限的恶意本地进程；结论不能外推到其他 Windows、Wails、Go、Python 或 WebView2 版本。
- ADR / 产品范围冲突：待填写；如发现，仅记录并回传，不修改 ADR。

本结果不会自行宣告 MVP 构建就绪、标记 PR Ready、合并 PR 或启动 V-03。
