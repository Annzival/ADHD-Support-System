# I-01：首个 PC 确定性执行闭环

## 当前结论

**等待 Windows 验收。** Linux 实现与自动检查已完成；Windows 10 实机尚未运行，不能报告整体 I-01 PASS。此结果不代表完整 MVP、正式 dogfooding 准入或 I-02 启动。

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
| Windows 目标 | Windows 10 22H2 / 19045 x64、Python 3.12.3 x64、Go 1.25.0、Wails v3.0.0-beta.8、Fixed WebView2 151.0.4129.78 x64 | 尚无本次实机证据，沿用 V-01R、V-02、V-03 锁定环境 |

Linux Go 1.25.0 下载包按 go.dev 官方 SHA-256 核验。浏览器补充检查最初因未安装对应浏览器／缺运行库而未启动；补齐仅本地测试运行库、显式使用现有 Linux Chrome 后通过。没有据此升级 Windows、Wails、Go、Python 或 WebView2。

## 场景结果

以下 PASS 只指表中自动层。凡需 Windows 的行均仍为“等待”，不把测试参数未覆盖的 I-02 分支写成 PASS。

| 场景 | 自动检查与实际结果 | Windows 对应步骤／状态 |
| --- | --- | --- |
| EX-01 | PASS：唯一开始干预；会话与检查点联合创建；完成后等待收尾；完成／跳过后唯一证据、无活动会话，后续确认安排可以开始。`test_execution_golden_path.py`、`test_atomicity.py` | A/B；等待 |
| EX-02 | PASS：打开、取消、缺少确认均无会话；确认时长后首次检查时间正确。Python + `frontend.test.mjs` 实际界面操作 | C；等待 |
| SES-02 完成分支 | PASS：检查点前／后完成 × 完成／跳过收尾四种组合；原检查点立即失效，等待收尾继续占位置。`test_execution_golden_path.py` | A/B；等待 |
| AT-01 本阶段 | PASS：开始、完成报告、完成收尾、跳过收尾每个写边界故障回滚；事务中途子进程退出码 71 后保持完整旧状态。`test_atomicity.py` | 自动证据已具备；Windows 脚本重跑同套测试 |
| AT-02 本阶段 | PASS：成功后丢失响应、重启再用同 ID 返回原结果，状态／事件／调度不重复；前端实际重试原命令。`test_atomicity.py`、`test_transport.py`、前端测试 | D + Windows 自动重跑；等待 |
| AT-03 本阶段 | PASS：开始／完成／收尾竞争只允许一份结果；完成收尾与跳过竞争不产生相互矛盾证据；第二行动在执行中／等待收尾均被拒绝，释放后可开始。`test_atomicity.py` | Windows 自动重跑；不包含改期、续行、恢复竞争 |
| REC 适用部分 | PASS：真实 Core 重启保留数据库身份、同一会话和检查时间、等待收尾或持久结束；旧主动尝试失效不补发。`test_execution_golden_path.py`、`test_delivery_and_recovery.py`、`test_transport.py` | D；等待；不宣称完整 REC-01～12 |
| DESK-03 | PASS（Linux）：HTTP／WebSocket 缺失、错误、旧令牌拒绝，旧连接失效，新发现信息重连；Go bootstrap 超时回收子进程和交接目录。`test_transport.py`、`bridge_test.go` | D + Windows 自动重跑；Windows 网络／宿主整合等待 |
| DESK-04 本阶段 | PASS（Core）：有效对象解析、已解决／过期通知上下文拒绝并返回现状，无重复会话。原生通知回调、焦点与小窗尚无实机证据 | A/B/C；等待 |

补充检查：全部完成／部分完成可区分，原完成报告不被覆盖；实际开始、结束和未填用时保持未知。完整历史更正与版本迁移并未实现。

## 自动检查汇总

- Python：17 个测试方法通过；包含上述参数化分支、写入故障、并发和真实进程检查。
- Go：3 项测试通过；`go vet ./...` 通过。
- 嵌入式前端：2 项真实浏览器／Core 交互测试通过。
- Windows amd64 目标 `go build` 通过；未运行该二进制。
- JavaScript 语法、PowerShell AST、`git diff --check` 通过。

原始自动输出留在本次 Linux checkout 的 `.scratch/i01-checks/`；已提交摘要仅含工具版本、结果、源文件／输出／二进制 SHA-256，不含令牌、个人方案、绝对路径或未脱敏日志。Windows 尚无原始包或成功摘要；其数据与证据将在操作者自己的 `.i01-runs/` 中受控保存，按实机步骤回传。

## 限制、未决与回传

1. 尚需真实 Windows 的通知送达与激活、焦点、小窗关闭重开、原生关闭收尾，以及与正式 Core 集成后的重新连接和持久结束证据。当前不申请合并或 Ready。
2. 开发夹具固定一个 4 小时窗口，这是明确测试数据，不是新增产品默认值。超过该窗口时旧操作拒绝并显示本阶段不可用；自动到期收束、无回应较弱跟进、恢复干预与切换属于 I-02，未在此伪造完成。正式观察不可使用本切片。
3. 确认行动仅限合成夹具。I-03 的真实导入、LLM／供应商集成未开始；I-02 其他分支、开机启动及完整宿主回归、I-04 观察准入也未开始。
4. 不覆盖真实 PC 重启、异常断电、数据库损坏／备份恢复、其他 Windows 版本、同权限恶意进程或公开分发。
5. 当前未发现必须改变产品范围／领域模型／ADR 的冲突，无新增产品治理决策请求。回传内容是本次技术 checkpoint 与 Windows 证据缺口，不改变 Issue #10 已确认的构建就绪结论。

下一步仅为 Windows 验收及本 I-01 范围内的必要修正。收到证据后逐项核验，未收到则保留 checkpoint 等待；不自动进入 I-02，不自行 Ready 或合并。

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
