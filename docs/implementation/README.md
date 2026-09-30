# I-01 开发运行说明

本实现对应 [Issue #31](https://github.com/Annzival/ADHD-Support-System/issues/31)，只覆盖首个 PC 确定性执行闭环。它使用隔离开发夹具，不含真实方案导入，不可用于正式 dogfooding；Windows 操作见 [实机验收步骤](windows-i01.md)，结果见 [结果报告](results/mvp-first-vertical-slice.md)。

当前状态：**I-01 验收及修复后的独立复审通过，PR #32 已由用户合并**（2026-09-23，`9fcd766`）。旧证据和限制保留，无需重做定向回归；完整 MVP 尚未交付。下一阶段见 [I-02 独立交接](plans/mvp-deterministic-branches-recovery.md)，本运行说明仍仅覆盖 I-01。

## 组成与边界

- `agent_core/`：Python 3.12.3 标准库实现。SQLite 保存当前记录、命令结果、成功事件、调度与执行证据；不调用 LLM。
- `desktop/`：Go 1.25.0、Wails `v3.0.0-beta.8` 薄宿主和嵌入式 HTML/JS。前端经宿主无领域逻辑的 HTTP 桥提交 Core API；宿主以认证 WebSocket 读取 Core 状态、传递呈现请求，并机械守护 Core。无 SQLite 访问、无领域调度、无模型调用。
- `tests/acceptance/`：领域与真实进程协议检查，全部使用临时数据库。`desktop/tests/` 对嵌入式前端作补充浏览器测试，不构成 Web/PWA 产品。
- `scripts/acceptance/windows-smoke.ps1`：锁定环境、构建、预置夹具、启动、重启 Core、记录状态和收集脱敏摘要。不自动判定 Windows PASS。

沿用交接报告认可的 Windows 10 22H2 x64 / 19045、Go 1.25.0、Python 3.12.3 x64、Wails beta.8、Fixed WebView2 151.0.4129.78 x64；没有升级这些目标版本。Node／Playwright 只用于 Linux 的补充前端检查，不是桌面运行依赖。

## 自动验收

仓库根目录执行；使用锁定 Go 的可执行文件或把其 `bin` 放入 PATH：

```bash
python3 -m unittest discover -s tests/acceptance -v
cd desktop
go test -v ./...
go vet ./...
GOOS=windows GOARCH=amd64 go build -o ../.scratch/i01-desktop.exe .
cd ..
node --check desktop/frontend/app.js
git diff --check
```

这是交接建议 `pytest` 入口的等价实现，使用标准库 `unittest`，无需 Python 第三方安装。单独执行黄金路径：

```bash
python3 -m unittest discover -s tests/acceptance -p 'test_execution_golden_path.py' -v
```

可选的嵌入式前端自动交互检查：

```bash
npm ci --prefix desktop
desktop/node_modules/.bin/playwright install chromium
npm test --prefix desktop
```

浏览器需具备其 Linux 运行依赖；可用 `I01_BROWSER_EXECUTABLE` 指向已安装的 Chromium。`I01_TEST_PYTHON` 可指定锁定 Python 路径；`I01_TEST_GO` 可指定 Go 路径（默认 `go`）。测试从锁定 Go 模块读取真实 Wails runtime，验证页面发送就绪消息后能处理宿主关闭脚本；只替代原生消息接收端，不能据此宣称 Windows 叉号已通过。测试用临时本机 HTTP 适配层和真实 Python Core 驱动嵌入式客户端，不部署网站，不测试 Wails 原生事件或 Windows 通知。

## 开发夹具

脚本使用新的 `.i01-runs/` 子目录。手工测试 Core 可使用：

```bash
python3 -m agent_core seed --data-dir .i01-runs/example --confirm-development-fixture --start-delay 45
python3 -m agent_core inspect --data-dir .i01-runs/example
```

该显式操作确认的是合成 P/A/a：行动“开发验收：在空白文档写下一行测试文字”、约定开始时间、已确认 60 秒时长、4 小时测试窗口。来源为 `I01 synthetic fixture v1`；来源、确认方式、安排数值和成功事件同事务保存。`--without-duration` 创建未确认时长的对照夹具。已有非空目录拒绝重建，`serve` 要求开发标记；不会读取个人数据库或导入个人方案。自动化中的第二行动只用于验证唯一活动位置，不是新增生产设置 API。

4 小时是明确测试夹具的执行窗口，不是新增产品默认期限。不要把它当作用户日常安排。这个阶段尚未实现 I-02 的自动到期收束／完整恢复：超出窗口后界面和 Core 明确拒绝旧操作，保留原事实，不伪造完成、暂停或未知退出转换。下一次验收新建目录，不手工修复旧库。

## 命令与持久化

Core 仅绑定 `127.0.0.1:0`。宿主在开发目录下创建随机交接目录，Core 以原子文件发布端点和每运行随机令牌，宿主消费后删除目录。HTTP 和 WebSocket 均用 Authorization header；前端不会收到令牌，普通日志和数据库不保存令牌。这个机制仅针对同机同用户，不宣称抵御同权限恶意进程。

| API | 用途 |
| --- | --- |
| `GET /v1/state` | 读取一致性事务快照、对象版本、事件及当前会话 |
| `POST /v1/commands` | 提交唯一 `command_id`、`kind`、`target`、预期 `version` 和 `payload` |
| `POST /v1/context` | 重新核验通知中的对象、类型、版本及期限；旧通知返回 409 与当前状态 |
| `GET /v1/events`（WebSocket） | 认证连接后发送 `{"kind":"snapshot"}`，接收权威状态及送达请求；宿主只呈现 Core 请求 |

I-01 用户命令为 `start`、`report_complete`、`finish_closure`、`skip_closure`。送达命令为 `delivery_claim`、`delivery_receipt`；它们不代表用户在场或执行。开机／重连错过的主动尝试不补发。已确认时长从当前提交时刻建立首次检查点；无时长时，只有确认本次时长后才联合建立。

`BEGIN IMMEDIATE` 串行校验和写入；当前记录、成功事件、命令结果与必要调度同事务提交。数据库唯一索引守住活动会话、当前检查点、每安排一个开始干预、每会话一份结果证据。失败整体回滚；同一命令 ID 与相同参数返回原结果，复用 ID 改参数拒绝。冲突请求返回当前状态，客户端不会显示成功；不确定网络结果保留原命令 ID 供重试。

应用进入时刻、报告时刻和收尾时刻是应用操作事实，不冒充现实开始、结束或用时。收尾可明确全部完成或细化部分完成；原完成报告保留。跳过只保存原报告能支持的最小事实。等待收尾占用活动位置，关闭收尾通过同一跳过命令保存成功后才隐藏。

## 已知边界

完整的开始校正、改期、今天不做、续行、暂停包、无回应跟进、自动期限收束、恢复干预／切换、旧版本选择和历史更正留给 I-02；未提供的命令明确拒绝。开机启动及完整五项宿主回归亦不在本阶段完成声明中。I-03 导入和供应商集成、I-04 集成与观察准入均未开始。

SQLite 架构为首个开发切片；没有旧产品数据迁移、备份恢复或断电可靠性承诺。JSON 记录保留对象类型、稳定身份和版本，关系由 Core 命令统一维护；以后表结构调整属于实现选择，不能改变产品对象或历史事实。

## I-02 当前实现与运行

I-02 在独立 Draft PR #35 实现确定性分支、期限、会话与恢复；上文 I-01 历史范围保留。最新状态见 [I-02 结果](results/mvp-deterministic-branches-recovery.md)，原生操作见 [Windows I-02 手册](windows-i02.md)。G-01 推荐方案 [尚待主线程确认](plans/i02-late-delivery-proposal.md)，当前不接纳新的迟到历史回执规则，不宣称整体 PASS。

新增用户命令：`already_started`、`already_completed`、`reschedule`、`skip_today`、`continue`、`pause`、`correct_fact`、`resume_packet`、`archive_packet`、`switch_current`、`defer_recovery`、`return_previous`。全部经同一命令／版本／SQLite 事务入口，宿主只转发。系统期限由 Core 执行，HTTP 用户白名单不开放系统 tick／过期命令。

- 改期 payload 为 `confirmed=true`、具体 epoch 秒 `start_at`，可选 `window_end`；不复制已经不适用的旧窗口。
- 已开始、续行、包接续及切换都明确传 `duration_confirmed=true`、`duration_seconds`；切换另需 `confirmed=true`。
- 恢复命令目标是恢复记录及其版本；使用包另传 `packet_id`。同一事务重验两侧来源，不能直接提交任意包绕过恢复上下文。
- 更正目标是原证据，传 `result`、`content`、`reason`；原证据不修改，恢复资格从原事实与追加更正读取。
- 快照新增 `packets`、`recoveries`、`corrections`、`decisions`、`foreground`；前台由 Core 投影，页面不另决定领域优先级。

原自动命令仍可运行；新增领域用例：

```bash
python3 -m unittest discover -s tests/acceptance -p 'test_i02_lifecycle.py' -v
```

隔离开发多版本夹具示例（不是导入／正式设置）：

```bash
python3 -m agent_core seed --data-dir .i01-runs/i02-example --confirm-development-fixture --start-delay 45 --duration 600 --second-delay 90 --second-version Q --grace-seconds 30
```

`--window-seconds 0` 显式去掉窗口；`--without-duration` 去掉估时；测试可传具体时区偏移和安静区间。真实运行的本地零点由操作系统本地时区计算，测试偏移仅为确定性夹具。没有新增 Python 包或升级运行环境。

Windows 脚本现在支持 `-Stage I02`、`BeforeReboot`／`AfterReboot`；运行参数和清理步骤见手册。重启必须使用同目录和同 checkpoint；旧证据不能用重建库替代。跨平台测试中的原生呈现回调仍只是替身。
