# I-02：G-01 证据接纳与生产集成交接

任务类型：implementation，继续既有 Issue #33、`agent/implement-mvp-deterministic-recovery` 和 Draft PR #35；不另起实现分支，不重建既有工作。本文随独立治理 PR 发布，人工合并后才能执行下方 Prompt。产品行为仍以 ADR-0055／0057／0058 为准，本交接不新增产品决定。

## 2026-09-28 治理接纳

审查固定点：`17efadf83235c04a50c5fe62f956cc297159b817...c4ec817e343da765e5bd59d4186390e4a7362031`，仅审查 ADR-0058 隔离候选及证据，不是 PR #35 全量代码复审。

- [结果报告](https://github.com/Annzival/ADHD-Support-System/blob/c4ec817e343da765e5bd59d4186390e4a7362031/docs/implementation/results/i02-g01-accepted-boundary-validation.md)：Linux 48/48 PASS；Windows 隔离候选 48/48 PASS 为操作者回传。Windows 矩阵源码为 `647a404`，摘要工具为 `77a43d1`，证据归档为 `c4ec817`。
- [Windows 回传摘要](https://github.com/Annzival/ADHD-Support-System/blob/c4ec817e343da765e5bd59d4186390e4a7362031/docs/implementation/results/i02-g01-accepted-boundary-windows-attestation.json)记录 Windows 10 22H2 x64（19045）、锁定 Python／Go、原日志及摘要哈希。完整原日志和 Windows 摘要由操作者保留，治理没有独立重算这些文件，也没有亲自运行 Windows。
- 治理核对 Linux 摘要的 10 个来源哈希、Windows 与 Linux 矩阵源码一致性、摘要工具 Git／CRLF 字节哈希，并运行两个换行校验测试，均通过。换行修复只影响摘要采集，无需重跑已通过的 Windows 矩阵。
- Standards：1 项 P2，`spikes/i02_g01/README.md` 仍将旧失败称为“当前”或“最新”，须在原 PR 修正；Spec：0 项。该文档问题不否定矩阵结果，也不阻塞生产集成授权，但须在 PR #35 完成前修正。

结论：接纳上述隔离证据，G-01 的构建前可行性阻塞已解除。六项构建就绪门槛重新满足；继续暂停产品 grilling。**这不等于生产接纳已实现、I-02 PASS 或 PR #35 适合合并。** 两轮旧 FAIL 保留，不用新契约改写其历史。

生产完成前仍缺：真实 Core／宿主路径集成及原子性验收、I-02 全部必要场景、原生 Windows 通知／窗口／宿主及真实 PC 重启。最近浏览器回归为 12 PASS／1 FAIL（`embedded overlay loads Wails runtime before native close delivery`，`fetch failed / read ECONNRESET`），原因未定位；不能用矩阵 PASS 或简单重跑覆盖。

## 完整续接 Prompt

```text
继续现有 I-02 的 implementation 工作；你是独立技术执行 session，不继承产品治理身份。本轮将已验证的 G-01 机制接入真实应用，并完成既有 I-02 验收，不继续扩展隔离实验。

开始条件与准备：
1. 先检查工作树、Issue #33、Draft PR #35；保护已有修改和 checkpoint，沿用 agent/implement-mvp-deterministic-recovery。核实 docs/implementation/plans/i02-g01-production-integration.md 已在远端 main，再正常合入 main；尚未合并则返回等待，不从未合并治理分支取得实现授权。
2. 完整阅读 AGENTS.md、CONTEXT.md、Grilling 发布规则、原 I-02 交接、本文、ADR-0055／0057／0058，以及领域模型、转换矩阵和验收场景。其余原 I-02 引用继续适用。
3. 读取 c4ec817 的分层验证报告与 Windows 回传摘要，保留两轮 FAIL、研究及旧源码锚点。隔离候选 PASS 不等于生产通过；Windows 原日志无需仅为换行摘要修复重跑。

交付问题：能否在真实 Core、正式宿主和同一权威 SQLite 中保存允许的迟到设备报告，同时保持旧操作失效、幂等、失败回滚、运行身份与领域状态边界，并通过完整 I-02 验收？

范围内与实施顺序：
1. 修正 spikes/i02_g01/README.md：历史失败说明及其运行命令标注适用 commit；当前入口指向 ADR-0058 报告。保留旧失败，不把它们描述为当前候选结论。
2. 集成 Core 的发送许可、调用／结果关联、原宿主实例绑定与结果保存。使用正式 SQLite 和事务，不把 experiment.sqlite3、/spike 路由或测试控制接口引入生产。宿主仍只负责设备调用、进程／连接及交回设备结果，不持有领域权威状态或调度规则。可逆的 schema／模块设计由执行者决定；已有数据库可继续打开并保留状态，不能清库或重建夹具冒充恢复。
3. 接入正式宿主的首次实例绑定、设备调用和结果重试路径。只接纳 Core 先前授予同一次尝试、且对应实际调用结果的报告；用户点按钮不证明提醒已呈现。保持取消新发送与保存已发生结果的区别。覆盖关闭窗口但进程未退出、真正退出／重启、断连、重复及冲突报告。
4. 按 ADR-0058 验证原事务通过关联和存续检查后可提交；检查时已退出或实例不明拒绝；回滚／新事务不能继承检查资格；新 Core 不补存旧未提交报告；已提交的同命令同内容返回原结果。以数据库提交判断保存，而非 HTTP 成功。不要补写检查到提交的时间上限。
5. 报告保存、去重与命令结果保持同事务一致；迟到报告不能恢复旧按钮、新发通知、改写任务／会话／领域调度。顺序未知不计合格机会或精确响应延迟；同时回归原有正常送达和成功指标，不能把隔离实验中全设为未知的简化复制成所有生产送达的规则。
6. 把隔离矩阵涉及的 G01-R/U/C 行为转为真实生产路径测试，保留首次绑定反例、竞争与保存失败；更新原 37 项场景及参数覆盖映射。按 Core 集成、宿主集成、自动回归、Windows 实机分别保存可复核 checkpoint。
7. 在本实现线程定位浏览器 ECONNRESET 失败，记录原因和相称修复／证据。不得仅因重跑变绿就宣称原因消失；若只能确认环境限制则明确保留，回传是否足以验收由独立复审判断。
8. 更新 Windows I-02 手册和证据采集，交操作者在锁定环境验证当前生产源码构建的原生通知、正确上下文、窗口／托盘、单实例、启动项、Python 守护及真实 PC 重启。隔离 Windows 48/48 不替代这些验收；记录源码、二进制哈希、环境和同库恢复身份。

范围外：不修改产品范围／ADR，不改变权威状态归属，不新增宿主持久结果库、权限或服务器，不实现 I-03／I-04、LLM、正式 dogfooding；不重新研究严格提交协调。原 I-02 非目标继续适用。

验收与退出：
- 原 I-02 全部必要场景及 G01-R/U/C 都须关联生产路径测试或实机步骤；I-01 回归、幂等、原子性、重启和错误转换保持通过，不能仅复用隔离矩阵作为正式验收。
- 仓库根目录现有自动入口：python3 -m unittest discover -s tests/acceptance -v；go -C desktop test -race ./...；go -C desktop vet ./...；npm test --prefix desktop；git diff --check。Windows 构建／操作命令以更新后的 windows-i02.md 为准，测试数量不作为完成指标。
- 无 Windows 条件或等待操作者时，提交并推送 checkpoint，交付可复制步骤后停止等待；不得外推 Linux 或交叉构建结果。
- 同一路径连续三次没有新增证据、必须扩大权限或发现产品／ADR 冲突时，保存复现并回传 Issue #33 与直接委托者，不自行放宽要求。范围完成即停止，不进入 I-03。

交付与回传：
更新 docs/implementation/results/mvp-deterministic-branches-recovery.md、37 项及新增行为映射、Windows 手册与脱敏证据；区分历史隔离 PASS、生产自动测试和实机结果，原始日志不混入治理文档。更新 Issue #33 和原 Draft PR #35；每个合格 checkpoint commit 后 push，多行正文用 UTF-8 文件和 --body-file，写入后读回。保持 Draft，不 Ready／merge／关闭 Issue。
最终回传 PASS／FAIL／BLOCKED、源码与证据 commit、实际命令和结果、未解决失败、有无产品／ADR 冲突。完整实现通过后仍须独立代码复审及用户人工审查合并；不要自行把本轮授权解释为已通过验收。
```
