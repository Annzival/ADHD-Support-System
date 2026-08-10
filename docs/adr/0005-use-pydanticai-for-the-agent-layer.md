# Agent 层采用 PydanticAI

首版 Agent 层采用 PydanticAI，不使用 OpenAI Agents SDK、LangChain 或 LangGraph。这样既能获得类型化且可更换供应商的模型交互，也能有意地将任务调度、持久工作流状态和产品授权规则保留在应用自身的控制之下。
