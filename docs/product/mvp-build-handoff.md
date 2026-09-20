# 第一个 MVP 构建交接报告

## 判断与授权边界

结论：**MVP 已达到可以开始构建的状态。**

2026-09-20，B-04 文档 checkpoint `39f597d` 已完成独立 Standards / Spec 双轴审查，两轴均无 findings；当前产品治理线程结合已接纳技术证据确认六项门槛全部满足，停止产品 grilling。本报告与验收规格由 [PR #30](https://github.com/Annzival/ADHD-Support-System/pull/30) 发布，仍需用户人工审查和合并后，执行 session 才能从最新 main 启动。

构建就绪只表示已有最低充分信息，可以开始第一个可验证闭环的实现；不表示所有路线图需求都已确定、软件可分发或 dogfooding 已可启动。Agent 不在产品治理线程实现代码、不自动创建执行 session，也不标记 PR Ready 或合并。

## 支撑证据

| 门槛 | 决策或验证依据 | 使用限制 |
| --- | --- | --- |
| 1. 假设与范围 | [构建就绪文档](mvp-build-readiness.md) B-01；Issue #10 | 单用户可行性信号，不是医疗、因果或群体结论 |
| 2. 两个必要切片 | 同文档 B-02；V-05 [Issue #7](https://github.com/Annzival/ADHD-Support-System/issues/7)、[Draft PR #27](https://github.com/Annzival/ADHD-Support-System/pull/27)，checkpoint `7c2c46c` | 低保真载体方案已接纳；prototype 源代码仍不合并，不证明真实 Windows 集成 |
| 3. 领域模型 | 已合并 [PR #28](https://github.com/Annzival/ADHD-Support-System/pull/28)，merge `930746d`；[模型](mvp-domain-model.md)、[转换矩阵](mvp-domain-transitions.md)、ADR-0043～0056 | 不是数据库 schema 或现有业务代码 |
| 4. 验收标准 | [B-04 Given–When–Then 场景](mvp-acceptance-scenarios.md) | 当前是规格；运行结果由后续 implementation 提供 |
| 5. 高风险技术 | [V-01](../spikes/results/wails-v3-windows-thin-host.md)、[V-01R](../spikes/results/wails-v3-windows-overlay-close-recovery.md)，Issue #11/#14、PR #13/#15 | 原 V-01 FAIL，由关闭恢复修复及实机复验补足组合 PASS；不隐藏原失败 |
| 5. 通信与恢复 | [V-02](../spikes/results/localhost-core-transport.md)，Issue #17 / PR #20，`73345e0`；[V-03](../spikes/results/sqlite-restart-recovery.md)，Issue #18 / PR #24，Windows `1ca7d92` | `2efbb3c` 是后续 bootstrap 超时修复，不是新的 Windows 成功锚点；限定实测环境 |
| 6. 未决归档 | 构建就绪文档四类清单与[多 session 编排](mvp-session-orchestration.md) | 低成本、可逆实现选择不重新阻塞产品 grilling |

实施者必须读取结果文档的锁定 Wails、Go、Python、WebView2 和 Windows 版本，不能将 PASS 外推至自行升级的环境。

## 准确范围与成功判据

目标是已有学习或求职方案、但难以按计划启动的成人 ADHD 用户；第一轮仅作者本人在可见、可操作的 Windows 10 22H2 x64 PC 上使用。

核心假设：通过须确认且可追溯的方案导入建立权威安排后，状态持久的 PC Agent 能否在约定时间呈现下一步行动和低成本选择，支持用户在计划窗口内明确进入执行会话，同时不造成不可接受的压力或自主感下降。

范围内：

- 文本／Markdown 原文保存、PydanticAI 草案生成、可追溯审阅、逐项确认首项行动及时间、确定性最终启用；
- 本机 Core、SQLite 权威状态和事件、确定性调度、localhost HTTP/WebSocket、运行期令牌和端口发现；
- Wails 可替换薄宿主、嵌入式桌面前端、托盘、置顶小窗、开机启动、交互通知及进程守护；前端仍只通过 Core API；
- 开始干预、已开始／已完成校正、改期、今天不做、检查点续行、完成／暂停及可跳过收尾；
- 期限、过期操作拒绝、重复提交、重启恢复、单一前台和唯一活动会话、恢复包与显式恢复切换；
- 供应商独立状态、必要的执行事实与更正，以及低负担的首轮观察记录。

明确不做：策略性学习／求职方案制定、完整方案调整或通用可行性分析、LLM 阻碍支持、准备提示、日终复盘及补记、剩余精力扩展、自动追加／批量顺延、历史执行补记、多日再触达、邮件／微信／QQ 集成、body doubling、Web/PWA、手机、多用户、多设备同步、远程部署／公网、桌面活动推断、跨平台承诺、公开分发和医疗效果验证。

首要成功行为是会话和首次检查点已经原子建立，不是点击按钮或“AI 看起来智能”。按合格机会记录进入比例、进入延迟、主观启动帮助、压力与自主感以及闭环能否重复运行；即时／延后口径与观察停止规则见 OBS-01～04。

## 黄金路径与必要异常

设置：保存原文 → Agent 草案 → 审阅和逐项确认 → 确定性最终确认 → 原子发布方案版本与首项安排。

执行：已确认安排到点 → 成功送达 → 立即开始并具备确认时长 → 会话与首次检查点 → 完成报告 → 完成或跳过收尾 → 保存最小证据、释放活动位置。

必要异常不另扩范围：模型不可用／来源变更／关键缺口／启用失败；已开始、已完成、改期、今天不做；续行、暂停、收尾跳过或到期；无回应至过期保持未知；Core／PC 重启恢复；通知过期、版本冲突、重复提交、保存失败；恢复包接续、旧版本选择、显式切换。逐项正确性由验收场景而非实现者自由补充。

## 核心对象与状态

| 对象 | 权威及关键转换 |
| --- | --- |
| 原文／草案 | 持久但非权威；LLM 可整理草案，不能启用 |
| 方案／版本／行动 | 用户最终确认发布不可变版本；行动固定引用确切版本；新版本不改旧历史 |
| 执行安排 | 表达何时尝试；改期结束旧安排并建后继，今天不做只结束当前安排 |
| 开始干预／送达尝试 | 每安排最多一个逻辑干预，首次及一次较弱跟进分开记录；过期不补发 |
| 会话／检查点 | 执行中 → 等待收尾 → 已结束；两种活动状态共用唯一位置；续行生成同会话的后继检查点 |
| 未知退出 | 核对到期或明确恢复切换可结束应用跟踪；不推出现实完成／暂停／失败 |
| 证据／更正 | 明确事实固化、追加更正；事件日志不自动等同结果证据 |
| 恢复包／恢复干预 | 包一次性建立关联新会话；干预保存来源与版本；切换旧、新会话是一个事务 |

所有领域写入由 Core 执行。用户操作和确定性期限触发不同事实，必须分开记录；状态与成功事件及命令结果同事务保存，不做完整事件溯源。LLM、桌面壳和供应商对话不能直接修改上述状态，更换供应商不迁移或丢弃权威记录。

## 推荐构建顺序及完成条件

下面划分的是 implementation 阶段，不是新 spike。第一个切片必须贯穿桌面 → 本机 API → Core → SQLite → 调度／桌面显示 → 用户完成 → 持久收尾；不能先交付一堆没有闭环的基础模块。

| 阶段 | 可交付范围与完成条件 | 验收范围 | 建议验收入口（待实现） |
| --- | --- | --- | --- |
| I-01 首个 PC 垂直切片 | 在隔离开发数据中使用显式确认来源的预置 P/A/a，贯通到点、立即开始、首次检查点、完成、跳过收尾、持久结束；状态／事件原子和唯一会话从首日成立；Windows 实际能操作 | EX-01、02；SES-02 的完成分支；AT-01～03 的本阶段转换；Core 重启不丢状态；DESK-03、04 的本阶段通知 | `python -m pytest tests/acceptance/test_execution_golden_path.py`；`powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage I01` |
| I-02 确定性分支与恢复 | 补全开始分支、续行、暂停包、期限、收尾、旧版本引用和事实更正、R09 切换；生产通知与五项宿主能力回归 | 全部 EX、SES、REC；AT-01～03；DESK-01～05 | `python -m pytest tests/acceptance/test_execution_branches.py tests/acceptance/test_recovery.py tests/acceptance/test_atomicity.py`；同一 Windows 脚本 `-Stage I02` |
| I-03 完整设置与模型边界 | 用户从真实文本／Markdown 在审阅工作区完成导入和启用；PydanticAI 模型调用只生成草案；两个供应商配置切换验收、模型不可用及状态保留 | 全部 SET、AT-04～05；用真实导入结果重新跑 EX-01 | `python -m pytest tests/acceptance/test_plan_setup.py tests/acceptance/test_provider_boundary.py`；`powershell -NoProfile -File scripts/acceptance/model-integration.ps1` |
| I-04 集成与观察准入 | 在锁定 Windows 上验证正式构建的全部必要场景，完成脱敏证据索引、退出控制和观察协议走查；用户决定是否开始观察 | 所有场景与 OBS-01～04；所有 FAIL／BLOCKED 均有处理结论，未通过必要功能不得开始正式观察 | `python -m pytest tests/acceptance`；`powershell -NoProfile -File scripts/acceptance/windows-smoke.ps1 -Stage Full`；按 OBS 手动走查并记录 |

这些命令是建议的交付接口，**当前测试文件和脚本尚不存在，不能立即运行或声称通过**。执行 session 在所负责阶段创建相应入口，或选择等价测试框架后在仓库运行说明中给出实际命令与场景 ID 映射；无需为命令命名再做产品决策。PowerShell 步骤必须提供给 Windows PC 的操作者，Linux 执行成功不能替代它。真实模型调用需测试凭据与成本控制，不能在本线程代跑。

I-01 的预置数据不是导入功能，也不能进入正式观察；I-03 是 dogfooding 前的硬性依赖。I-02、I-03 是否在接口稳定后并行是实施协调选择，不改变全部必须完成的结果。

每阶段遇到规格冲突或必须改变范围／ADR时，保存证据并返回当前产品治理线程；不以技术实现偏好覆盖产品决定。Linux 准备完成但缺 Windows 执行时标记“等待 Windows 验收”，保留 checkpoint，不判整体 PASS。

## 尚存但不阻塞开始构建的风险

- Wails 及 Windows 证据限定版本和单台机器；生产集成仍须回归，替换／升级宿主不能偷偷改变 Core 边界。
- SQLite 已有合成事务及受控重启证据，不覆盖异常断电、损坏或备份恢复；不把这些限制写成可靠性保证。
- LLM 草案的真实输出仍须实施期验证；准确性靠来源区分、缺口表达、用户确认及失败不启用保护，不保证模型质量。
- 程序不能抵御同权限恶意本地进程的所有行为；localhost 令牌不等于完整主机安全边界。
- 唯一活动会话、版本校验和跨对象事务仍有实现风险；自动化场景必须测试竞态与失败，不靠 UI 禁用代替 Core 约束。
- 第一轮观察样本仅作者本人；不能推广临床或人群效果。可随时停止，不为收集数据增加工作负担。

可以等实现反馈再决定：前端框架／组件和布局、数据库访问库与索引、API 命名、测试框架和模块拆分、诊断导出、安装包与自动更新、模型默认值、非关键文案。开源许可证须在正式对外宣称可复用发布前明确，但不阻塞本地闭环编码。未来能力继续按构建就绪文档“MVP 后”归档。

## I-01 独立执行任务 Prompt

以下 Prompt 用于用户另开的独立 implementation session，任务跟踪为 [Issue #31](https://github.com/Annzival/ADHD-Support-System/issues/31)，当前未启动；使用前必须先合并 PR #30。当前主线程不启动编码，也不因文件存在赋予新 session 产品治理身份。

```text
你在 ADHD-Support-System 仓库执行 I-01：首个 PC 确定性执行闭环的 implementation 任务。

身份与范围：
- 你是独立技术执行 session，不是产品治理主线程，不继承该角色。
- 只交付 I-01；发现范围、领域模型、ADR 或验收冲突，记录到任务 Issue 并回传委托者／当前产品治理线程，不自行改写产品规则。
- 不执行 I-02～I-04，不开始正式 dogfooding，不实现未来功能。

开始前：
1. 只读检查工作树、现有任务 Issue / Draft PR，保护用户修改。
2. 完整阅读 AGENTS.md、CONTEXT.md、docs/agents/grilling-git-workflow.md、docs/product/mvp-build-readiness.md、mvp-domain-model.md、mvp-domain-transitions.md、mvp-acceptance-scenarios.md 和 mvp-build-handoff.md（后五份均在 docs/product/），以及相关 ADR-0004、0008、0043～0056。
3. 阅读 docs/spikes/results/ 中 Wails 薄宿主、关闭恢复、localhost 通信及 SQLite 重启的四份结果文档，确认锁定环境和限制，不把 spike 源码直接当成已验收的正式实现。
4. 核实 PR #30 已人工合并；从最新 main 建立 agent/implement-mvp-first-slice 独立分支。若未合并、文件缺失或存在未知冲突，停止并说明，不从未合并文档分支借用起点。
5. 读取并沿用 I-01 的 Issue #31（https://github.com/Annzival/ADHD-Support-System/issues/31），以及 Issue #10 的构建就绪结论；已有本任务分支或 PR 则沿用，避免重复创建。

交付问题：
在 Windows 10 22H2 x64，能否用真实桌面客户端通过 localhost API 驱动 Python Core，在预置的确认方案上贯通：到点 → 开始干预 → 立即开始／必要时确认时长 → 会话与首次检查点 → 完成 → 完成或跳过收尾 → SQLite 持久结束？重试、保存失败、Core 重启时是否仍保持一致？

范围内：
- 最小正式 Core、SQLite、权威状态／事件／命令结果同事务、计划触发和本阶段确定性操作。
- Wails 可替换薄宿主与嵌入式前端，通过 HTTP/WebSocket 连接 Core，端口发现、运行期令牌和真实通知上下文。
- 可控制时钟、隔离测试数据与自动化测试；预置方案仅用于开发，不作为面向用户的导入替代。
- 可逆实现细节可自主选择并记录；不在执行状态模型上另造规则。
- Linux 完成实现与自动检查；另提供 Windows 操作者可复制的实机步骤、预期结果和脱敏证据记录方式。

范围外：
- 不调用 LLM 或实现导入工作区；这由 I-03 完成；核心接口须保留供应商独立边界。
- 不实现完整异常／恢复集合以外扩 I-01；对尚未交付的操作明确不可用，不伪造成功，也不能让测试夹具被误认为完整 MVP。
- 不做服务器、手机、Web/PWA、同步、公开分发、桌面活动采集、邮件、方案自动调整或 AI 陪伴。
- Wails 不直接访问 SQLite、不调度领域规则、不调用 LLM。

验收条件：
- EX-01、EX-02，SES-02 的完成分支；AT-01～03 中本阶段的开始、完成／收尾转换；REC 中 Core 重启保留同一会话／已提交状态的适用部分；DESK-03、04 本阶段通信与通知上下文。
- 方案夹具建立方式可追溯且只作用于隔离开发数据；会话与检查点原子建立，等待收尾占唯一位置，收尾后证据和结束状态原子保存。
- 提供实际可运行的自动测试及 Windows 验收命令，并将场景 ID 映射到测试／步骤。自动测试成功不代替 Windows 实测。
- 只有所列自动与 Windows 验收均有证据才可报告 I-01 PASS；必须声明 I-01 PASS 不是完整 MVP 或 dogfooding 准入。

退出条件：
- 本阶段范围通过后停止，不自动进入 I-02。
- 遇到领域歧义、必须升级已验证环境或扩大权限／范围，保留证据并回传，不在此自作产品决定。
- 缺 Windows 桌面访问或用户尚未执行步骤时，保存 checkpoint，返回等待 Windows 验收；不要无限等待或用 Linux 结果替代。
- 任一调试路径连续三次没有新增证据，整理复现和尝试记录，回传委托者后再决定是否另开 debugging 任务，不无限尝试。

交付物及发布：
- 产品代码、自动测试、运行说明、Windows 手动验收步骤。
- docs/implementation/results/mvp-first-vertical-slice.md：环境、commit、方法、场景结果、脱敏证据位置、限制与未决项。
- 任务 Issue 与独立 Draft PR 相互链接，checkpoint commit 后 push；PR 范围完成时提醒用户审查／merge，不自行 Ready 或合并。
- 不提交密钥、个人方案正文或未脱敏日志；多行 GitHub 正文用文件发布并读回检查换行。
- 最终回传：PASS / FAIL / BLOCKED 或等待 Windows 验收，场景证据、运行命令、实际限制、ADR 冲突及需要产品治理判断的问题。
```
