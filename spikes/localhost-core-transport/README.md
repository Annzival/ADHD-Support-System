# V-02 localhost Core 传输最小验证包

这是 Issue #17 的独立 technical spike 阶段 A 产物，不是正式 MVP 代码，也不定义正式领域 API。

## 验证边界

该包只验证以下传输与启动边界：

- Wails 宿主启动 Python Core 测试替身；
- Core 只绑定动态分配的 127.0.0.1 端口；
- 宿主通过一次性启动交接取得当前端点和临时令牌；
- 带认证的 HTTP 与 WebSocket 使用预生成的假上下文 ID 往返；
- 缺失、错误、上一运行的令牌被拒绝；
- Core 不可用、启动交接超时和一次重启都有可诊断的非就绪结果；
- Core 重启后，旧 WebSocket 与旧令牌失效，宿主重新交接后恢复往返；
- 原始令牌不进入 Git、普通日志、机器可读摘要或前端。

它不包含用户方案、下一步行动、执行会话、干预、数据库、调度、LLM、模型调用、联网 API、TLS 或正式产品状态。

## 已选择的握手机制

本次只实现一种机制：one_time_bootstrap_file。

1. Wails 宿主在当前证据运行目录下创建不可预测的一次性临时目录，并将其中尚不存在的 handoff.json 路径传给 Python Core。
2. Core 先以端口 0 绑定 127.0.0.1，在内存中生成本运行临时令牌，然后将端点、dynamic 标记和令牌原子写入该文件。
3. 宿主只接受 http://127.0.0.1:<dynamic-port>，读取后立即删除文件及其临时目录；令牌只留在宿主和 Core 的内存中。
4. 自动验证会让 Core 故意延迟发布交接文件，确认宿主记录 bootstrap_timeout_not_ready 而不伪造就绪。

这证明的是同一台 PC、同一用户会话中的启动交接和避免意外持久化/日志泄露，不是针对已拥有同一用户权限的恶意本地进程的安全边界。localhost 与临时文件路径都不应被表述为这类威胁模型下的完全隔离。

第一次机制尚未在 Windows 失败，因此没有实现第二种机制。只有 Windows 证据明确证明该机制本身不可行时，Issue #17 才允许新增第二种最小机制。

## 文件与自动检查

| 路径 | 用途 |
| --- | --- |
| main_windows.go | 真实 Wails v3 宿主；启动后自动运行验证并退出。 |
| agent_core/agent_core_stub.py | 仅回环、动态端口的 Python 假 Core。 |
| agent_core/test_agent_core_stub.py | 平台无关的 HTTP、WebSocket、拒绝、重启和日志泄露测试。 |
| scripts/verify_static_contract.py | 检查锁定版本、传输形状、边界禁项和 PowerShell 编码约束。 |
| scripts/*.ps1 | Windows 环境、构建、自动运行、验证、打包与清理步骤。 |
| MANUAL-CHECKLIST.md | Windows 执行者的有限步骤和回传内容。 |

PowerShell 脚本刻意保持 ASCII。V-01 的实机证据表明，含中文的 UTF-8 无 BOM PowerShell 5.1 脚本可能被按错误代码页读取；中文说明保留在本 README 和结果文档中。

远程 Linux 默认没有 Go/Wails 工具链。阶段 A 使用隔离的锁定 Go 1.25.0 做一次 Windows x64 交叉编译检查，同时运行 Python 测试和静态契约；这些都不能被写成 Windows 编译现场或 Wails 集成已通过。

## Windows 10 22H2 x64 执行

只在 Issue #17 更新中指定的 checkpoint、交互式 Windows 10 22H2 x64 桌面会话执行。不要用 WSL、Windows 11、远程无桌面会话或其他 checkpoint 代替。

前置条件是锁定的 Go 1.25.0 x64、Python 3.12.3 x64（含 Python Launcher）、Wails v3.0.0-beta.8 与 WebView2 Fixed Version Runtime 151.0.4129.78 x64。不要升级这些版本。

在仓库根目录确认 checkpoint 后执行：

```powershell
git rev-parse HEAD
Set-ExecutionPolicy -Scope Process Bypass
cd spikes\localhost-core-transport
.\scripts\Test-PowerShellScriptParsing.ps1
.\scripts\Install-WailsCli.ps1
.\scripts\Install-WebView2FixedRuntime.ps1
.\scripts\Check-WindowsEnvironment.ps1
.\scripts\Build-Spike.ps1
.\scripts\Start-Spike.ps1
```

Start-Spike.ps1 会短暂显示真实 Wails 窗口、完成自动验证并退出。不要手工修改代码、端口、令牌、日志或结果文件来追求通过。任何命令失败都停止该次尝试，保留 .evidence，在 MANUAL-CHECKLIST.md 中记录实际结果。

成功后，打包最新运行：

```powershell
$run = Get-ChildItem .evidence\runs -Directory | Sort-Object Name | Select-Object -Last 1
.\scripts\Collect-Evidence.ps1 -RunDirectory $run.FullName
```

脚本会输出脱敏摘要路径和原始 ZIP 的 SHA-256。通过约定的私有渠道回传 ZIP、脱敏 JSON 和 SHA-256；不要把 ZIP、.evidence、.tools、bin、.spike-run.json 或临时令牌提交 Git。

## Windows 后的停止点

- Windows 自动检查全部通过时，只表示可供本 session 核验的候选证据；最终 PASS 仍须由本 session 对回传包、摘要、哈希和 checkpoint 身份链核验后写入。
- 任一必需行为失败时，记录 FAIL，不要开始第二种机制，除非证据表明首次握手本身不可行。
- 缺少目标环境、原始证据、摘要或哈希时，记录 BLOCKED。
- 完成一次可核验证据后停止；不开始 V-03 或 MVP implementation。
