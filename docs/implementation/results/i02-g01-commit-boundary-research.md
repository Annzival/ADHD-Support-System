# G-01：重启边界与数据库提交协调研究

## 结论

**需产品取舍。** 在本轮检查的约束和两个方向内，未找到有一手依据、可直接用于当前 MVP 的严格协调方案。这不是证明所有方案都不可能。保留进程句柄能辨认旧实例并观察退出；SQLite 能原子保存报告与命令结果；两项保证并不自动组成“旧宿主退出／新宿主开始运行与 Core 提交不可交错”的保证。

具体差别是：Core 已查到旧宿主还活着，随后旧宿主退出、新宿主运行，最后 Core 才提交旧报告。当前 ADR-0057 要拒绝这份报告；较弱候选允许保存它。报告仍只描述历史设备返回，不改变任务／会话或重发通知，但持久历史的内容确实会不同，不能称为没有用户影响。

**唯一建议下一步：** 将文末这个具体行为取舍交当前明确激活的治理线程核对，再由用户决定是否接受较弱边界。本轮不建议再加一次检查的第三轮实验，也不授权实验或生产实现。若用户不接受，继续保留当前规则与阻塞状态；任何进一步改变启动所有权的研究都需要单独限定范围。

## 基线、方法与证据层级

沿用 [Issue #33](https://github.com/Annzival/ADHD-Support-System/issues/33)、[Draft PR #35](https://github.com/Annzival/ADHD-Support-System/pull/35) 和 `agent/implement-mvp-deterministic-recovery`。启动工作树干净。核实 PR #40 人工合并为 `2bd1644`，交接存在于远端 main，正常合入为 `fe02e32`，无冲突、无历史改写。

完整读取 AGENTS、CONTEXT、发布流程、ADR-0055/0057、研究交接、两轮报告与机器摘要，以及实验事务／进程身份代码；补查生产事务和宿主启动代码。使用 research 技能，后台资料核对与本地只读分析分开。不运行新旧实验或回归，不改代码、测试预期、产品文档或 ADR。

- **资料保证**：下面官方资料实际描述的能力，受各自前提限制。
- **代码与既有证据**：[第一轮](i02-g01-verification.md)及[机器摘要](i02-g01-verification.json)，源码 `62bc99a`、证据 `eb3863b`；[第二轮](i02-g01-restart-revalidation.md)及[机器摘要](i02-g01-restart-revalidation.json)，源码 `9848b29`、证据 `86b6941`。本轮只读，不把旧测试写成新执行。
- **研究推断／未接受候选**：据前两项分析可提供的保证及缺口；不作为新验收答案。

目标仍为 Windows 10 22H2/19045 x64、Python 3.12.3、Go 1.25.0、Wails beta.8、Fixed WebView2 151.0.4129.78。资料访问日期为 **2026-09-26**。本轮 Windows 与 Linux 执行均 **NOT_RUN（研究任务）**；既有 Linux 证据不外推 Windows，I-02 未 PASS。

资料核对共两轮后停止：第一轮查进程对象、退出、互斥、SQLite/WAL 与 Python 提交行为；第二轮只核对 commit hook 是否填补原子空隙，以及创建／强制终止的事件含义。新增关键依据是 hook 返回零只是允许提交继续，不能把回调时的进程状态固定到提交完成；没有展开第三个方案或继续架构检索。

## 一手依据、前提与限制

以下为资料内容的摘要；跨系统结论另标研究推断，没有把厂商未承诺的性质写成保证。

| 来源（均访问于 2026-09-26） | 官方描述的保证 | 使用前提与限制 |
| --- | --- | --- |
| Microsoft [Process Handles and Identifiers](https://learn.microsoft.com/en-us/windows/win32/procthread/process-handles-and-identifiers)、[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess) | 已打开句柄可在进程终止后保留；OpenProcess 根据 PID 和访问权限打开对象 | 必须先正确绑定原进程，持续保留句柄；数值 PID 不能独自证明旧实例。首次打开前的身份竞争未解决，查询所需权限失败则依据不足，不能自动升级权限 |
| Microsoft [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)、[Terminating a Process](https://learn.microsoft.com/en-us/windows/win32/procthread/terminating-a-process) | 超时 0 查询当前对象状态；终止后的进程对象为 signaled | SYNCHRONIZE 权限和有效句柄是前提；这是时点观察，不承诺进程之后继续存活 |
| Microsoft [TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess) | 有 PROCESS_TERMINATE 权限的调用可强制结束目标；外部调用异步发起，等待句柄才确认真正终止；进程不能自行阻止被终止 | 发起终止不等于 E，未决 I/O 会影响完成。不能依赖被终止方清理；不以改 ACL 或扩大权限绕开本轮异常退出条件 |
| Microsoft [Using Mutex Objects](https://learn.microsoft.com/en-us/windows/win32/sync/using-mutex-objects)及上述等待 API | 可串行化共享资源访问；owner thread 未释放而终止时等待方可取得 abandoned mutex，资源状态需检查 | 只有遵守协议的路径会等门；放弃的锁不是应用数据已回滚的证明。将其与 SQLite 组合的效果是候选推断 |
| Microsoft [CreateProcessW](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw) | 创建进程和主线程，成功返回时不保证初始化已完成 | 不能把完成初始化或 R 当作 N；创建者能够延迟自己发起的创建，不代表它控制所有启动入口 |
| SQLite [Transactions](https://www.sqlite.org/lang_transaction.html) | 单库同时至多一笔写事务；BEGIN/COMMIT/ROLLBACK 管理数据库事务 | BEGIN IMMEDIATE 取得的是数据库写入资格，不是外部进程生命期锁；不能由 INSERT 成功推断已提交 |
| SQLite [Write-Ahead Logging](https://www.sqlite.org/wal.html)、[PRAGMA synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous) | WAL 追加提交记录标识提交，FULL 在每笔提交同步 WAL；checkpoint 是把 WAL 内容搬回数据库的另一动作 | 依赖底层存储及同步接口如实工作，不增加项目原本没有的任意硬件故障承诺；外部进程身份不在其事务内。不能等到 checkpoint 才承认原命令已提交 |
| Python 3.12 [Connection context manager](https://docs.python.org/3.12/library/sqlite3.html#how-to-use-the-connection-context-manager) | 有打开事务时，正常退出连接上下文会提交；块内异常或提交失败时回滚 | 对应当前实验的控制流；不负责判断宿主是否退出，不等同生产封装的显式 commit |
| SQLite [Commit And Rollback Notification Callbacks](https://www.sqlite.org/c3ref/commit_hook.html) | commit hook 返回非零可转为回滚，返回零允许 COMMIT 继续；回调不得修改触发它的连接 | **推断：**在 hook 内再查存续仍只是提交继续前的一次检查，未获得阻止 E/N 的保证。这里只排除 A 的一个微调，不提出第三方案；未添加绑定、依赖或回调 |

Windows 文档所列 API 最低支持版本早于 Windows 10；这支持接口适用性，不验证锁定机器权限、实际错误码或时序。SQLite 为访问当日官方文档，结合锁定旧版本的既有代码阅读，未升级运行库或声称新做了旧版本验证。

## 先分开八个事件

| 记号 | 具体事件 | 不能替代的事件 |
| --- | --- | --- |
| D | 设备 API 返回结果，宿主能形成报告 | 不等于通知显示或用户看见 |
| A | 该结果请求到达 Core | 不等于接纳，更不等于持久保存 |
| C | Core 校验关联与运行资格；本讨论取最后一次存续检查 | 不等于事务提交 |
| T | SQLite 事务实际提交，报告与命令结果一起成为持久结果 | 不等于执行 INSERT、进入 commit 函数或 HTTP 成功到达宿主 |
| E | 旧宿主进程实际结束 | 不等于退出请求，也不等于 Core 已发现退出 |
| N | 新宿主进程开始运行 | 不等于完成初始化、取得单实例锁或登记 |
| O | Core 观察到旧进程已经结束 | 可能晚于 E；不能以 O 重新定义重启 |
| R | 新宿主登记到 Core | 可能晚于 N；不能以 R 重新定义重启 |

`U` 另指用户回应的领域事务提交。下文箭头表示受控顺序或候选协议要求，**不用跨进程墙钟大小证明顺序**。E、N 分开讨论；不擅自决定尚未启动新宿主时的额外产品语义。既有明确反例同时包含 E 和 N，已经足够检验当前禁止跨重启补存的规则。关闭窗口但进程留在托盘，没有 E/N。

## 现有代码确实说明了什么

`spikes/i02_g01/server.py` 在一个实验库事务内先查完整原命令；已提交且内容相同就返回原结果。新增结果写入报告、事实、命令结果后，执行 `live()`，再退出 SQLite connection 上下文提交。`process_identity.py` 保留 OS 进程句柄；Windows 使用 `OpenProcess(SYNCHRONIZE)` 和 `WaitForSingleObject(handle, 0)`。它没有锁住被观察进程的生命期。

第二轮确定性控制点给出 `D → U → A → C → E → N → T`，R 尚未发生。要求 409／零报告，实际 200／一份报告；原断言保持 FAIL。第一次的 `E → N → A → C` 空档则已由保留句柄修复。两者不能混为一个问题。已提交丢响应支是 `T → E → N → 同命令查询`，可返回原结果而不新增事实。

生产 `agent_core/core.py` 使用 WAL、`synchronous=FULL`、`BEGIN IMMEDIATE`，状态／事件／命令结果统一事务。实验 `experiment.sqlite3` 是另外的库，未显式设置 WAL。**实验库的提交证据不能证明生产事务集成完成。** `desktop/bridge.go` 当前由宿主启动并守护 Python；`main_windows.go` 的单实例设置也不等于有一个控制所有进程创建的外部启动仲裁者。

## 两个方向比较

| 方向 | 试图提供的保证与前提 | 反例／限制 | 架构成本与结论 |
| --- | --- | --- | --- |
| A：提交与生命周期共用互斥门，尝试保留严格规则 | Core 从运行检查至提交持有同一门；正常退出与新启动方也必须经该门。若所有实际新进程创建都在门外等候，可使受控启动 N 排在 T 后 | 普通锁只约束参与协议的代码，不阻止崩溃或强制结束 E；若新宿主开始执行后才取门，N 已发生，仍有 C→E→N→T。正常退出合作不能解决这一支 | 当前架构内未证明严格保证。创建前仲裁要求覆盖快捷方式、开机启动、重启等所有入口，并重做仲裁者自身退出／恢复；不是增加一个字段的成本，不能当作已合格 MVP 方案 |
| B：以 Core 同一结果事务内最后一次可靠存续检查 C 决定新增资格 | 同 Core 运行、许可／调用对应、旧实例在 C 尚未结束且身份可确认；报告和原命令同事务保存。已提交查询先于这些新增守卫 | 允许 C→E→N→T 的旧报告；不满足现行 ADR-0057。C 至 T 没有已证明的最大时长 | 复用现有最小机制，技术增量较小，但改变历史结果接纳行为。**未接受**，不能改测试预期，也不能自动生产化 |

### A：谁能阻止什么，为什么仍不构成严格方案

Core 持门可以阻止另一段也取门的启动／正常退出代码进入，不能仅凭持门阻止 Windows 终止旧宿主。若让宿主线程持门，Core 又必须在它释放后才能取得，交接仍不保证宿主继续活到 T；宿主线程异常结束导致的 abandoned mutex 是供接手方发现异常的信号，不是自动回滚另一个进程的 SQLite 事务。这是依据 [互斥语义](https://learn.microsoft.com/en-us/windows/win32/sync/using-mutex-objects)与[强制终止语义](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)作出的组合推断。

逐支分析如下，均为候选推断，不是新增实验：

| 情况 | 该门能否守住 |
| --- | --- |
| 合作式关闭 | 可以设计为等 Core 完成 T，再允许正常关闭；仅覆盖配合协议的退出 |
| 异常／强制结束 | 不能靠普通互斥门阻止 E，也不能保证退出清理代码运行；Core 仍可能继续提交 |
| 新宿主未登记 | 在新宿主内部等门发生于 N 后，因此不解决反例；等待登记更晚 |
| C 后、T 前发生 E/N | 与第二轮相同的竞争仍可发生；再检查或异步 O 只改变观察位置 |
| Core 自身退出 | 需要按 SQLite 恢复后的已提交记录判定：存在完整原命令就返回，不存在则旧 Core 运行不再有新增资格。门释放／被遗弃不提供额外持久判据 |
| T 后重启且响应丢失 | 原命令结果已与报告同事务保存，可读取；无需旧宿主继续存活 |

如果由另一个始终先取得门的创建者在 **CreateProcess 之前** 控制所有 N，理论上可把受控 N 排在未决 T 之后；这是附加前提下的顺序推断，不是当前架构保证。[CreateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-createprocessw)本身不等待初始化完成。门仍不阻止 E；若把“进程已运行但还没获得门”改称“尚未重启”，则直接改变启动边界。不得把这两个动作混用来声称满足 ADR。

成本／冲突逐项标记：改变当前“宿主管理 Core”的进程所有权或增加唯一创建仲裁者，需要重新审查 ADR-0008 的职责与启动链；宿主直接参与数据库写入违反 ADR-0008/0010 及本轮 Core 唯一写入约束，未采用；新增共享持久运行事实或宿主持久结果库超出本轮与 ADR-0057 首版取舍，未采用；跨 OS 对象与 SQLite 的原子同步保证在所查接口中未找到；把 N 移到取得门／登记完成会改变已确认重启定义，未采用。纯技术上的门本身不是 ADR 冲突，缺少的保证和为补保证付出的架构变化才是需要回传的内容。

### B：明确哪些旧报告将多保存

以下只描述 **未接受的行为候选**，现有失败仍按严格规则失败。

1. `D → U → A → C(旧实例存活) → E → N → T → R`：会保存报告。当前应拒绝；用户将来查看历史可能多看到一条设备报告，虽然新宿主已运行。调用与许可仍必须对应，不能从 U 推断设备结果。
2. `D → E → N → A → C(旧句柄已终止)`：仍拒绝，即使 R 没到；未知身份／句柄不可用也拒绝，不退回最后登记值。
3. `D → A → C → Core 异常退出（未提交）→ 新 Core → 重交`：无已提交原命令时拒绝；不把旧请求自动变成新 Core 的可保存结果。
4. `D → A → T → 响应丢失 → 任一进程重启 → 原命令查询`：返回已有原结果，不新增报告。与当前规则相同。若提交结果因崩溃暂时不明，读取恢复后的数据库决定，不能用是否收到 HTTP 200 代替 T。
5. 同进程关闭窗口以及 `D/U` 顺序无法证明：关联满足时保存未知顺序报告；没有新增重启边界变化。

新增保存只写历史设备报告与命令结果，不改变任务、会话、安排或旧按钮，不重开干预，不授予发送许可，重发次数应为 0；同报告与命令冲突仍按原机制去重／拒绝。顺序、机会资格、是否看见保持未知，实际发送时刻和精确延迟不从接收时刻生成，不因此增加合格机会。这些是候选必须保留的要求和既有隔离证据，**并非本轮验证了生产行为**。

C 与 T 之间可能包含进程调度、SQLite 提交及 I/O；没有从所查资料得到整个区间的可证明上限。连接忙等待超时也不是整个提交区间的期限保证。不能说只有几毫秒，也不能用墙钟阈值把不确定性伪装为严格顺序。B 在 C 已发现退出时仍拒绝，但不能承诺退出一定能在 T 前被观察到。

## 推荐交回的具体取舍与停止点

请治理线程核对后交用户明确决定这一件事：**是否允许 Core 已确认旧宿主仍存活并进入结果提交的请求，即使随后旧宿主结束、新宿主开始运行，仍完成这笔历史报告保存？** 代价是重启后可能多保存一条旧设备报告，窗口无已证明上限；收益是复用已验证关联与事务机制，不为该边界新增启动仲裁架构。已提交原命令查询、不重发、不恢复旧操作、不计未知机会都继续保留。

建议讨论这个具体取舍，不把它直接当成同意。拒绝该变化就保持现有规则与 G-01 阻塞；本研究不从技术成本倒推用户必须接受。治理线程负责判断对 MVP／领域模型／ADR 的影响。本 session 没有发现 ADR 文本之间的新矛盾；B 若被采纳必须显式变更 ADR-0057 行为，A 的扩展前提也不能默许。

本轮到可行性限制与行为代价已区分处停止。不新增 Windows 操作任务；已有第二轮报告保留锁定 Windows 最小步骤，但本研究未授权或执行它们。不发起下一阶段，不把 PR #35 视为可合并。

## 可复核入口与保留证据

本轮只做文档、历史对象／哈希与链接检查；不重跑下列报告中的实验命令。读者可从 Git 对象和文件摘要复核引用，不需要启动程序：

```bash
git show 9848b29:spikes/i02_g01/server.py
git show 9848b29:spikes/i02_g01/process_identity.py
git show 9848b29:desktop/i02_g01_restart_test.go
sha256sum docs/implementation/results/i02-g01-verification.{md,json}
sha256sum docs/implementation/results/i02-g01-restart-revalidation.{md,json}
git diff --check
```

| 只读来源 | 本轮核对 SHA-256 |
| --- | --- |
| 第一轮报告 | `02d500c663612bd123b6b691a098bb036288f688ac940222d0ff344acec21595` |
| 第一轮机器摘要 | `0e2112ff09fd9961e883065839f047fec3e44e78f32bb80b8c391f8214f20a18` |
| 第二轮报告 | `7ed71d74b145844860e9003ccadc23870cd23a913fb4f95cefdac48416ca215a` |
| 第二轮机器摘要 | `d59d854e86c461caaf1fa916500af1c778047e35b224a1cf4ffa5018948bdc4b` |
| 当前实验 server.py | `a03b2a6361aa67b86c7ff8d6cbf430b2c189bb098a17801cc7afd68708a75df2` |
| 当前实验 process_identity.py | `299d5319da4991da7da77d32cc5d2d462da9cb7e81b21527c554cc5857443fe3` |

原始运行日志继续按两轮机器摘要在 `.scratch/i02-checks/` 受控保留，原哈希不变；本轮没有新增原始运行日志或个人数据。研究 checkpoint 由本文件 Git 历史及 Issue／PR 发布记录定位，不能把 `fe02e32` 同步提交称为新的实验源码版本。
