# I-02 当前生产覆盖映射

本表更新原 37 项映射，不覆盖历史检查点。当前生产源码及运行哈希见 [生产结果](i02-g01-production-integration.md)。Python／Go／浏览器是不同证据层；全部 Windows 生产操作仍 NOT_RUN，旧隔离 48/48 不计入此表。浏览器本轮通过，但历史 ECONNRESET 根因仍未确认，等待独立复审判断验收影响。

G/A/D/T/UI/宿主、L 的文件缩写沿用 [I-02 总报告](mvp-deterministic-branches-recovery.md#当前-37-项覆盖清单)。窗口步骤 A～H 见 [Windows 手册](../windows-i02.md)。表中的参数化断言是原 I-02 回归，新 G01 行使用正式生产数据库和命令路径。

| 场景 | 已实现并验证／测试入口及参数 | 仍需处理 |
| --- | --- | --- |
| EX-01 | G 全链路；UI 原开始／完成／两类收尾保留；L 新分支同一活动位置 | Windows A；G01-U01/正常指标见下表生产测试 |
| EX-02 | G 未确认、取消、确认；UI 主窗／小窗时长输入和取消，无半会话 | Windows B |
| EX-03 | L `ex03`：已有估时仍确认剩余时长、拒绝未确认、来源与实际开始未知；UI 确认／取消 | Windows B |
| EX-04 | L `ex04`：回顾完成后全部／部分／跳过，无检查点、时长未知；UI 回顾入口 | Windows C 两轮 |
| EX-05 | L `ex05`：后继、原时间和行动引用、旧送达取消；AT 逐写故障；UI 确认及取消改期 | Windows D |
| EX-06 | L `ex06`：仅当前安排与决定事实，其他安排和行动不变，无会话／包／后继；UI | Windows D |
| EX-07 | L `ex07_08`、D/宿主：正常首次回执、最多一次较弱跟进、不产生第三次，原请求／响应丢失重试保留 | G01-U/R/C 自动层见下表；Windows E 原生强弱 |
| EX-08 | L `ex07_08`：宽限时安静／离线／下一项到来，不补发，无推断结果 | Windows E 的原生部分；其余受控时钟自动验证 |
| EX-09 | L `ex09`：窗口／T0+D／本地次日零点，期限早于宽限；过期旧入口拒绝，行动仍未知 | Windows F；无窗口入口可另用 WithoutWindow |
| EX-10 | L `ex10`：有／无活动会话时单一前台，旧入口被动保留、取消旧跟进；UI 多安排 | Windows G 焦点与置顶 |
| SES-01 | L `ses01`：同会话后继链、原检查时间、同 ID 重试；另测三种缺确认保持完整快照；UI 续行 | Windows A |
| SES-02 | G 完成前／后检查点；L `ses02` 暂停前／后、旧续行拒绝；等待收尾仍占位置；UI | Windows A/B |
| SES-03 | G 全部／部分及原报告；L `ses03` 后续合成版本指针变化不改旧事实；UI 原两个页面草稿断连回归 | Windows A/C；版本变化是隔离夹具，不是 I-03 方案启用测试 |
| SES-04 | L `ses04` 完成／显式跳过暂停收尾、最小包和未知进展；UI 暂停后宿主关闭钩子 | Windows B 原生关闭 |
| SES-05 | L `ses05_and_rec04` 完成／暂停 × 窗口／下一项／零点，最早边界、重复恢复无重复证据／包；自动命令逐写故障 | Windows F；零点由可控时钟验证 |
| SES-06 | L `ses06_rec03` 检查点首次及一次较弱跟进、窗口／检查点日期零点未知结束，无证据／包 | Windows F |
| SES-07 | L `ses07` 追加内容／原因／时间，原事实保留、逐写故障与重试；`rec06` 更正后完成拒绝恢复；UI | Windows A |
| REC-01 | L `rec01_02_08_09`、D/T：同库身份、未确认旧尝试失效、来源不变复用；UI 重连 | Windows H 真实 PC 重启 |
| REC-02 | 同上：未过期被动保留／已过期未知，不重放；L `ex09` 三种期限 | Windows F/H |
| REC-03 | G 同会话未来检查点；L `ses06_rec03` 被动核对和过期未知；`return_same_session` 返回不重计时并取消恢复呈现 | Windows F/H |
| REC-04 | L `ses05_and_rec04` 未到／已到边界重启，完成／暂停去重；G 等待收尾持久化 | Windows F/H |
| REC-05 | L `rec05_06` 包→新安排／会话／检查点／已使用，再次暂停新包关联旧包；AT 同 ID 重试；UI 包继续 | Windows B |
| REC-06 | L `rec05_06` 旧 P 继续仍引用 P、当前 Q 不移动；`rec06_archive` 未使用归档原事实不变；UI 两个主窗选择 | Windows G |
| REC-07 | L `rec07` 已使用、已归档、已明确完成、有另一活动会话均拒绝，完整快照不变 | Windows G 可观察拒绝 |
| REC-08 | L `rec08_defer` 仅错过开始、暂不决定后重启安静、无虚构会话；UI 被动返回 | Windows G |
| REC-09 | L `rec09_each_source` 会话／包／安排／当前版本变化四支，旧命令拒绝且新来源重核；UI 读取新状态 | Windows G/H；版本切换由合成夹具隔离 |
| REC-10 | L `rec10_11_12` R09 原子切换，A 未知无证据／包，B 独占；UI 真 Core 切换入口 | Windows H |
| REC-11 | L 缺两类确认、逐写故障、同 ID 重试、旧切换不得覆盖完成报告；UI 取消／确认 | Windows H |
| REC-12 | L 提交后重开同库原 ID 返回原 B，旧 A 检查点失效；T 提交丢 HTTP 响应；宿主原通知核验 | Windows H 真实重启及旧通知 |
| DESK-01 | 宿主原单实例／托盘／关闭机制保留；UI 两页关闭收尾先保存，失败可重试 | 等待 Windows：小窗置顶／恢复、单实例、关闭主窗留托盘 |
| DESK-02 | 受限 Core 守护保留，增加当前用户登录启动配置／清理及真实重启脚本；Windows 交叉构建通过 | 等待 Windows：守护次数、登录启动、同库 PC 重启 |
| DESK-03 | T/宿主：回环 HTTP/WS、令牌与重连；新命令白名单仅 Core 执行；前端真实 HTTP | 等待 Windows 宿主整合，Wails 不访问 SQLite |
| DESK-04 | Core 对过期／解决／改期旧上下文拒绝；宿主通知向 Core 核验，主窗定位目标；UI 状态刷新 | 等待 Windows 通知实际跳转／焦点；迟到结果接纳已转入下表生产测试 |
| DESK-05 | UI 主窗两侧独立展开、暂停包／切换／暂不决定；小窗仅打开主窗、不承载恢复选择 | 等待 Windows 载体、原生通知辅助返回 |
| AT-01 | A 旧命令保留；L 9 类新增联合命令每次写入故障及提交前子进程退出；另测更正／归档、过期／自动收尾／未知结束／跟进每次写入回滚 | Windows 同库进程／PC 恢复；方案启用不属本阶段 |
| AT-02 | A/T/UI/宿主旧重试；L 新联合命令、自动命令、更正／归档提交后重开同库同 ID 返回同结果、整库快照不变 | G01-R/U/C 生产事务重试已测；Windows 恢复 |
| AT-03 | L 不同命令四对：开始／改期、续行／完成、包恢复／包恢复、切换／完成；A 旧竞争保留 | Windows 表现；SQLite 竞争已在 Linux 真实临时库验证 |


## G01-R/U/C 的生产路径补充

P = `tests/acceptance/test_g01_production.py`；N = `test_g01_processes.py`；H = `desktop/g01_delivery_test.go`。P 的存续替身与 N 的真实进程明确分层；H 使用正式 HTTP、Core、SQLite、pump，设备 API 返回为替身。它们不读取隔离摘要来断言生产通过。

| 行为 | 实际入口与参数 | 证据边界／Windows |
| --- | --- | --- |
| G01-R01 | P `r01_r02`：Core／宿主／两者 × 未提交；N `actual_core_exit`、`native_exit` 检查前真实退出、新宿主未登记 | 临时正式库保留；Windows 当前源码 NOT_RUN |
| G01-R02 | 同上已提交三支；N `committed_response_lost`；H `response_loss` | 数据库已有报告／原命令才返回；HTTP 失败不推断回滚 |
| G01-R03 | P `r03_mixed`：Core／宿主，已存与未存混合；`existing_database` 旧 schema／原命令可读 | 不清库、不重建领域；Windows 同库步骤 H |
| G01-R04 | H `window_close`；N `window_close` 活进程控制 | 自动层不证明原生窗口；Windows g01WindowClose |
| G01-U01 | H `during_call`、`after_return`、`request_loss`；P `u01` 完整领域快照不变 | 未知顺序、不计机会，不用墙钟比较定顺序 |
| G01-U02 | P `u02` 原 ID／新 ID 同报告去重、冲突内容；H 两种丢包原字节重试；P `conflicting_reports` 真 SQLite 竞争 | 一次报告／事实；不同新命令仍核验实例 |
| G01-U03 | P `u03_no_permission`、`u02` 错许可／尝试／Core／宿主／库／实例／调用／来源；H `CancelledBeforeCall` 领取前／调用前取消 | 不将按钮点击当 API 结果；零新增调用 |
| G01-C01 | N `after_check`：真实退出且替代进程未登记；P `c01` 存续替身确定暂停点 | 同一原事务一笔提交，不承诺时间上限 |
| G01-C02 | N 检查前真实退出；P `c02` 已死／未知实例／存续不可用 | 整库无半更新；不只查登记值 |
| G01-C03 | P `c03_each_write` 每次写入失败，`rollback_retries` 活宿主重试／新 Core；N `actual_core_exit` 真进程受控退出 | 已提交与未提交依数据库区别，资格不继承 |
| 首次绑定 | N `first_binding`、`registration_to_open`：成功、打开前／后退出、登记到打开退出、错／旧挑战、PID 复用替身；H `InitialBinding` 真宿主校验函数 | 真实退出与复用替身分开；不是同权限恶意进程防护 |
| 正常送达与指标 | P `normal_result`、`followup_does_not_count`；H normal／api_failure；D/L 原首次与较弱跟进 | 一干预一次机会，正常进入延迟保留；Windows g01NormalDelivery |
| I-01 保留 | delivery_test.go 领取／结果请求和响应丢失、负结果、慢领取不阻断心跳；UI 两页同会话收尾草稿 | 旧 opt-in 实验跳过不是验收通过，也未计入生产覆盖 |

未知顺序报告不生成精确进入延迟；正常顺序由原事务尚未解决的上下文及后续用户事务确定。P2 修复后的正常延迟使用经核对的同机 QPC／CLOCK_BOOTTIME 样本及同 Core 运行期，不是墙钟差或显示／阅读时间；计时依据不足仅将时间指标标为未知。未实现任何新的观察仪表盘或正式 dogfooding。

## OBS-01 时间指标 P2 补充（源码 3f7820a）

| 分支 | 生产路径断言 | 证据层 |
| --- | --- | --- |
| 正常、宽限内／边界／外 | `test_delivery_timing.elapsed_normal_boundaries_and_wall_jumps`：0/599/600/601 秒，机会 1、进入 true | Python 可控双时钟 PASS |
| 墙钟前跳／回拨且差值非负 | 同测试：实际 10 秒／700 秒分别保留 immediate／delayed，不使用 610／100 秒墙钟差 | Python PASS；修复前失败输出保留 |
| 旧记录缺依据、非法／不匹配／范围外、读失败 | `wall_clock_alone`、`missing_invalid_or_unbounded_samples`：null/unknown，其他事实保留 | Python PASS |
| Core 重启与旧完整样本对 | `core_restart_does_not_mix_epochs`：跨期不接续，旧完整对只读保留，原命令返回 | Python PASS；原真实进程重启回归保留 |
| 宿主新运行／重复报告 | `host_replacement_cannot_replace_committed_timing`、正常分支原命令重试；既有 G01 重启／冲突／逐写回滚 | Python PASS；不篡改原报告 |
| 迟到且顺序未知 | `late_unknown_order_never_has_latency`：无机会、无延迟 | Python PASS |
| QPC 精度边界 | `qpc_tick_ambiguity`：零点及宽限边界 ±1 tick 未知 | 确定性替身 PASS，非 Windows 运行 |
| 真实跨进程共同计时源 | Go `TestDeliveryElapsedClockAcrossRealBridge`，正式 pump→HTTP→Core 校验开始／接收范围 | Linux PASS；Windows NOT_RUN |

本轮只修复时间证据，不改变 OBS-01 的机会或进入规则，不作为正式观察准入。Windows 手册 A／G-01 原步骤的指标预期已同步，无新增操作。详见生产报告 P2 节及机器摘要 `p2_timing_fix`。
