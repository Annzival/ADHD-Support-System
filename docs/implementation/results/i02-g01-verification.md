# I-02 G-01 有界验证结果

## 结论

**FAIL（隔离候选机制），不是 I-02 产品验收。** 30 个参数化分支中 29 支通过，1 支揭示宿主重启识别缺口。已完成本轮矩阵并停止，不启用生产接纳规则、不修改领域文档或 ADR、不将 PR #35 标为可合并。

具体失败：旧宿主已经结束，新宿主已启动并运行，但新宿主的登记请求尚未到达 Core。此时放行在传输中滞留的旧结果，Core 仍保存“上一次登记的宿主标识”，因此返回 200 并新增实验报告。已确认的规则要求不补存重启前未提交结果；测试仍断言 409 和零报告，没有把观察到的错误行为改成预期。

这不是新的产品偏好问题，也未发现 ADR 冲突；是候选机制尚不能完整落实 ADR-0057。不能把“登记已完成”重新解释为“进程已经重启”，也不能要求用户重新选择是否跨重启保存。

## 起点、范围与隔离

沿用 [Issue #33](https://github.com/Annzival/ADHD-Support-System/issues/33)、[Draft PR #35](https://github.com/Annzival/ADHD-Support-System/pull/35) 和原分支。启动工作树干净；已核实 PR #38 合并为 `065e8fb`，交接已进入远端 main。正常 merge 为 `7ed43b3`，没有冲突，保留 `7834bdb`、`f50af6e`、`50b17d8`。

已重读 AGENTS、CONTEXT、发布流程、ADR-0052/0055/0057、转换／验收矩阵、I-02 交接、G-01 交接和旧提案。[旧提案](../plans/i02-late-delivery-proposal.md)仍是历史候选，里面“取舍待确认”的文字不覆盖 PR #38 已合并决定；本轮以合并后的 ADR-0057 和 G01-R/U 预期为准。

- `spikes/i02_g01/server.py`：只在显式实验进程中挂接 `/spike/*`，复用生产 HTTP 鉴权；真实 Core 操作仍走原 `/v1/*`。原调度由受控时钟触发。
- `desktop/i02_g01_spike_test.go`：生产 Go bridge 和 deliveryPump 不改动；测试专用 transport 在领取成功后建立实验许可，把设备结果转到隔离端点；额外的内存交回逻辑独立于已取消的发送工作。
- 生产 Core 使用原临时数据库；实验许可、调用关联、报告、事实和命令结果使用另一个临时 `experiment.sqlite3`。没有修改生产 schema、路由、回执守卫或依赖。
- Core 和宿主分别为真实 Python／Go 子进程。测试通过 Kill、Wait 和重新启动验证进程边界，不仅替换字符串。关闭窗口反例只是同一宿主进程内的控制事件，不是 Wails 原生关闭实测。
- API 调用是布尔返回替身；宿主记录本地事件序号。父测试保存旧请求字节用于模拟网络滞留／重放，不是新增宿主持久待交回日志。不能据此宣称重启宿主可自行找回旧请求。

## 候选核对机制及实际证明范围

1. 生产领取和当前上下文核验通过后，实验 Core 保存唯一许可，关联数据库、尝试、目标与原版本、Core／宿主运行标识。调用前再次核验当前尝试；每许可只能登记一次调用。许可不是已发送结果。
2. 宿主只有执行了设备回调并返回后才产生结果信封，包含许可、调用 ID、本地返回序号、布尔结果和稳定命令 ID。仅点击或无法关联调用的输入被拒绝。这里信任同权限的设备桥报告，不防御恶意宿主伪造 API 调用；字段存在本身不是操作系统发送证明。
3. 结果事务先按原命令 ID 核对完整请求并返回已提交原结果，再对未提交结果验证许可、运行标识、调用及序号。每尝试一份报告、一条实验事实；命令结果同事务保存。相同身份改内容拒绝，保存失败回滚；换命令但报告相同不增加报告／事实。
4. 所有结果的真实发送顺序、机会资格和是否看见均为 `unknown`，实际发送时间及精确延迟为 null；Core 接收时间单独保存。故意输入前后倒退的宿主墙钟仍不改变结果，不比较跨进程单调时钟。夹具能证明“回调进入→用户请求完成→回调返回”等**受控程序顺序**，不能据此证明 Windows 内部呈现顺序。精确分类不是保存报告的前提。
5. 登记后的 Core／宿主运行变化能够拒绝旧未提交结果；已提交原命令仍可返回。**但仅靠最后登记值不能识别宿主已经启动却尚未登记的时间段**，因此第 5 点不是完整的重启方案。

生产域快照在每次历史报告核验前后必须完全相同，包括状态、事件、调度和引用；用户开始后旧上下文保持 409。结果报告不修改会话、不重开入口、不产生发送任务。所有已执行分支重发次数为 0。

## 逐支矩阵

每个参数分支的输入事件顺序、关联字段摘要／哈希、预期及实际状态、报告数、调用数、重启边界和原因见 [机器摘要](i02-g01-verification.json)。下表列出全部 30 支，没有隐藏失败或用跳过制造全绿。

| 分支 | 输入顺序／核对结论 | 结果／补充场景 |
| --- | --- | --- |
| normal | 许可→调用返回→保存结果→用户回应；一份报告；真实时间仍未知 | PASS；A02/AT-02 |
| claim_loss_cancel | 领取响应丢失前用户回应，随后读取已取消状态；零 API 调用 | PASS；U03、不得恢复发送 |
| before_call | 许可→用户回应→调用前核验拒绝；零调用、零报告 | PASS；U03 |
| during_call | 回调进入→用户回应→回调返回→结果；许可／调用对应，保存未知顺序报告 | PASS；U01 |
| after_return | 回调返回→用户回应→结果；同运行保存、不计机会 | PASS；U01 |
| request_loss | 结果请求未到 Core→用户回应→独立内存结果重试 | PASS；U01/U02 |
| response_loss | 结果已提交但响应丢失→用户回应→同 ID 原结果 | PASS；U02/AT-02 |
| window_close | 结果留内存→同进程关闭界面事件→重试保存 | PASS（非原生窗口）；R04 |
| api_failure | 设备替身明确返回 false，只记录该设备报告；不由缺失推断失败 | PASS；关联控制支 |
| click_only | 有领取但只有用户点击，无关联设备调用结果 | PASS：拒绝；U03 |
| wrong_permit | 结果许可 ID 错配 | PASS：拒绝；U03 |
| wrong_attempt | 同许可改尝试身份 | PASS：拒绝；U03 |
| wrong_core | 篡改许可中的 Core 身份 | PASS：拒绝；U03 |
| wrong_host | 篡改宿主身份 | PASS：拒绝；U03 |
| wrong_database | 篡改数据库身份 | PASS：拒绝；U03 |
| wrong_call | 无匹配调用 ID | PASS：拒绝；U03 |
| conflict_command | 已存原命令 ID、改设备结果内容 | PASS：拒绝、不覆盖；U02 |
| conflict_attempt | 换命令 ID、同尝试冲突设备结果 | PASS：拒绝、不覆盖；U02 |
| duplicate_new_command | 换命令 ID、同一份相同报告 | PASS：仍一份报告／事实；U02 |
| rollback | 报告／事实写入后、命令结果提交前注入失败；再重试 | PASS：先完全回滚、后一次保存；AT-01/02 |
| core_before | 未提交→真实 Core 重启→宿主重连→交旧结果 | PASS：拒绝；R01 |
| core_after | 已提交丢响应→Core 重启→原命令 | PASS：返回原结果；R02 |
| host_before | 未提交→宿主退出→新宿主登记→交旧字节 | PASS：拒绝；新宿主无内存结果；R01 |
| host_after | 已提交丢响应→新宿主登记→夹具重放原命令 | PASS：原结果；非宿主自行找回；R02 |
| both_before | 两个进程重启并登记→旧未提交结果 | PASS：拒绝；R01 |
| both_after | 两个进程重启并登记→已提交原命令 | PASS：原结果；R02 |
| mixed_core | 已存开始尝试报告＋未存检查点报告并存→Core 重启 | PASS：前者保留、后者拒绝，同会话／检查点／调度保留；R03 |
| mixed_host | 上述混合状态→宿主重启并登记 | PASS；R03 |
| mixed_both | 上述混合状态→两者重启并登记 | PASS；R03 |
| host_restart_before_registration | 新宿主已运行但未登记→滞留旧请求到 Core；要求 409/零报告，实际 200/一份报告 | **FAIL；R01 尚不完整** |

正常支及所有成功交回支还重试相同命令，要求结果完全相同且实验快照不变。错误支要求报告／命令／事实均无半更新。混合支保留既有数据库身份、方案、行动、安排、会话、检查点与有效调度；只按原恢复规则使未提交送达失效，不把缺失写成用户失败。

## 最小失败复现与退出

```text
Core C / 宿主 H1：领取许可 L，设备调用返回，结果请求暂留在传输中
用户开始命令已提交，旧操作失效
H1 被终止并等待退出；启动 H2，H2 已能处理控制输入
暂不让 H2 的运行登记到达 Core
将 H1 的原请求字节交给 Core C
期望：不补存；实际：C 仍认为 H1 是当前宿主，新增一份实验报告
```

单支和最终全矩阵各复现一次，均有同一明确证据；没有继续三次无新增证据的调试循环。矩阵已完成，按交接停止。失败是隔离实验新增记录，不是生产状态被错误写入；生产回执守卫未放宽。

## 运行、环境与回归

Linux x86_64、Python 3.12.3、SQLite 3.45.1、Go 1.25.0；浏览器和 Wails 沿用 I-02 锁定安装，无升级。本轮实验源码 commit `62bc99a`；来源文件及原始输出 SHA-256 见机器摘要。原始日志在 `.scratch/i02-checks/` 受控保留至复审结束；临时库自动清理，不提交令牌、个人内容或原始数据库。

在仓库根目录：

```bash
I02_G01_SPIKE=1 I02_DELIVERY_PROBE=1 .scratch/toolchain/go/bin/go -C desktop test -race -count=1 -timeout 120s -v ./...
# 单支复现：应非零退出；这是未修复候选缺口，不是工具调用成功就算 PASS。
I02_G01_SPIKE=1 .scratch/toolchain/go/bin/go -C desktop test -race -count=1 -timeout 30s -run '^TestG01RestartBeforeRegistration$' -v
/usr/bin/python3 -m unittest discover -s tests/acceptance -v
I01_TEST_GO="$PWD/.scratch/toolchain/go/bin/go" I01_BROWSER_EXECUTABLE=/home/Parzival/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome LD_LIBRARY_PATH="$PWD/.scratch/browser-libs/extracted/usr/lib/x86_64-linux-gnu" npm test --prefix desktop
.scratch/toolchain/go/bin/go -C desktop vet ./...
```

结果分层：

- G-01 实验：29 PASS、1 FAIL，完整 Go 命令非零退出。helper 的父测试占用分支不作为产品用例；实验未开启时的 skip 也不计 PASS。
- 既有 Go 送达丢包／负回执／桥接等回归及原四支诊断通过。旧诊断仍只是旧实现观察，不替代新验收。
- Python 46 个方法通过。浏览器初次运行有 2 支 `UND_ERR_SOCKET`（Core 重启和具体改期），保留原失败输出；未改产品或测试，重跑 13/13 通过。不能据重跑声称已经定位或修复间歇连接问题，作为既有回归稳定性限制回传。
- Go vet 通过，Windows 测试二进制交叉编译通过；都不是 Windows API 运行证据。

## Windows 最小步骤（NOT_RUN）

本轮 Linux 结果足以暴露候选缺口，不需要等待 Windows 才回传 FAIL。以下仅补分层设备证据，不扩展实机任务或升级依赖。

1. 在既有 Windows 10 22H2/19045 x64、Python 3.12.3 x64、Go 1.25.0、Wails beta.8、Fixed WebView2 151.0.4129.78 的干净本任务 checkpoint，运行下面同一隔离矩阵；它仍使用设备回调替身。若无现有 race C 工具链可去掉 `-race` 并记录限制，不为本轮安装升级。

```powershell
$env:I02_G01_SPIKE = '1'
$env:I01_TEST_PYTHON = 'D:\Tools\Python312\python.exe' # 换成已核验路径
New-Item -ItemType Directory -Force .scratch\i02-g01 | Out-Null
go -C desktop test -count=1 -timeout 120s -run '^TestG01(BoundedSpike|MixedCommittedAndUncommitted|RestartBeforeRegistration)$' -v 2>&1 | Out-File -Encoding utf8 .scratch\i02-g01\matrix.txt
Get-FileHash -Algorithm SHA256 .scratch\i02-g01\matrix.txt
Remove-Item Env:I02_G01_SPIKE
Remove-Item Env:I01_TEST_PYTHON
```

2. 需要补充实际 Wails API 表现时，按 [I-02 Windows 手册](../windows-i02.md)用新合成目录执行 A 轮正常送达，以及 E 轮关闭小窗／托盘恢复。沿用正式宿主，不将实验路由接入它。记录同一轮源码／二进制哈希、`presentation_requested` 的上下文及 `notification_submitted`、实际观察到的通知或未观察到通知、关闭前后宿主 PID。API 返回成功与操作者看见分开记录；不知道出现时刻就填未知。
3. 点击开始后再点击旧通知，核验只显示当前状态；关闭主窗留托盘后回到同一会话。保存前后快照和脱敏事件，按手册 Collect，退出后清理本轮登录启动设置（若曾启用）。原始资料本机保存，回传摘要和哈希。

这组原生步骤不控制 Windows API 调用中的用户回应，也不验证候选迟到接纳，因为正式逻辑未启用。精确呈现时刻、读取时刻、任意交错下的原生行为全部 NOT_RUN／未知，不能用旧 I-01 PASS 或模拟关闭代替。

## 推荐与转交主线程

建议保留已验证的最小部分：不可变许可与调用关联、发送和结果重试分离、每尝试唯一报告、原命令先查询再查运行资格、冲突拒绝与同事务保存、未知顺序不计机会。它们不需要更精确时钟，也不需要宿主持久日志。

**不建议把当前登记运行标识机制直接转入生产。** 下一技术候选需让 Core 获得独立于“新宿主主动登记”的运行存续依据，例如结合操作系统进程实例身份与退出观测，并在未提交结果提交路径核对；证据不足时不能只凭旧登记值放行。这只是下一项技术建议，尚未实现或证明，尤其还须测试退出观测延迟、PID 复用、结果事务与退出交错，以及重启后的原命令查询。不能把这项建议包装成已经解决，也不把字段名／数据结构交给用户选择。

另一个未证明范围是最后一次发送校验与真实设备调用之间的任意并发空隙；本轮只证明已控制到调用前核验的取消会阻止调用。未来集成须确保保存历史结果不会使发送权限复活，本报告没有作更强保证。

提交给当前治理线程的结论：产品决定已明确且没有发现冲突；本轮技术候选 FAIL，有具体的跨重启反例。请核对证据后决定后续独立验证／正式实现授权；本 session 在矩阵完成处停止，不自动扩大实验或进入生产实现。I-02 仍未 PASS，Windows 原生验收仍未完成。
