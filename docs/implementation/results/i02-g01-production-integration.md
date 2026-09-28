# G-01 正式 Core／宿主集成结果

## 当前结论

**生产自动层通过；I-02 整体验收 BLOCKED。** Windows 当前生产源码的原生通知、Wails 窗口／托盘、单实例、启动项、Core 守护及 PC 重启均为 **NOT_RUN**。此外，历史浏览器 `ECONNRESET` 根因未确认，不能宣称仅剩 Windows，是否足以验收须由独立复审判断。

本次是独立实现，不承担产品治理；未修改产品范围／ADR、模型或权威状态归属。PR #42 已人工合并，交接已在远端 main；正常合入 `a100909`。Core 检查点 `500bd04`、宿主检查点 `3cd3a5f` 已提交推送；最终源码 `c819bdf`，Python 64 方法、Go race／vet、浏览器 13 项、Windows 交叉构建、PowerShell 语法及 6 支解释器发现检查通过。源码及原始输出哈希见 [生产机器摘要](i02-g01-production-integration.json)。Draft PR #35 保持 Draft，不代表已可合并。

保留 [第一轮 FAIL](i02-g01-verification.md)、[第二轮 FAIL](i02-g01-restart-revalidation.md)、[提交边界研究](i02-g01-commit-boundary-research.md)、[ADR-0058 隔离证据](i02-g01-accepted-boundary-validation.md)和 c4ec817 的 Windows 回传。没有重跑旧 Windows 48 支，也没有把它们的 PASS 改称生产 PASS。

## 正式路径与事务

- `agent_core/host_identity.py` 在打开原进程对象后生成新挑战；正式宿主仅回答自己的运行身份和实际 PID。Core 核对完整挑战和保留对象存续后绑定。随机标签或 PID 相等不是独立依据。Windows 使用 SYNCHRONIZE 权限的进程句柄与即时等待；Linux 使用 pidfd。首次绑定的因果依据沿用已核验候选；不增加权限或对同权限恶意进程的防护声明。
- `delivery_evidence.py` 通过原 `Core.transact` 在同一权威 SQLite 中追加 `delivery_permissions`、`delivery_reports`。已有记录、事件、原命令及 database_id 保留；迁移不清库。保存报告、正常送达状态／必要跟进、成功事实和原命令结果原子提交。
- 领取时记录尝试、原目标及版本、数据库、Core／宿主运行、原实例和许可；设备调用前保存唯一调用关联，再核验当前操作仍允许发送。结果只能引用这次调用的实际返回。宿主在内存保存原请求字节，断连或丢响应只重交结果；没有新增持久结果日志。
- 结果原命令优先从数据库返回，不依赖 HTTP 是否成功。新报告在同一事务完成关联及最后存续检查；检查之后宿主退出可以完成这笔事务，检查前退出／身份不明拒绝。回滚后重新检查，新 Core 不继承资格。相同内容的新命令也不新增事实，但仍须核验运行身份；冲突拒绝。
- 历史报告不改已取消送达、行动、会话、检查点、恢复或调度，不恢复旧入口。正常回执先于用户事务时保留正常送达与跟进；迟到且顺序不能证明时保存报告，机会资格未知。不是把所有结果设为未知。
- `delivery_metrics` 是只读去重投影：同一开始干预最多一个机会，只计已有明确进入来源；回顾式完成及未知顺序报告不冒充促成进入。正常延迟使用同机墙钟的适配器返回与会话提交差值；实际显示／阅读时刻仍未知。墙钟调整不能证明顺序，没有新增检查至提交时限承诺。

生产启动器没有导入 `spikes`，没有 `/spike` 路由、实验数据库或远程测试控制接口。测试的存续替身、故障回调和受控子进程只在测试代码中组织。

## 自动证据与参数映射

[37 项及 G01-R/U/C 映射](i02-production-coverage.md)列出当前生产测试入口、参数和剩余 Windows 步骤。原 46 个 Python 验收方法、I-01 宿主领取／结果重试、负结果和两页收尾草稿测试保留；旧 receipt 夹具改为先完成正式绑定、许可及调用，不能以缺少依据的旧裸回执绕过生产守卫。

生产测试覆盖：错许可／尝试／运行／库／实例／调用及仅点击；同 ID／新 ID 重复和冲突；正常、调用中／返回后回应、请求与响应丢失；提交前后 Core／宿主／两者重启，混合已存和未存；真实退出后新宿主未登记；打开前、登记到打开、打开后退出，错／旧挑战和 PID 复用替身；最后检查后退出允许、逐写回滚、回滚活宿主重试、Core 真进程未提交退出；不同命令竞争和旧库升级。

证据层必须区分：

| 层 | 本轮内容 | 不证明什么 |
| --- | --- | --- |
| 真实生产 SQLite / 可控时钟 | 状态、引用、事件、调度、报告、原命令的原子性和幂等 | 不代表原生 API 真的显示 |
| 正式 HTTP / Go pump | 原字节重试、取消新调用与追加已发生结果分开 | 设备调用为替身 |
| Linux 真实进程 | pidfd、保留对象、退出／重新运行、Core 事务退出 | 不外推 Windows 句柄运行 |
| 确定性存续／PID 复用替身 | 可重复检查前后控制点、身份错配 | 不声称实际 OS 复用了 PID |
| 浏览器 | 真实 Core 页面操作与 Wails runtime 加载 | 不代表 WebView2、焦点、托盘或通知 |
| Windows 交叉构建 | 当前正式宿主可编译 | 不是 Windows 运行 PASS |

## 浏览器 ECONNRESET：未解决风险

历史 `g01-accepted-ui.txt` 在小窗 runtime 支记录 `fetch failed / read ECONNRESET`；原日志没有能定位请求路径或关闭方的栈信息。本轮没有升级 Node、浏览器或依赖。

按 diagnosing-bugs 的复现方式检查现有路径：

1. 原浏览器基线 13/13 通过，未复现旧失败。
2. 同一 Python HTTP Server、相同认证和 `Connection: close` 的 1,000 次串行真实请求全通过，服务端无异常输出。
3. 将唯一变量改为 32 路并发，960 次请求全通过，服务端仍无异常输出。

三个方向是连接压力、Core 退出时在途请求、测试代理上游错误传播；当前只有前者的压力对照完成，后两者尚无能把历史失败归因于它们的证据。连续三次未新增失败定位证据后，按用户停止条件停止这条诊断路径，不做推测性修复、不删除失败、不降低断言。最终正常浏览器回归再次通过也不等于根因消失。**未证明是产品缺陷，也未证明只是环境限制。** 将这一具体缺口交独立复审；如需继续诊断，推荐先在原失败的请求边界保留脱敏路径、阶段及 Core 退出信息，而不是继续无差别重跑。

受控复现材料和输出在 `.scratch/i02-checks/browser-transport-*`，摘要只记录哈希；其中临时端口／令牌没有输出或提交。当前没有提交不确定的浏览器补丁。

## 复现与 Windows 交接

仓库根目录：

```bash
python3 -m unittest discover -s tests/acceptance -v
go -C desktop test -race -count=1 -v ./...
go -C desktop vet ./...
npm test --prefix desktop
git diff --check
```

本机使用锁定 Go `.scratch/toolchain/go/bin/go`。浏览器实际命令附带已有环境，不新增依赖：

```bash
I01_TEST_GO="$PWD/.scratch/toolchain/go/bin/go" I01_BROWSER_EXECUTABLE=/home/Parzival/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome LD_LIBRARY_PATH="$PWD/.scratch/browser-libs/extracted/usr/lib/x86_64-linux-gnu" npm test --prefix desktop
GOOS=windows GOARCH=amd64 CGO_ENABLED=0 .scratch/toolchain/go/bin/go -C desktop build -o ../.scratch/i02-production-desktop.exe .
```

当前 Windows 生产验收统一按 [Windows I-02 手册](../windows-i02.md)。Run 在锁定环境运行生产自动测试、构建宿主并记录源码及二进制哈希；A～H 原生操作、真实 PC 重启和同库身份核对仍必要。新增 G-01 原生观察及报告／指标摘要，所有未做项保留 NOT_RUN。旧隔离矩阵无需重跑，合成夹具不等于正式设置。

原始输出、测试数据库及 Windows 本机路径不提交；摘要保留源码文件 Git／工作区原始字节哈希、输出哈希和来源。不把源代码换行规范化后的相等比较当作原始文件哈希。无 I-03／I-04、LLM、公开发布或正式观察。

生产自动实现检查点可供独立代码复审。完整 I-02 仍不能报 PASS，也不建议现在合并 PR #35；待 Windows 原生证据和未决风险经过独立核对后，再交用户人工审查合并。
