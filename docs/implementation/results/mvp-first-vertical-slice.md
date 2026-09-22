# I-01：首个 PC 确定性执行闭环

## 当前结论

**复审修复及 Windows 定向回归已通过，等待独立代码复审。** `21b4a24` 的通知不重复、Core 断连恢复后收尾 partial／12 保留，以及最终 partial／720 秒持久证据均已核验。两项 P2 的故障注入自动回归已通过；新实机证据补齐。尚未收到修复后的独立复审结论，不据此宣布可 merge，不自行 Ready、合并或进入 I-02。旧版本成功与失败证据均保留。

任务：[Issue #31](https://github.com/Annzival/ADHD-Support-System/issues/31)。本任务是独立 implementation，不是产品治理；从 PR #30 已合并后的 `main@ad940755ebfd19d8fe7ef7011f93ebc17a242e4a` 创建 `agent/implement-mvp-first-slice`，启动时无既有 I-01 PR 或分支、工作树干净。未修改产品范围、领域模型或 ADR。

代码、测试与验收脚本 checkpoint：`e262f96fb2cca99d526dac5feff30e5e53fb5a91`；[Draft PR #32](https://github.com/Annzival/ADHD-Support-System/pull/32)。该锚点为首次交付基线；后续 Windows 准备修复单独记录于文末，不覆盖原自动证据。Linux 检查针对该代码，机器可读摘要见 [linux-checks.json](mvp-first-vertical-slice.linux-checks.json)。Windows 必须从最终发布的干净 checkpoint 构建并记录自己的 commit 与二进制哈希，不能复用 Linux 二进制哈希作为实机身份。

## 实现与方法

贯通路径：已确认开发 P/A/a → Core 到点创建唯一开始干预和送达尝试 → Wails 原生通知／小窗 → localhost 命令 → 原子建立会话及首次检查点 → 报告完成进入等待收尾 → 完成、跳过或关闭收尾 → 原子保存证据并持久结束。

Python Core 使用标准库 SQLite、HTTP 和有边界的 WebSocket 快照协议；数据库唯一索引、串行写事务和预期版本共同守住唯一活动位置。成功事件、调度和命令结果同事务保存。客户端保留不确定请求的原命令 ID；宿主仅负责进程、端点、令牌和 Windows 呈现。源码未直接依赖 spike 模块，也未以旧 spike PASS 代替本次验证。

Linux 自动检查使用临时数据库、可控制时钟和真实子进程。事务测试逐个写入边界注入存储异常，并对开始、完成报告、完成／跳过收尾分别进行未提交进程退出、丢失响应后重试和并发校验。前端浏览器测试使用真实 Core，只用测试适配层替代 Windows 载体，明确不构成原生桌面证明。

实现细节和实际命令见 [运行说明](../README.md)，Windows 命令、预期结果及观察字段见 [实机步骤](../windows-i01.md)。未采用建议的 pytest 名称，改用等价的标准库 unittest，避免新增 Python 运行依赖。

## 环境

| 层 | 实际或锁定环境 | 证据边界 |
| --- | --- | --- |
| Linux 自动 | Linux x86_64 / kernel 6.8.0-49、Python 3.12.3 64 位、SQLite 3.45.1、Go 1.25.0 | 领域、进程、协议及 Windows 目标构建 |
| 补充前端 | Node 24.19.0、Playwright 1.58.2、Chrome for Testing 151.0.7922.34 Linux | 嵌入式 JS 行为；不是锁定 Windows WebView2 |
| PowerShell 解析 | PowerShell 7.4.6 Linux | 语法检查，不是 Windows PowerShell 5.1 执行 |
| Windows 目标 | Windows 10 22H2 / 19045 x64、Python 3.12.3 x64、Go 1.25.0、Wails v3.0.0-beta.8、Fixed WebView2 151.0.4129.78 x64 | 首轮已回传：Build 19045.7725、SQLite 3.45.1；沿用锁定环境，详见文末 |

Linux Go 1.25.0 下载包按 go.dev 官方 SHA-256 核验。浏览器补充检查最初因未安装对应浏览器／缺运行库而未启动；补齐仅本地测试运行库、显式使用现有 Linux Chrome 后通过。没有据此升级 Windows、Wails、Go、Python 或 WebView2。

## 场景结果

以下为本阶段最终场景结果。A／B／D 对应 `c6b868e`，C 复测对应 `9493d2e`；自动证据与实机证据各自标明边界，不把 I-02 分支写成 PASS。

| 场景 | 自动检查与实际结果 | Windows 对应步骤／状态 |
| --- | --- | --- |
| EX-01 | PASS：唯一开始干预；会话与检查点联合创建；完成后等待收尾；完成／跳过后唯一证据、无活动会话，后续确认安排可以开始。`test_execution_golden_path.py`、`test_atomicity.py` | A/B PASS |
| EX-02 | PASS：打开、取消、缺少确认均无会话；确认时长后首次检查时间正确。Python + `frontend.test.mjs` 实际界面操作 | C 复测 PASS |
| SES-02 完成分支 | PASS：检查点前／后完成 × 完成／跳过收尾四种组合；原检查点立即失效，等待收尾继续占位置。`test_execution_golden_path.py` | A/B PASS |
| AT-01 本阶段 | PASS：开始、完成报告、完成收尾、跳过收尾每个写边界故障回滚；事务中途子进程退出码 71 后保持完整旧状态。`test_atomicity.py` | 自动证据已具备；Windows 脚本重跑同套测试 |
| AT-02 本阶段 | PASS：成功后丢失响应、重启再用同 ID 返回原结果，状态／事件／调度不重复；前端实际重试原命令。`test_atomicity.py`、`test_transport.py`、前端测试 | D PASS；Windows Run 自动重跑门槛通过 |
| AT-03 本阶段 | PASS：开始／完成／收尾竞争只允许一份结果；完成收尾与跳过竞争不产生相互矛盾证据；第二行动在执行中／等待收尾均被拒绝，释放后可开始。`test_atomicity.py` | Windows 自动重跑；不包含改期、续行、恢复竞争 |
| REC 适用部分 | PASS：真实 Core 重启保留数据库身份、同一会话和检查时间、等待收尾或持久结束；旧主动尝试失效不补发。`test_execution_golden_path.py`、`test_delivery_and_recovery.py`、`test_transport.py` | D PASS；不宣称完整 REC-01～12 |
| DESK-03 | PASS（Linux）：HTTP／WebSocket 缺失、错误、旧令牌拒绝，旧连接失效，新发现信息重连；Go bootstrap 超时回收子进程和交接目录。`test_transport.py`、`bridge_test.go` | D PASS；Windows 宿主重连整合通过 |
| DESK-04 本阶段 | PASS（Core）：有效对象解析、已解决／过期通知上下文拒绝并返回现状，无重复会话。原生通知回调、焦点与小窗由 Windows 观察补齐 | A/B PASS；C 复测 PASS |

补充检查：全部完成／部分完成可区分，原完成报告不被覆盖；实际开始、结束和未填用时保持未知。完整历史更正与版本迁移并未实现。

## 自动检查汇总

- Python：17 个测试方法通过；包含上述参数化分支、写入故障、并发和真实进程检查。
- Go：3 项测试通过；`go vet ./...` 通过。
- 嵌入式前端：最终 4 项浏览器／Core 交互测试通过，包含两个窗口入口的 Wails runtime 就绪与关闭回归。
- Linux 的 Windows amd64 交叉构建通过；该交叉构建产物未运行，实机证据来自 Windows 本机构建的独立二进制。
- JavaScript 语法、PowerShell AST、`git diff --check` 通过。

原始自动输出留在本次 Linux checkout 的 `.scratch/i01-checks/`；已提交摘要仅含工具版本、结果、源文件／输出／二进制 SHA-256，不含令牌、个人方案、绝对路径或未脱敏日志。首轮 Windows 回传包已受控保存并核验，见文末；原始附件不提交仓库。

## 限制、未决与回传

1. 原 C 轮关闭修复复测通过；复审新增两条异常路径问题已修复，本次定向 Windows 证据已通过，尚待独立复审。PR 保持 Draft，暂不适合 merge。
2. 开发夹具固定一个 4 小时窗口，这是明确测试数据，不是新增产品默认值。超过该窗口时旧操作拒绝并显示本阶段不可用；自动到期收束、无回应较弱跟进、恢复干预与切换属于 I-02，未在此伪造完成。正式观察不可使用本切片。
3. 确认行动仅限合成夹具。I-03 的真实导入、LLM／供应商集成未开始；I-02 其他分支、开机启动及完整宿主回归、I-04 观察准入也未开始。
4. 不覆盖真实 PC 重启、异常断电、数据库损坏／备份恢复、其他 Windows 版本、同权限恶意进程或公开分发。
5. 当前未发现必须改变产品范围／领域模型／ADR 的冲突，无新增产品治理决策请求。回传内容是本次 I-01 PASS 与限定范围，不改变 Issue #10 已确认的构建就绪结论。

下一步仅为本次修复的独立代码复审；沿用 Issue #31 / Draft PR #32，不自动进入 I-02，不自行 Ready 或合并。

## Windows 准备反馈：Python 发现兼容性修复

用户在 Windows 执行 `Run / ConfirmedDuration` 时，发现阶段的 `py -3.12 -c ...` 返回 `Unknown option: -3`，错误用法属于 Python 解释器。此次未进入构建、夹具创建或桌面启动，不能记为桌面能力 FAIL 或 PASS；整体仍等待 Windows 验收。

在 Linux PowerShell 中加载脚本真实函数与发现调用位置，将 `py` 映射到真实 Python 3.12.3 进程，复现完全相同的错误。以同一进程调用器执行普通 `-c` 能成功，确认可复现缺陷是脚本假定命令名 `py` 必然支持 Launcher 版本参数；无需推断 Windows 上具体是何种包装器或命令映射。

修复保留首选 `py -3.12`，失败后依次探测无选择器 `py`、`python`、`python3`，只接纳锁定的 3.12.3 x64 和有效绝对路径。全部失败给出 `-PythonExecutable` 指引；用户显式指定路径时不自动换用其他解释器，后续原版本／位数门槛不变。未修改 Core、桌面代码、产品范围或 ADR。

针对性回归入口（不依赖 Pester）：

```powershell
powershell -NoProfile -File scripts/acceptance/tests/test-python-discovery.ps1 -TestPython 'D:\Tools\Python312\python.exe'
```

实际 Linux 命令使用 PowerShell 7.4.6 与 `/usr/bin/python3`：6 项检查通过，覆盖直接解释器的 `py`、模拟 Launcher、缺少 `py`、错误版本、错误位数和显式路径绕过发现。前者使用真实进程复现原故障；其他候选布局通过进程边界替身模拟。脚本解析与 diff 检查通过。这里不重复宣称 Windows PowerShell 5.1 已通过；待用户用修正版或显式路径重试。

原 `linux-checks.json` 继续对应 `e262f96` 基线，不能当作修复后脚本的哈希。修复证据见 [解释器发现检查摘要](mvp-first-vertical-slice.python-discovery-checks.json)；修复提交由同一 Issue #31 / Draft PR #32 追踪。

## Windows 准备反馈：根目录本机产物误触发干净检查

Python 发现修复后，用户运行推进至干净 checkout 检查；`git status` 显示唯一未跟踪内容为根目录 `.evidence/` 和 `.tools/`。已有忽略规则仅列出部分 spike 子目录的同名产物，遗漏了根目录的本机证据／工具位置。

本次仅将 `/.evidence/` 和 `/.tools/` 加入 `.gitignore` 并补充运行说明；不删除、移动或提交原始证据和下载工具，不放宽验收脚本对源码的干净检查，也不忽略任意层级的同名目录。

用实际 `.gitignore` 在隔离 Git 仓库重现：修复前，两目录出现在脚本使用的 `git status --porcelain --untracked-files=normal` 输出；修复后输出为空。随后修改已跟踪文件、增加普通未跟踪源码和嵌套同名目录，三者仍能被检查发现；产物文件继续存在。检查通过，未重跑未改动的 Core／桌面测试。用户的 Windows 完整重试结果仍待返回，整体继续等待 Windows 验收。

## Windows 首轮证据核验与原生关闭修复

用户回传 `return-20260922-215256.zip`，SHA-256 为 `F9B85B988DB600F1F5100FE2107297403237A1F5E51DDF3B26DF247E74FB6638`，与实际文件一致。四轮源码均为 `c6b868ebc83546eaa981fba0e42abd5760c23a20`，Windows 二进制 SHA-256 均为 `C1976706A097D332ABF5DCD79F3FD085D6D71995E3CD6A8AFDDDCF3944C15E4B`；四个数据库相互独立。机器可读核验与逐文件哈希见 [Windows 核验摘要](mvp-first-vertical-slice.windows-review.json)。原始包在当前任务附件及操作者本机受控保留；仓库不复制原始状态／日志。

| 轮次 | 核验结果 | 关键证据 |
| --- | --- | --- |
| A | PASS（本轮范围） | 有效通知回调与人工观察相符；完成报告早于检查点；等待收尾后确认全部完成；一份证据、活动位置释放 |
| B | PASS（本轮范围） | 检查点先到达、随后报告完成并显式跳过；失效通知回调；旧通知前后完整持久状态一致 |
| C | FAIL（关闭）；时长分支 PASS | 打开／取消前后持久状态相同且没有会话；确认后首次检查为 300 秒；两个叉号均无法关闭，最终仍等待收尾、没有执行证据 |
| D | PASS（本轮范围） | 会话与检查时间保持；首次检查提示在第一次重启前已送达；等待收尾重启前后一致；结束后重开状态一致且唯一证据；四次连接没有重放旧呈现 |

摘要与最终状态字段一致，最终状态与桌面日志的哈希匹配摘要。全部中间快照按轮次顺序核验；比较时仅排除读取时刻 `now`，没有把事件或调度差异隐藏。人工观察与合成状态共同支持以上结论。Windows 自动测试原始日志未回传，Run 在自动测试失败时会停止，摘要存在支持脚本已通过该门槛；不声称独立重读了未回传日志。

### 缺陷、修复与检查边界

正式页面只加载 `app.js`，没有加载 Wails 自带的 `/wails/runtime.js`。锁定 beta.8 的 `WebviewWindow.ExecJS` 在收到 `wails:runtime:ready` 前将脚本排队；该消息由 runtime 加载时发送。原生关闭钩子先 Cancel，再通过 ExecJS 派发 `host-close`，因此漏载 runtime 会让窗口保留而前端关闭逻辑收不到事件。旧浏览器测试直接派发事件，绕过了这个依赖，未能发现缺陷。

回归测试从锁定 Go 模块读取真实 runtime，通过浏览器加载正式 HTML，替代的仅是原生消息接收端。修复前就绪消息检查在 2 秒后失败；在 HTML 增加 runtime 模块加载后通过。主窗口和 overlay 两个入口均验证：发送就绪消息、执行真实宿主关闭脚本、执行中隐藏且会话不变、等待收尾时保存唯一最小证据后隐藏。测试不运行 Windows 原生消息循环，故这是依赖缺陷的自动复现与修复证据，不能替代原生 × 实机复验。

本次实际检查：前端浏览器 4 项通过，Go 测试通过，Windows amd64 交叉构建通过，diff 检查通过。Core 规则与命令处理未改动；不重复执行未受影响的全部 Python 用例。浏览器检查入口为 `npm test --prefix desktop`，使用锁定 Go 路径 `I01_TEST_GO`、已安装 Chromium 的 `I01_BROWSER_EXECUTABLE` 和本机浏览器运行库；具体环境同上方 Linux 补充检查。

### 首轮后的复测安排（已完成，保留历史）

当时安排：只需在新 checkpoint、新目录执行 C1～C6，回传四份中间快照、Collect 摘要、最终状态和桌面日志。可复制命令见[手册“本次只复测 C 轮”](../windows-i01.md)。原 A／B／D 证据保留为原 commit 的已核验基线，不要求用户重复四轮。修复后的 C 未回传前，整体保持未通过；PR 保持 Draft，不合并、不进入 I-02。没有产品范围／ADR 冲突，也没有需要产品治理另行决策的问题。

## C 轮修复复测与当时交付结论（复审前基线）

用户回传 `return-20260922-221817.zip`，实测 SHA-256 与提供值均为 `B83A7DAAC4207F837D7E5ACC5D030536673255E1F7B035B4847A4ABB50844486`。源码为 `9493d2e688d33339b43ca1d1463e9807e8132f7a`，Windows 二进制 SHA-256 为 `8E5425919468679691B58C84C56B1D7E619E0DB2DB7ECA01E35E1EB8FE883ABD`，环境与首轮完全一致。用户明确确认小窗和主窗口原生 × 均能关闭，托盘重开得到预期显示；对应四项 observations 均 PASS。

核验四份快照与最终状态：打开／取消时长期间完整持久状态不变，没有会话／检查点；确认后唯一会话和 300 秒首次检查点；执行中关闭小窗后仍为同一会话；主窗口关闭前为等待收尾且无证据，关闭后为 ended、唯一 explicit_skip 证据、无活动会话，未填实际时间／用时仍为未知。回传日志及最终状态哈希匹配摘要，摘要与最终对象一致。

机器可读核验见 [C 轮复测与最终覆盖摘要](mvp-first-vertical-slice.windows-c-retest.json)，内含回传文件哈希和 13 项观察字段到证据轮次／commit 的映射。首轮 [Windows 摘要](mvp-first-vertical-slice.windows-review.json) 及其 C FAIL 保留不覆盖。受影响路径在新二进制复测，A／B／D 沿用先前基线；修复仅增加 runtime 加载，Core 与宿主规则未变，并有修复后的 4 项浏览器回归、Go 测试和 Windows 目标构建记录。本次只更新证据与文档，没有新的产品代码变更，也不重复无关自动测试。

最终结论为 **I-01 PASS**。交付代码、自动测试、Windows 手册、机器可读摘要和结果文档均在同一 Draft PR #32；Issue #31 与产品治理追踪 Issue #10 同步结论。没有 ADR／领域／范围冲突，无需新增产品决策。用户可审查并决定是否合并；本执行任务不自行 Ready、合并、关闭 Issue 或进入 I-02，不宣称完整 MVP 或正式观察准入。

## 2026-09-23 复审 P2 修复（当时检查与待办）

复审基线 `3c80071`：Standards 无独立规范问题；Spec 两项 P2，接受并修复。此前 Windows PASS 仅证明当时已执行路径，不撤销原始证据，但撤回可结束 I-01 交付的判断，当前以本节待复审状态为准。没有产品范围或 ADR 冲突。

### 提醒命令结果不确定

将 Windows watch 内的传输工作抽取为跨平台 `delivery.go`／`delivery_watch.go`，正式宿主和测试调用相同实现。修复前，真实 Core 持续调度、领取已提交但响应丢失后，展示次数为 0、送达停留 claimed；回执未送达时也停留 claimed，回执已提交响应丢失时没有原命令确认重试。

修复在一个 Core 连接周期内保留领取与回执工作，按原 ID、原版本、原 payload 重试不确定命令；已展示标记与原始原生提交结果分开保留，回执重试不重新呈现。400／409 确定拒绝或失效送达终止工作；展示前重新向 Core 查询上下文和当前送达，避免旧成功结果复活已过期对象。不接管没有本地命令历史的 claimed；Core 重启后由原恢复规则处理，未引入持久宿主权威状态。

额外复现：HTTP 响应等待 2.5 秒时，旧同步 watch 阻塞心跳，Core 的在线租约到期导致提醒失效。现将命令工作与 WebSocket 快照心跳分离，单一 worker 串行处理、容量为 1 的最新快照队列，不在重试时停心跳。宿主退出等待 worker 收束，不跨 Core 运行期保留旧请求。

自动覆盖：领取／回执各自的请求丢失和提交后响应丢失（逐字节比较重试请求）；连续快照下只展示一次；原生提交失败仍重试原负回执；过期对象与无本地历史的 claim 不呈现；真实 Server 调度及 WebSocket 下慢领取响应不阻断在线状态。对应 EX-01、AT-02／ADR-0055 本阶段送达整合。

### 收尾草稿被重建覆盖

两个实际页面入口均复现：选择 partial、输入 12，一次状态读取失败后恢复，旧代码变回 completed／空值。现将未提交收尾草稿按会话 ID 保留在当前页面内存，字段编辑即更新；同一会话的重连、轮询和重绘均从草稿恢复。只有离开等待收尾或切换会话才丢弃，不写数据库／localStorage，不把草稿当作完成证据。原命令不确定时仍沿用既有幂等命令重试。

真实浏览器与 Core 回归同时验证界面值和最终证据：断连恢复后仍 partial／12，提交后为 partial／720 秒；主窗口和 overlay 各一例。对应 SES-03 确认结果与固化证据。测试清理还显式关闭测试 HTTP 连接，避免活跃轮询连接拖住测试退出。

### 检查与剩余工作

- Go 7 个测试入口通过（其中领取／回执组合含 4 个子案例），`go test -race ./...`、`go vet ./...` 通过；真实 Core／调度用于送达回归。
- 浏览器 6 项通过，包括原关闭／命令重试回归及两项新草稿回归。
- Windows amd64 交叉构建通过。Core 源码未修改，原 Python 17 项基线保留，不据此声称重跑未执行的检查。
- 入口：`cd desktop && go test -race ./...`、`npm test --prefix desktop`（从仓库根目录）。本机使用锁定 Go、Python 和此前同一 Chromium／运行库。

目前缺少新宿主／前端的 Windows 实机证据。只需按 [复审定向回归手册](../windows-review-regression.md) 跑一轮通知→开始→收尾 partial／12→重启 Core→确认输入保留→保存；Run 内同时执行 Go 的丢包回归。不要求重做旧 A～D。收到证据及复审反馈前，不重新声明整体 I-01 PASS。

## 2026-09-23 Windows 定向回归核验

回传 `return-20260923-013401.zip` 的实际 SHA-256 为 `9415E21DD348E5BB3CAF3679AC00A8A70C9AB205FA543E28AA278F99A37E7339`，与用户提供值一致。源码 `21b4a24084c16268ded8b63b0b9b044ae55d0875`，Windows 二进制 SHA-256 `E6651702C387886E8D23758D0334478CE2C07601A9305EC26F5513D537F5FBDA`；锁定环境不变。记录时间为 UTC 2026-09-22，对应 Asia/Shanghai 2026-09-23。

核验结果：**Windows 定向回归 PASS**。

- 两份快照除读取时刻外，全部持久状态一致；Core 重启前后同一会话等待收尾，没有提前产生结束证据。
- 用户明确观察通知不重复、断连恢复后仍为部分完成／12 分钟，随后提交显示已结束与部分完成。UI 草稿不在数据库快照中，不能把快照单独当作输入保留证据。
- 最终唯一证据为 `closure=confirmed`、`result=partial`、`actual_duration_seconds=720`；`original_report=completed` 保留。会话 ended、无活动会话，行动仍 pending，未错误标为全部完成。
- 桌面日志为一次呈现、一次有效通知回调、两次 Core 连接，与实测相符。摘要与最终对象一致，回传最终状态／桌面日志哈希匹配摘要。

逐文件哈希、身份及核验边界见 [定向回归摘要](mvp-first-vertical-slice.windows-review-regression.json)。原始包受控保留，不提交仓库。本轮未人工注入领取／回执丢包，该异常路径由 `21b4a24` 的真实 Core 自动故障注入覆盖；Windows Run 会执行 Go 测试，但其原始自动日志没有单独回传。

本次只更新证据及文档，没有新产品代码，也未重复运行无关测试。Windows 实机待办已完成，无需再要求操作者重复此轮。剩余事项为 `21b4a24` 两项修复的独立代码复审；尚无该复审通过结论，PR #32 保持 Draft，Issue #31 保持打开，并将同一状态回传产品治理追踪 Issue #10。未改变产品范围、领域规则或 ADR，不自行 merge 或进入 I-02。
