# 执行支持 MVP（首个可验证垂直切片）

本目录是按 [MVP 构建就绪文档](../docs/product/mvp-build-readiness.md) 已确认的两个黄金路径直接构建的实现：

- **必要设置切片**：导入方案原文 → Agent 生成可追溯草案 → 方案审阅工作区逐项确认 → 确定性变更确认 → 智能体核心原子启用权威用户方案。
- **首要执行闭环**：计划开始时间送达开始干预（立即开始 / 我已经开始 / 改到具体时间 / 今天不做）→ 会话与首次检查点原子建立 → 检查点三类操作 → 可跳过收尾确认 → 执行证据 + 稳定退出。

同时覆盖：开始宽限与唯一低显著跟进、安静时段抑制（不扩大权限）、被动界面按执行窗口过期、检查点无回应时跟踪结束（沉默保持未知，ADR-0016）、Core/PC 重启后的单一合并恢复干预（ADR-0012）、单一前台执行上下文与未决记录并存（ADR-0026）。

## 结构

```
app/
├── agent_core/    # Python 智能体核心：唯一权威状态（SQLite）、确定性调度、恢复、回环 API
├── desktop/       # Wails v3 薄宿主：进程守护、一次性 bootstrap 交接、托盘、通知、置顶小窗
└── scripts/       # 端到端验证脚本
```

## 运行

前置：Windows 10 x64 + WebView2；Python 3.12（首次需创建 venv）。

```powershell
# 1. 准备核心环境（一次性）
cd app\agent_core
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. 构建宿主
cd ..\desktop
go build -o bin\app-desktop.exe .

# 3. 运行
.\bin\app-desktop.exe
```

宿主自动启动 `app/agent_core/.venv` 中的 Python 核心，通过一次性 bootstrap 文件完成动态回环端点与临时令牌交接（令牌只存在于宿主与核心内存，不落盘、不进日志）。

## 模型配置（可选）

方案草案生成使用 PydanticAI（ADR-0005），在应用"设置"页配置 OpenAI 兼容的 Base URL / API Key / 模型名；配置保存在应用数据目录的 `model_config.json`，不进入数据库与日志。模型不可用时草案进入失败状态并保留原文，可重试——执行闭环完全不依赖模型。

开发期可用 `ADHD_FAKE_DRAFT=1` 环境变量启用预置草案脚手架（不属于产品功能）。

## 验证

```powershell
# 单元测试（领域转换、原子性、调度生命周期、恢复、API 认证）
cd app\agent_core
.venv\Scripts\python.exe -m pytest tests\ -q

# 端到端（真实核心进程 + HTTP/WS + 完整黄金路径）
cd app
python scripts\e2e_check.py
```

## 边界说明

- 本实现不等价于 B-03/B-04 正式领域模型与验收套件；领域对象与状态机是从已确认黄金路径推导的最小实现。
- 首个 MVP 明确不做：LLM 阻碍支持、日终复盘、剩余精力、方案调整建议、执行补记、多日重新进入、桌面活动推断（完整清单见构建就绪文档）。
- 本地回环与临时令牌证明的是启动交接与避免意外持久化，不是针对同权限本地进程的威胁模型隔离（与 V-02 结论一致）。
