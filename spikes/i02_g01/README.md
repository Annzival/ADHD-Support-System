# G-01 隔离关联与重启实验

> 当前隔离候选：ADR-0058 源码 `bc24f2a`／证据 `647a404`，Windows 回传核对 `c4ec817`；Linux 与 Windows 隔离矩阵各 48/48 PASS。它们不代表生产集成或 I-02 PASS。复验入口：[结果与独立 Windows 步骤](../../docs/implementation/results/i02-g01-accepted-boundary-validation.md)。在上述历史隔离源码上显式使用 `I02_G01_CONTRACT=ADR-0058` 运行新预期；当前生产集成已改变正式协议，不在当前 checkout 重跑旧隔离矩阵；旧报告和历史 commit 保留。本目录始终是隔离实验，不被生产启动器导入。

> 以下为第一轮 `62bc99a` 的机制说明。第二轮源码 `9848b29` 加入保留 OS 进程句柄，原 `TestG01RestartBeforeRegistration` 在原断言下通过；新的 `TestG01RestartRevalidation/exit_after_check_before_commit` 在当时严格边界下失败。该历史结果见 [第二轮报告](../../docs/implementation/results/i02-g01-restart-revalidation.md)。第一轮失败报告和摘要保持原样。

本目录与 `desktop/i02_g01_spike_test.go` 仅供 Issue #33 有界验证。生产启动器不导入此目录；不修改生产表、回执守卫或命令白名单。实验端点使用现有回环 HTTP 验证和 Go bridge；正式 pump 经测试专用 transport 将结果转到 `/spike/result`，并用独立的内存结果交回逻辑验证取消后重试。设备调用是返回布尔结果的替身，不能证明 Windows 呈现或阅读。

实验 Core 是独立 Python 子进程，宿主是独立 Go 测试子进程；父测试通过管道控制顺序、终止并等待进程、启动新进程。运行材料仅经受控临时文件和管道交接，不打印令牌。临时目录含真实 Core 数据库和单独的 `experiment.sqlite3`。后者保存实验许可、调用关联、报告、事实与命令结果，不是生产 schema。

以下命令仅适用于第一轮源码 `62bc99a`（仓库根目录，锁定环境），用于复现旧 FAIL；不是当前 ADR-0058 的运行入口：

```bash
I02_G01_SPIKE=1 I02_DELIVERY_PROBE=1 go -C desktop test -race -count=1 -timeout 120s -v ./...
# 单独复现已知失败：预期命令非零退出，不能把观察到的 200 改成验收答案。
I02_G01_SPIKE=1 go -C desktop test -race -count=1 -timeout 30s -run '^TestG01RestartBeforeRegistration$' -v
```

`I01_TEST_PYTHON` 可指定已核验的 Python 3.12.3。没有显式实验开关时诊断跳过；这不意味着候选通过。宿主 helper 只由测试父进程使用 `G01_SPIKE_HOST` 启动，不手工单独运行。

第一轮 `62bc99a` 候选的历史失败：Core 只保存“最后登记的宿主”，新宿主已经启动但尚未登记时，旧请求可以先到达并被保存。失败用例保留期望 409／零报告的断言，实际 200／一条报告必须报 FAIL。实验没有把登记完成重新定义成产品所说的进程重启。

许可关联、每许可一次调用、每尝试一次报告、同命令原结果查询、内容冲突拒绝和保守未知顺序可以独立评估；登记运行标识不能单独承担重启证明。关闭界面用同一宿主内事件模拟，仅证明未重建进程不改变运行身份，不是 Wails 托盘实测。故障父进程保留的待重放字节是网络延迟输入，不是新增宿主持久日志。

每个用例输出一行 `G01_OBSERVATION`。机器摘要由 `summarize.py` 从受控原始输出提取；结果和 Windows 最小步骤见 [报告](../../docs/implementation/results/i02-g01-verification.md)。完成矩阵后停止，不接入生产逻辑。
