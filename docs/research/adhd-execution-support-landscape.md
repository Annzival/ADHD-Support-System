# ADHD 主动执行支持应用：循证原则、产品与技术形态调研

> 调研日期：2026-08-09
>
> 状态：用于后续用户访谈和产品假设设计的研究底稿，不是医疗建议，也不是已经作出的产品决策。

## 结论摘要

这类产品最值得解决的，不是“再做一张更聪明的待办清单”，而是待办清单通常没有覆盖的几个状态转换：**从知道要做到真正开始、偏离后回到任务、中断后保存现场并重新进入、未完成后调整计划而不是积累羞耻感**。

最稳固的证据支持“外化执行功能”：环境调整、书面提示、较短专注段与活动休息、时间管理/组织/计划技能、结构化支持和持续跟进。NICE 对成人 ADHD 建议综合且共同制定的计划；当非药物干预适用时，至少包含 ADHD 聚焦的结构化心理支持和定期跟进。它列举的环境调整包括减少干扰、缩短专注时段并加入活动休息、把口头要求转成书面说明。[NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations) 成人 ADHD 的元认知治疗随机试验也直接训练时间管理、组织与计划；88 名临床成人中，该干预优于支持性心理治疗。[Solanto et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20231319/) 另一项随机试验支持成人 ADHD 专门化 CBT 的价值，但这些研究评估的是成套心理干预，不能直接证明某个 App 功能本身有效。[Safren et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20736471/)

“主动”不能等同于“多发提醒”。一项针对 109 名成人 ADHD 用户的微随机研究，在用户未完成互联网干预模块后随机发送或不发送 SMS；提醒没有改善模块完成、登录次数或应对策略练习，只在部分周次加快登录，并使平均停留时间略增。[Nordby et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9149073/) 因此更有价值的主动支持假设是：**识别当前阻塞状态，给出低成本选择，更新计划，并在用户不需要时停止**，而不是提高通知频率。

代表性产品已经分别把任务拆解、视觉时间、共同专注、当日执行和心理教育做好，但很少把它们连成一个有持久状态的“启动—执行—中断—恢复—复盘”闭环。这个闭环是本项目可验证的空白；它仍是基于现有证据与产品比较得出的**设计推断**，不是已证实的疗效结论。

若把项目同时作为开源作品集，最有辨识度的并非功能数量，而是能否公开展示：问题定义、范围取舍、事件/状态模型、隐私与安全边界、AI 输出评估、可复现实验、issue/ADR/里程碑、用户研究如何改变设计。这样能够同时证明产品管理和与 AI Agent 协作，而不只是“调用了一个大模型 API”。

## 1. 研究问题、方法与证据等级

本轮研究回答五个问题：

1. 成人 ADHD 的启动、持续专注、拖延/逃避可由哪些有依据的执行支持原则承接？
2. 代表性商业产品如何设计任务拆解、主动提醒、共同专注、当日执行和复盘？
3. 代表性开源项目提供了哪些可复用的产品/工程思路？
4. Agent、skill、plugin 和 automation 分别适合承担什么？
5. 这些事实对候选 MVP 和开源作品集有什么启示？

来源优先级为：临床指南和原始研究；产品官方帮助/官方功能页；开源仓库 README、许可证和 GitHub API；框架官方文档。商业产品自述只能证明“产品如何设计或宣称”，不能证明有效性。调研选择少量代表深入比较，不是市场穷举。

本文用以下标签区分证据：

- **指南/随机研究**：可支持临床或行为干预方向，但未必能拆解到单个功能。
- **观察/可用性研究**：能说明关联、接受度或使用行为，不能确立因果疗效。
- **定性/早期研究**：适合发现需求和形成假设，不能估计效果大小。
- **产品事实**：来自厂商一手资料，只说明功能与交互。
- **设计推断**：本调研基于上述材料提出的待验证产品假设。

## 2. 循证与临床执行支持原则

### 2.1 证据较稳固的方向

| 原则 | 来源支持的事实 | 对数字产品的设计推断 |
| --- | --- | --- |
| 共同制定、持续调整 | NICE 要求综合、整体、共同制定的计划，纳入日常功能（含睡眠）、个人目标、保护因素、偏好与顾虑，并定期重新讨论参与方式；成人非药物支持至少应结构化、聚焦 ADHD 并有定期跟进。[NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations) | 督促强度、安静时段、是否需要他人参与、提醒渠道应由用户配置并可随时改变；系统应保存决策理由，而非把一次设置永久化。 |
| 外化环境和记忆 | NICE 的环境调整示例包括降低噪声/干扰、较短专注段与活动休息、用书面说明强化口头要求。[NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations) 一项小型研究（29 名 ADHD 成人、24 名对照）发现 ADHD 组日常前瞻记忆较弱，日常前瞻记忆表现与拖延相关；样本较小，不能把中介结果当作因果定论。[Altgassen et al., 2019](https://pubmed.ncbi.nlm.nih.gov/30927231/) | 把“记住下一步”交给系统：当前唯一下一步行动、可见计时、到点提示、结束时的恢复包，比要求用户在脑中维持项目上下文更匹配证据。 |
| 训练组织、计划与时间管理 | 成人 ADHD 元认知治疗随机试验训练时间管理、组织和计划并优于支持性心理治疗。[Solanto et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20231319/) ADHD 专门化 CBT 随机试验也显示了症状改善；它是成套治疗而非单功能测试。[Safren et al., 2010](https://pubmed.ncbi.nlm.nih.gov/20736471/) | 拆解不应只生成更多子任务；还应让用户选择下一步、估时、执行、对比实际用时，并据此校准后续计划。 |
| 以功能和赋能为目标 | 澳大利亚循证指南认为成人应获得 ADHD 专门化的认知行为干预，并强调 strengths-based、hope 和 personal empowerment；它也指出这类干预更主要针对功能、痛苦和行为改变，而非直接消除核心症状。[AADPA guideline](https://adhdguideline.aadpa.com.au/non-pharmacological/cognitive-behavioural-interventions/cognitive-behaviour-interventions/) | 产品语言宜聚焦“让这一步更可做”“修改环境/计划”，避免把未完成解释成品格失败，也避免承诺治疗 ADHD。 |
| 规律跟进，但不是固定轰炸 | NICE 支持定期跟进。[NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations) 但 ADHD 成人 SMS 微随机研究没有发现额外提醒改善模块完成、登录数或策略练习。[Nordby et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9149073/) | 跟进应和任务状态、用户回应及阻塞原因联动；每次提醒都应提供可执行分支，如“现在做 2 分钟 / 改到具体时间 / 缩小一步 / 今天放弃并记录原因”。 |

### 2.2 仍属早期或证据不足的方向

**Body doubling / 共同专注。** Focusmate 等服务把预先预约、开场声明目标、安静共事、结尾汇报组合在一起。[Focusmate 官方说明](https://www.focusmate.com/about/) 这些交互可形成明确的社会承诺，但产品内部调查和营销页不能替代独立临床证据。2026 年一篇 CHI workshop 路线图称 ADHD body doubling 的实证研究仍很少，并明确呼吁更多有效性研究。[Tan et al., 2026](https://arxiv.org/abs/2605.07851) 因此它适合做可选模块和 A/B/单人交叉实验，不宜在项目文案中称作已被充分证明的 ADHD 治疗。

**关系和情感支架。** 一篇已标注“accepted to CSCW 2026”的预印本报告了 22 次半结构访谈，以及另外 20 人对 13 个推测性 AI 概念的 speed-dating 研究；作者提出任务管理可能是关系性、情感性共同建构的，并建议支持非线性注意节奏、共同调节和情绪适配。[Chen et al., 2026](https://arxiv.org/abs/2603.17258) 这是很有针对性的近期定性设计证据，但参与者规模小、包含强自我认同而非全部临床诊断、概念并非上线产品，不能作为疗效证据。

**App 疗效。** Inflow 的 7 周开放研究主要验证可用性与可行性；240 人参与基线，只有 95 人完成 7 周可用性测量，症状变化是无对照自评。作者明确表示仍需 RCT 判断效果是否超过非特异因素，且两名作者是 Inflow 联合创始人。[Knouse et al., 2022](https://pubmed.ncbi.nlm.nih.gov/36812621/) 因而“基于 CBT”与“这个 App 已证明有效”必须分开表述。

## 3. 代表性产品：它们真正优化了哪个环节

| 产品 | 一手资料确认的核心设计 | 优点 | 空白或风险 |
| --- | --- | --- | --- |
| [Focusmate](https://www.focusmate.com/about/) | 预约固定时段、匹配一名伙伴、视频共同工作；开场声明任务。官方说明强调预先承诺和问责。[使用场景](https://www.focusmate.com/use-cases/) | 把“开始”变成对另一个人的具体约定；仪式简单，能快速进入执行。 | 依赖预约、摄像头和陌生人匹配；对项目拆解、错过后的恢复、跨会话上下文支持弱；有效性主张主要来自厂商调查。 |
| [Tiimo](https://www.tiimoapp.com/resource-hub/how-to-start-planning) | 视觉日程、AI co-planner 语音/文字拆步、视觉 Focus timer、widget/锁屏、可选 morning/motivation 提醒、每日 Review Today 与未完成任务改期；另有每周复盘提醒。[通知帮助](https://www.tiimoapp.com/faq/notifications) | 把计划持续放在视野内，覆盖捕获—安排—执行—日终改期；允许只开一两类提醒。 | 官方说明称过去的每日 check-in 不可回看，限制长期模式学习；提醒仍以预设时点为主，对“为什么没开始”和恢复策略支持有限。 |
| [Goblin Tools](https://goblin.tools/About) | Magic ToDo 按“spiciness”提示拆解粒度，可继续拆子任务、估时和导出；Taskmaster 一次呈现一项并按估时计时。[Magic ToDo](https://goblin.tools/ToDo) [Taskmaster](https://goblin.tools/Taskmaster) | 单用途、低学习成本；把模糊任务快速变成下一步，“困难度”输入比要求写完整提示更轻。 | 官方明确说模型输出只是猜测；缺少长期跟进、行为反馈和社会支持。过度拆解也可能制造更长清单。未找到官方开源仓库，不能把免费网页等同于开源。 |
| [Llama Life](https://llamalife.co/features) | 面向“今天”的任务计时器、总结束时间、AI 拆解、随机选一项、间隔轻提示、实际超时、preset、完成/用时报告。 | 强调一次做一项和让时间可见；随机任务可减少选项瘫痪；实际用时能支持估时校准。 | 用户仍需主动打开并开始；报告较轻，未显示跨会话阻塞原因、恢复现场或社会跟进。 |
| [Inflow](https://www.getinflow.io/how-it-works) | CBT 原则的短课/练习、社区、专家活动、教练；官方 2025 功能说明还列出 AI 支持、每日共同工作与 drop-in focus rooms。[官方功能说明](https://www.getinflow.io/post/inflow-adhd-management-app) | 把心理教育、人工支持、同伴共同专注组合在一个 ADHD 专门环境中。 | 宽度大、使用成本可能高；主要是教育/支持项目，不是工作任务状态机。现有同行评审证据是开放可用性研究，不是疗效 RCT。[研究](https://pubmed.ncbi.nlm.nih.gov/36812621/) |

### 3.1 横向观察

**产品事实：** 任务拆解、计时、提醒、body doubling、日终改期、心理教育和社区均已有成熟实现，单独复制任一功能都很难形成作品集辨识度。

**设计推断：** 仍有价值的组合空白是一个“恢复优先”的持久执行循环：

```text
捕获 → 澄清下一步行动 → 约定开始 → 正在执行
                         ↓ 未开始/偏离/中断
                    识别阻塞 → 缩小/改期/求助/放弃
                         ↓
                  保存恢复包 → 再启动 → 简短复盘
```

关键区别不在于 AI 更会鼓励，而在于系统记得：用户承诺了什么、实际停在哪、哪种支持被接受/忽略、何时应该停止打扰。

## 4. 代表性开源项目

活跃性是截至 2026-08-09 的仓库 `pushed_at` 快照，只能证明近期有提交，不能保证长期维护质量。

| 项目 | 可借鉴能力 | 许可证与活跃性 | 对本项目的提醒 |
| --- | --- | --- | --- |
| [Super Productivity](https://github.com/super-productivity/super-productivity) | 子任务、timeboxing/计时、休息提醒、anti-procrastination、Pomodoro、个人指标、GitHub/Jira 等集成；无需注册且声明不收集数据。[README](https://github.com/super-productivity/super-productivity#features) | [MIT](https://github.com/super-productivity/super-productivity/blob/master/LICENSE)；API 显示最后 push 为 2026-08-08。[GitHub API](https://api.github.com/repos/super-productivity/super-productivity) | 展示了 local-first、执行计时与工程任务集成的成熟基线；也说明功能过多会提高首次设置与导航成本。 |
| [Habitica](https://github.com/HabitRPG/habitica) | 用 RPG 奖励、HP、金币、组队和挑战把习惯/任务社会化。 | 代码为 GPLv3，资产/内容另有许可，复用前必须逐项检查。[LICENSE](https://github.com/HabitRPG/habitica/blob/develop/LICENSE)；最后 push 为 2026-08-07，但 README 宣布自 2026-08-04 暂停接收代码 PR，并禁止提交 AI 生成代码。[README](https://github.com/HabitRPG/habitica) | 游戏化与社交能制造即时反馈；“失败掉血/连续性”也可能放大惩罚感。其当前贡献政策使它不适合作为展示 AI 协作的上游贡献目标。 |
| [ActivityWatch](https://github.com/ActivityWatch/activitywatch) | 本地、自动记录活动窗口/AFK/浏览器/编辑器，架构由 watcher 心跳、server 与 web UI 组成。[README](https://github.com/ActivityWatch/activitywatch) | [MPL-2.0](https://github.com/ActivityWatch/activitywatch/blob/master/LICENSE.txt)；最后 push 为 2026-08-06。[GitHub API](https://api.github.com/repos/ActivityWatch/activitywatch) | 被动数据可减少手工复盘，并估算“实际发生了什么”；但窗口标题可能含高度敏感信息，原始日志不应默认上传给 LLM。 |
| [Leantime](https://github.com/Leantime/leantime) | 面向非项目经理、声明考虑 ADHD/自闭/阅读障碍；把目标、项目规划、任务、计时、回顾、文档、API/plugin 组合起来。[README](https://github.com/Leantime/leantime) | [AGPL-3.0](https://github.com/Leantime/leantime/blob/master/LICENSE)；最后 push 为 2026-08-05。[GitHub API](https://api.github.com/repos/Leantime/leantime) | 适合参考“目标—里程碑—执行—回顾”的项目层模型；对单人启动支持而言过重。AGPL 对网络服务衍生修改的分发义务与 MIT 不同，需要单独做许可证决策。 |

**设计推断：** 开源侧已分别覆盖任务/计时、游戏化、被动追踪和完整项目管理，但本轮代表样本中没有一个同时把 ADHD 专门的关系/情感支架与可恢复 Agent 工作流做成小而清晰的核心。这是候选定位，不是“市场上绝对不存在”的证明。

## 5. AI Agent、skill、plugin 与 automation 应如何分工

### 5.1 不要把系统等同于聊天机器人

候选架构可以分为七层：

1. **确定性领域状态**：任务、下一步行动、承诺时间、会话状态、阻塞原因、恢复包、复盘；数据库是事实来源，LLM 不是。
2. **事件/调度器**：到点、错过开始、计时结束、长时间无响应、日终等事件；它决定何时唤醒工作流。
3. **Agent 编排**：根据当前状态选择“拆解、缩小、改期、进入共同专注、复盘”等受限动作。
4. **Skill**：保存可复用的访谈/拆解/复盘协议、语气边界、输出 schema 和示例；适合快速迭代工作流，不负责可靠定时和数据库持久化。OpenAI 当前把 skill 定义为包含说明、资源和可选脚本的可复用工作流。[Skills 文档](https://learn.chatgpt.com/docs/build-skills)
5. **Plugin / MCP tools**：当需要日历、通知、GitHub、文件等实时数据或受控写操作时再接入。OpenAI 插件文档把 skill 用于说明/资源，把 MCP server 用于实时数据、认证、受控动作或服务端代码。[Plugin use-case guide](https://developers.openai.com/plugins/plan/use-case)
6. **审批和权限**：读取计划可以自动；改日历、联系 body double、发送外部消息、删除数据等副作用应在工具边界校验或请求批准。OpenAI Agents SDK 支持暂停、持久化状态并在批准/拒绝后恢复同一次运行。[Guardrails and human review](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
7. **trace 与 eval**：记录模型调用、工具调用、guardrail 和人工接管，用固定场景检查是否误判、过度打扰、越权或生成不可执行步骤。Agents SDK 的 tracing 默认可记录上述工作流结构。[Integrations and observability](https://developers.openai.com/api/docs/guides/agents/integrations-observability)

### 5.2 状态、checkpoint、resume 比“记住聊天”更重要

OpenAI Agents SDK 当前区分应用自管历史、SDK session、Conversations API 和 `previous_response_id`；官方把 session 定位为需要持久记忆、可恢复运行和自管存储时的默认选项。[Running agents](https://developers.openai.com/api/docs/guides/agents/running-agents#choose-one-conversation-strategy) LangGraph 则把每一步状态保存为 checkpoint，以支持容错、时间旅行调试和 human-in-the-loop；其 interrupt 会保存状态并等待相同 thread id 恢复。[Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

对本项目而言，checkpoint 不只是技术容错。一次执行会话结束时的“恢复包”可以是产品对象：

```yaml
task: 修改简历项目经历
last_artifact: resume.md
last_position: 项目 2 的第二条 bullet
next_action: 打开 GitHub issue #12，提取一个可量化结果
blocker: 不知道怎样量化
restart_hint: 只找一个数字，不改句子
saved_at: 2026-08-09T16:40:00+08:00
```

这使“再启动”无需重新阅读整个聊天，也便于测试 Agent 是否给出了真正可执行的下一步。

### 5.3 automation 是触发器，不是支持策略本身

后台/定时能力已经是可用的通用基础设施。OpenAI Responses API 支持异步 background response 和轮询/取消；webhook 可在后台响应完成时通知自有服务。[Background mode](https://developers.openai.com/api/docs/guides/background) [Webhooks](https://developers.openai.com/api/docs/guides/webhooks) Codex/ChatGPT 的 scheduled task 也能在未来或循环运行，并可回到同一 chat 保留上下文。[Scheduled tasks](https://learn.chatgpt.com/docs/automations)

但这些能力只回答“何时运行”，不回答“用户此刻需要什么”。领域层仍要定义：最多提醒几次、什么算错过、什么状态停止追问、quiet hours、连续忽略后如何降级、何时只记录不干预。

### 5.4 技术候选的取舍，不在本轮替用户决定

| 形态 | 最适合验证 | 局限 |
| --- | --- | --- |
| 单个 skill | 拆解/复盘对话协议、语气和边界是否有用 | 不能单独保证定时、持久状态、跨设备通知；宿主能力不同。 |
| skills-only plugin | 把多个窄工作流打包给其他 Agent 用户试用 | 仍依赖宿主保存数据和触发；不等于独立产品。 |
| plugin + MCP server | 接入任务库、日历、通知和受控写操作，展示工具边界 | 需要部署、认证、权限和隐私设计。 |
| 独立 Web/PWA | 完整控制状态机、通知、数据、UI 和实验指标 | 工程范围最大；移动系统后台限制需另行验证。 |
| LangGraph 等持久 Agent runtime | 快速实现 checkpoint/resume/HITL；LangGraph 为 MIT，仓库 2026-08-09 有 push。[仓库](https://github.com/langchain-ai/langgraph) | 引入框架复杂度；简单 MVP 也可用普通数据库状态机实现。 |

## 6. 候选 MVP 假设与验证方式

以下不是已选方案，而是可带入用户访谈继续缩小的三个候选垂直切片。

### 假设 A：恢复优先的主动执行循环

最小闭环只覆盖一个当天任务：捕获 → AI/人工确认一个下一步行动 → 约定开始 → 到点 check-in → 开始计时 → 中断/结束保存恢复包 → 当天一次复盘。错过时不重复同一提醒，而是给“做 2 分钟、缩小一步、改到具体时间、今天放弃并记原因”四类低成本分支。

它直接测试本调研发现的核心空白。候选指标包括：计划到实际开始的延迟、中断到再启动的延迟、无需重读即可恢复的比例、被忽略/关闭的提醒比例、用户主观压力与自主感。完成率只作为一个指标，不能成为唯一成功标准。

### 假设 B：AI 辅助的可选 body double

开场共同确认一个可观察的输出，中间默认安静，只在用户预设节点轻提示，结尾说明做到哪里并生成恢复包。可以先比较“纯计时器”“非互动环境陪伴”“少量互动 Agent”“真人共同专注”，而不是预设视频真人一定最好。相关维度可参考 2026 body doubling 路线图中的同步性、熟悉度、embodiment、互动和 mutuality。[Tan et al., 2026](https://arxiv.org/abs/2605.07851)

它的主要风险是把模拟陪伴包装成真实关系、制造依赖，或在摄像头/麦克风场景收集过量数据。

### 假设 C：只面向“今天”的单任务执行器

借鉴 Llama Life 和 Goblin Tools：导入已有清单，但界面只展示当前动作、可见时间和下一项；完成后记录实际用时，日终只处理未完成项，不建设完整项目管理器。[Llama Life](https://llamalife.co/features) [Goblin Taskmaster](https://goblin.tools/Taskmaster)

它最容易做小和做完，但“主动跟进与关系支架”的辨识度较弱，需判断是否足以回答用户的核心痛点。

### 6.1 第一轮实验不宜只看留存和 streak

候选衡量框架：

- **产出**：是否产生目标 artifact 或可验证进展，而非只记录“专注了多久”。
- **启动/恢复**：启动延迟、错过后恢复时间、中断后恢复成本。
- **估时学习**：预估与实际的偏差是否逐步缩小。
- **干预负担**：通知忽略、关闭、改 quiet hours、主动暂停支持的频率。
- **体验**：任务是否更可做、压力/羞耻是否上升、自主感是否下降。
- **可切换性**：是否能按计划结束、保存现场、去吃饭/休息/睡眠；这是面向 hyperfocus 的候选退出保护，不是已被单项 RCT 验证的治疗功能。

## 7. 风险与边界

### 7.1 医疗边界

- 不诊断 ADHD，不用聊天表现推断分型，不提供用药增减建议。NICE 明确要求 ADHD 诊断由受训的专业医疗人员基于完整临床/心理社会、发育和精神病史作出，不能只靠量表或观察数据。[NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations)
- 产品宜定位为一般执行/工作学习支持或临床照护的补充，而非替代。若宣传“诊断、治疗、缓解 ADHD”，会改变证据和监管要求；FDA 2026 general wellness guidance 将与疾病诊断、治疗、缓解无关的健康生活软件和疾病相关功能明确区分。[FDA guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/general-wellness-policy-low-risk-devices)
- 若用户表达自伤/危机，Agent 应停止生产力督促并提供当地紧急支持路径；具体国家/地区资源和规则应在发布市场确定后单独研究。

### 7.2 自主性与心理安全

- 默认由用户选择强度、渠道、quiet hours、最大追问次数和停止词；连续不回应应降级，而不是升级语气。
- 避免“你又失败了”、公开排名、不可修复 streak、经济惩罚等默认机制。可以提供游戏化，但应把未完成当作计划信息而不是人格评价。
- Agent 应说明不确定性并允许一键编辑拆解结果。Goblin Tools 的官方边界表述很合适：通用模型输出可能不准确，需由用户判断。[Goblin Tools About](https://goblin.tools/About)
- 关系型 AI 必须透明说明它是软件；不能伪造真人关心、假装已观察到用户现实行为，或利用用户内疚维持使用。CSCW 预印本也把模拟陪伴和自主性列为伦理问题，但仍是早期定性研究。[Chen et al., 2026](https://arxiv.org/html/2603.17258v2)

### 7.3 数据与工具安全

- ADHD 状态、情绪、失败原因、日历、窗口标题和工作内容组合后可能成为敏感健康/职业画像。优先最小化收集、local-first、字段级删除/导出、把原始行为日志与 LLM 输入分离。
- 不要默认把 ActivityWatch 一类的窗口标题/URL 上传模型；可以先在本地聚合成“工作/分心/离开”且允许用户检查。
- 外部副作用采用最小权限和逐工具审批。发送消息、创建日历事件、邀请真人、公开进展、删除任务和导出健康数据不应只凭模型决定。Agent 框架的 HITL 是实现手段，不能代替产品层明确的授权规则。[OpenAI HITL](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals)
- 面向美国用户时，不能假设“不属于 HIPAA 就没有义务”。FTC 2024 修订明确 Health Breach Notification Rule 可覆盖未受 HIPAA 约束的健康 App 和类似技术。[FTC compliance guide](https://www.ftc.gov/business-guidance/resources/complying-ftcs-health-breach-notification-rule-0) 其他发布地区需另做法律核查。

## 8. 作为开源作品集的价值：应展示什么

### 8.1 能证明项目管理的公开证据

- 一页 problem framing：目标用户、核心转换、明确不解决什么。
- 研究日志和带来源的设计假设；本文件可作为起点。
- issue map、里程碑、优先级依据、用户反馈如何改变 backlog。
- 领域状态图、事件 schema、ADR、隐私威胁模型和医疗声明边界。
- 每个迭代的 success metric、实验结果和“为何没有继续做”。
- 小范围、可完成的 release，配 demo、测试数据、安装说明、贡献指南、许可证和 roadmap。

### 8.2 能证明与 AI Agent 协作的公开证据

- skill/prompt 版本化，注明输入、输出 schema、边界和反例。
- Agent trace 的脱敏样例，以及拆解质量、过度提醒、越权工具调用、恢复包完整度的 eval。
- 所有有副作用的工具都有权限表、审批测试和失败恢复测试。
- PR/commit/issue 记录中区分“Agent 提议、人工接受/修改/拒绝”，展示判断而不是声称全部由 AI 自动完成。
- 用固定场景回归，例如“错过三次”“情绪低落”“进入 hyperfocus”“日历冲突”“模型生成 40 个子任务”“用户说停止提醒”。

### 8.3 许可证是产品决策的一部分

GitHub 官方说明：公开仓库若没有许可证，默认版权法仍适用，别人通常不能合法复制、修改和分发；“公开可见”不等于开源。[GitHub licensing docs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository) MIT/Apache-2.0 便于宽松复用，GPL/AGPL 强化衍生作品开放义务；具体选择会影响贡献者和部署方式，应在确定商业/社区目标后单独作出，而不是从参考项目直接复制。

## 9. 建议带入后续访谈、但本报告不替用户回答的问题

后续 grilling 最值得先澄清的不是功能偏好，而是：

- 最痛的失败点是首次启动、被打断后的恢复、每天重启，还是长期项目失联？
- 用户期待的是温和提醒、明确约束、真人在场、AI 共同执行，还是根据状态切换？
- 什么信息能证明“在做”，又不形成监控感？
- 哪些行为必须由用户主动确认，哪些可以后台自动发生？
- 应用首先服务个人真实使用，还是首先展示项目/Agent 工程能力；两者的最小交集是什么？

这些问题应在访谈中由用户决定，不能从诊断标签或竞品功能代推。

## 10. 主要不确定点

1. 成人 ADHD 专门的任务启动/再启动数字干预证据仍少。临床 CBT/MCT 支持成套技能干预，不能直接证明某个通知、计时器或 LLM 功能。
2. Body doubling 广泛用于商业产品和社区，但 ADHD 特异、独立、对照的有效性研究仍很薄；厂商内部调查只能视为产品发现线索。
3. 2026 CSCW 论文是已接受标注的预印本，设计洞见很相关，但样本小且以自述为主。
4. Inflow 的同行评审论文证明可用性/可行性，不证明因果疗效；存在公司相关利益披露。
5. GitHub 活跃日期、产品功能和 OpenAI/LangGraph API 会变化；本文记录的是 2026-08-09 快照，正式实现前需重新核实。
6. 本轮没有对每个国家/地区的医疗器械、隐私、未成年人、危机干预义务做法律分析。
