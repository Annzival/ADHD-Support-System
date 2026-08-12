# V-01：Windows/Wails 薄桌面宿主两阶段验证计划

## 任务类型

`technical spike`

## 背景

ADR-0008 要求 Wails v3 只有在托盘常驻、置顶小窗、开机启动、可交互系统通知和 Python 进程守护均通过真实 Windows 环境验证后，才正式成为 v0.1 桌面宿主。ADR-0009～0011 将 v0.1 限定为 Windows 10 22H2 x64 单机应用，并要求桌面宿主保持为可替换薄适配层。

项目的代码和文档主工作区运行在远程 Linux 服务器上，无法直接操作 Windows 桌面；用户另有一台 Windows 10 PC。因此 V-01 使用同一技术 session、分支、Issue 和 Draft PR 完成两阶段验证：

1. **阶段 A：Linux 准备**——生成最小验证代码、Windows 执行脚本、检查清单和结果模板；
2. **阶段 B：Windows 实机执行**——用户在 Windows 10 PC 上运行阶段 A 产物并把证据返回技术 session，由技术 session 整理最终结论。

Linux 环境不能单独对 Windows 桌面能力判定 `PASS`。本任务只生产技术证据，不实现 MVP 功能，也不决定产品范围。

## 工作区与写入边界

- 远程 Linux Git 工作区及其远端分支是代码、文档和验证契约的来源；
- 技术 session 负责创建和更新 V-01 分支、Draft PR、结果文档和 Issue；
- Windows PC 只拉取阶段 A 的已推送 checkpoint，运行脚本并生成本地证据包，不直接提交或推送该分支；
- 阶段 B 执行期间，技术 session 不修改会影响复现的验证代码或脚本；如果必须修改，先记录原因、推送新 checkpoint，再要求 Windows 端从新 commit 重新执行受影响项目；
- 用户将证据包、截图、录屏或必要日志返回同一个技术 session；技术 session 负责脱敏、摘要并写入仓库结果文档；
- 大型原始视频或含本机敏感路径的日志不直接提交仓库，只在结果文档中记录经过脱敏的摘要和可控证据位置。

## 验证问题

1. 在 Windows 10 22H2 x64 上，锁定的 Wails v3 版本能否稳定提供系统托盘常驻，并区分关闭窗口、退出应用和单实例启动？
2. 能否提供可显示、隐藏、置顶且不拥有领域状态的“当前下一步行动/立即开始”演示小窗？
3. 能否注册、禁用并验证开机启动，且不会产生重复实例？
4. 能否发送带可交互操作的系统通知，并把操作携带的演示上下文标识转交给主窗口或最小 Python 智能体核心测试替身，而不是保存在 Wails 领域状态中？
5. Wails 能否启动并健康检查 Python 智能体核心测试替身；在连续受控异常退出时按配置退避、达到重启上限后停止；在用户明确退出时不重启、不残留孤儿进程？
6. 如果任一能力失败，是否存在不改变智能体核心 localhost API、唯一状态源和无 LLM 桌面宿主边界的替代路线？

## 阶段 A：Linux 准备

### 范围内

- 从最新 `main` 建立独立分支 `agent/spike-wails-v3-windows-thin-host` 和以 `main` 为 base 的 Draft PR；
- 锁定并记录候选 Wails v3、Go、WebView2、Python 和 Windows 构建版本；
- 实现最小 Go/Wails 宿主、最小静态前端和最小 Python 智能体核心测试替身；
- Wails 可以实现机械性的进程守护：启动与健康检查、区分正常退出和异常退出、限制重启次数与退避、用户明确退出后停止重启，以及记录守护日志；
- 提供 Windows 环境检查、构建、逐项验证、证据收集和清理所需的 PowerShell 脚本；
- 脚本必须尽量把 Windows 版本、Wails、Go、WebView2、Python、commit SHA、时间戳和逐项结果写入机器可读的证据清单；
- 提供人工观察清单，覆盖脚本无法自动断言的托盘、置顶、通知交互和真实登录启动行为；
- 在 Linux 上运行与平台无关的单元测试、静态检查和 Python 测试替身检查；Windows 专属行为不得用 mock 结果代替实机证据；
- 创建 `docs/spikes/results/wails-v3-windows-thin-host.md` 结果模板，明确区分阶段 A 状态与阶段 B 结论。

### 阶段 A 验收条件

只有同时满足以下条件，阶段 A 才能标记为 `READY_FOR_WINDOWS`：

- 最小验证代码、锁定版本、运行说明和清理说明已经提交并推送；
- Windows 执行有一个明确的入口脚本，失败时返回非零退出码并保留诊断信息；
- 自动收集项和需要用户观察的项目已经分开，用户不需要自行发明验收步骤；
- 结果模板列出五项必需能力及边界检查，且尚未把任何 Windows 桌面能力写成 `PASS`；
- 与平台无关的检查通过，或失败已记录为阻止进入 Windows 执行的原因；
- Draft PR、Issue #11 和待执行 commit SHA 已相互链接；
- 技术 session 已向用户提供准确、有限的 Windows 执行步骤和证据回传方式，然后暂停等待。

阶段 A 只允许两个状态：

- `READY_FOR_WINDOWS`：准备完整，可以交给 Windows PC 执行；
- `BLOCKED`：准备工作本身无法完成，记录阻塞后退出。

`READY_FOR_WINDOWS` 不是 Wails 能力的 `PASS`，也不满足 MVP 构建就绪门槛中的高风险技术验证。

## 阶段 B：Windows 实机执行

### 用户执行范围

- 在 Windows 10 22H2 x64 PC 上获取阶段 A 指定的远端分支和确切 commit；
- 确认处于可交互的 Windows 桌面登录会话，而不是只能运行无桌面的 Linux/WSL 环境；
- 按阶段 A 提供的说明运行环境检查、构建、验证和清理脚本；
- 按人工观察清单完成托盘、置顶小窗、开机登录启动、通知操作和进程生命周期观察；
- 不手工修改验证代码来追求 `PASS`；发现问题时记录实际行为；
- 将脚本生成的证据包以及必要截图或录屏返回同一个技术 session；Windows 工作副本无需提交或推送。

### 最终验收条件

每项能力必须依据 Windows 实机证据给出 `PASS`、`FAIL` 或 `BLOCKED`，不能只给“看起来可行”：

- **托盘**：关闭主窗口后进程和托盘仍存在；托盘可恢复窗口并明确退出；第二次启动不会产生独立实例。
- **置顶小窗**：可以独立显示、隐藏和保持置顶；关闭或隐藏不会改变智能体核心测试替身的状态；操作只通过演示 API 或消息转交。
- **开机启动**：能够启用、禁用，并在一次真实 Windows 登录启动验证中只产生一个宿主和一个智能体核心测试替身。
- **通知**：至少一个通知操作能激活正确窗口或路由到预先生成的演示上下文标识；失败路径有日志，通知不保存领域状态。
- **进程守护**：宿主可启动智能体核心测试替身并完成健康检查；一次受控异常退出后按配置退避并重启；连续受控异常退出时，可以观察到退避并在达到预先记录的重启上限后停止重启且留下可诊断记录；明确退出宿主后不重启，检查不到孤儿进程。
- **边界**：代码和运行证据能证明 Wails 未访问数据库、未执行领域调度或干预规则、未调用 LLM，连接和上下文转交通过可替换接口完成。
- **失败替代**：任何 `FAIL` 都要说明根因、影响范围和至少一条不破坏智能体核心边界的替代路线。
- **复现**：结果记录目标环境、待执行 commit、步骤与证据，使另一名协作者可以在相同环境复现。

整体结论规则：

- 五项必需能力及边界检查全部 `PASS`，整体才是 `PASS`，并且只表示可以建议保留 Wails v3 首选；
- 任一必需项 `FAIL`，整体为 `FAIL`，返回产品治理主线程决定是否更换宿主；
- Windows 环境、权限或证据不完整使某项无法判定时，整体为 `BLOCKED`；不得把 Linux、WSL、mock、源代码检查或其他操作系统表现外推为 Windows 10 结论。

## 共同范围外

- 不实现用户方案、下一步行动、执行会话、任务调度规则或任何正式领域状态；
- 不接入 SQLite、PydanticAI、真实 LLM、邮件、微信、QQ、Web/PWA 或移动端；
- 不设计正式产品 UI，不实现安装器、自动更新或发布包；
- 不把任务定时与调度、干预规则、通知业务选择或上下文权威状态移入 Wails；机械性进程守护不属于这些领域职责；
- 不修改产品范围、`CONTEXT.md` 或现有 ADR；发现冲突只记录并返回产品治理主线程；
- 不因为阶段 A 完成、代码可以交叉编译或自动测试通过，就宣称 Windows 桌面能力已经验证。

## 退出条件

- 阶段 A 达到 `READY_FOR_WINDOWS` 后，技术 session 必须暂停，不得伪造或猜测阶段 B 结果；
- 阶段 A 无法完成必要准备时，以 `BLOCKED` 退出并记录原因；
- 阶段 B 的所有验证问题已经得到带证据的 `PASS / FAIL / BLOCKED`；或
- 同一 Windows 能力完成两个有依据的最小实现尝试后仍失败，停止继续调试并记录最小复现；或
- 无法取得 Windows 10 22H2 x64、交互式桌面、WebView2 或所需通知/开机启动权限，以 `BLOCKED` 退出；或
- 发现继续验证必须把领域状态、领域调度、干预规则或 LLM 移入 Wails，立即停止并报告 ADR 冲突。

不要为了得到 `PASS` 扩大任务范围或开始实现正式产品功能。

## 新对话完整 Prompt

```text
你正在 ADHD-Support-System 仓库中执行独立 technical spike：V-01 Windows/Wails 薄桌面宿主两阶段验证。

身份与环境边界：
- 当前 session 是技术验证 session，不是产品治理主线程，也不继承产品治理角色；
- 当前 session 运行在远程 Linux 环境，不能直接操作 Windows 桌面；
- 用户有一台 Windows 10 22H2 x64 PC，可以按你生成的有限步骤执行验证并回传证据；
- 只生产可复现的技术证据和最小验证代码；
- 不得修改产品范围、领域模型或已有 ADR；发现冲突时记录证据并返回主线程。

开始条件：
- 确认包含两阶段验证计划的治理 PR 已合并，且最新 main 存在 docs/spikes/plans/wails-v3-windows-thin-host.md；
- 如果该文档尚未进入 main，停止并请用户先完成治理 PR 的审查与合并，不创建 stacked spike PR；
- 同步最新 main，从 main 创建独立分支 agent/spike-wails-v3-windows-thin-host，Draft PR 以 main 为 base。

开始前完整阅读：
- 仓库根目录 AGENTS.md、CONTEXT.md；
- docs/agents/product-governance-workflow.md；
- docs/product/mvp-build-readiness.md；
- docs/spikes/plans/wails-v3-windows-thin-host.md；
- ADR-0008、ADR-0009、ADR-0010、ADR-0011；
- Issue #11（https://github.com/Annzival/ADHD-Support-System/issues/11）的正文与全部评论。

采用同一个技术 session、分支、Issue 和 Draft PR 完成两个阶段。

阶段 A：Linux 准备
1. 锁定并记录 Windows、Wails、Go、WebView2 和 Python 的确切候选版本。
2. 实现最小 Wails 宿主、静态前端和 Python 智能体核心测试替身。
3. 生成 Windows 环境检查、构建、逐项验证、证据收集和清理所需的 PowerShell 脚本。
4. 生成不要求用户自行发明步骤的人工观察清单。
5. 在 Linux 上完成所有与平台无关的检查；不得用 mock 或交叉编译结果代替 Windows 实机证据。
6. 创建中文结果模板 docs/spikes/results/wails-v3-windows-thin-host.md。
7. checkpoint commit、push 并创建 Draft PR；更新 Issue #11，记录待执行 commit SHA。
8. 按计划中的阶段 A 验收条件判断 READY_FOR_WINDOWS 或 BLOCKED。
9. 如果 READY_FOR_WINDOWS，向用户给出准确、有限的 Windows 执行步骤及证据返回方式，然后暂停等待；不得继续推测阶段 B 结果。

Windows 人工检查点：
- 用户从指定 commit 获取代码，在 Windows 10 22H2 x64 的交互式桌面会话运行脚本和观察清单；
- 用户不修改或推送分支，只把证据包、截图、录屏或必要日志返回本 session；
- 等待期间不要修改会影响复现的验证代码。确需修改时，先推送新 checkpoint，并明确要求重跑受影响项目。

阶段 B：Windows 实机证据整理
1. 核对证据对应的 Windows 版本、工具版本和 commit SHA。
2. 对托盘、置顶小窗、开机启动、可交互通知、通知上下文返回和 Python 进程守护逐项给出 PASS、FAIL 或 BLOCKED。
3. 进程守护必须包含单次异常重启、连续异常、退避、重启上限、明确退出和孤儿进程检查。
4. 证据不完整时标记 BLOCKED，不根据 Linux、WSL、mock、源码或其他操作系统表现外推。
5. FAIL 时记录根因、影响和至少一条不破坏智能体核心边界的替代路线；不要在本任务中实现第二套宿主。
6. 完成结果文档，提交并推送同一个 Draft PR，更新 Issue #11。

共同范围外、逐项验收和退出条件以 docs/spikes/plans/wails-v3-windows-thin-host.md 为准，不得自行扩张。

最终必须回报：
- 阶段 A 状态及 checkpoint；
- 阶段 B 总体 PASS/FAIL/BLOCKED 和逐项证据；
- 失败根因、替代路线和未决风险；
- 是否发现与产品范围、领域模型或 ADR 的冲突；
- Draft PR 和 Issue #11 链接。

结束后不要自行宣布 Wails 正式采用，也不要开始 implementation。由产品治理主线程根据证据更新 MVP 构建就绪门槛。
```
