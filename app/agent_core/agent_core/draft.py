"""方案导入草案生成（Agent 层，ADR-0005：PydanticAI）。

边界（必要设置切片）：
- Agent 只在用户既有方案边界内提出拆分或时间安排，明确标为派生内容并提供原文依据；
- 不得自行新增目标、截止日期或优先级；
- 模型不可用或输出无效时，草案进入 failed 状态并保留原文，用户可重试或更换模型配置
  （异常路径 1），系统不得因此启用方案。
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .domain import DraftCandidateAction, PlanImportDraft

# ---------------------------------------------------------------------------
# 模型配置（环境变量优先，其次应用数据目录下的 model_config.json；不入库、不入日志）


@dataclass
class ModelConfig:
    base_url: str
    api_key: str
    model_name: str

    @classmethod
    def load(cls) -> "ModelConfig | None":
        base_url = os.environ.get("ADHD_MODEL_BASE_URL", "").strip()
        api_key = os.environ.get("ADHD_MODEL_API_KEY", "").strip()
        model_name = os.environ.get("ADHD_MODEL_NAME", "").strip()
        config_path = _config_file_path()
        if config_path is not None and config_path.is_file():
            try:
                payload = json.loads(config_path.read_text(encoding="utf-8"))
                base_url = str(payload.get("baseUrl", "")).strip() or base_url
                api_key = str(payload.get("apiKey", "")).strip() or api_key
                model_name = str(payload.get("modelName", "")).strip() or model_name
            except (OSError, json.JSONDecodeError):
                pass
        if not (base_url and api_key and model_name):
            return None
        return cls(base_url=base_url, api_key=api_key, model_name=model_name)

    def save(self) -> None:
        path = _config_file_path()
        if path is None:
            raise RuntimeError("无法确定模型配置文件路径")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"baseUrl": self.base_url, "apiKey": self.api_key, "modelName": self.model_name}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _config_file_path() -> Path | None:
    if os.environ.get("ADHD_MODEL_CONFIG"):
        return Path(os.environ["ADHD_MODEL_CONFIG"])
    home = Path.home()
    for candidate in (home / "AppData" / "Roaming" / "ADHDSupportSystem", home / ".adhd-support-system"):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate / "model_config.json"
        except OSError:
            continue
    return None


def model_config_summary() -> dict[str, Any]:
    """状态摘要给 UI：绝不含 api key 原文。"""

    config = ModelConfig.load()
    if config is None:
        return {"configured": False, "modelName": None, "source": "env_or_file"}
    return {
        "configured": True,
        "modelName": config.model_name,
        "baseUrlHost": re.sub(r"^https?://", "", config.base_url).split("/")[0],
        "source": "env_or_file",
    }


# ---------------------------------------------------------------------------
# 结构化输出


class DraftCandidate(BaseModel):
    local_id: str = Field(description="候选行动的稳定短标识，例如 c1")
    title: str = Field(description="下一步行动标题，最小可观察工作单元")
    origin: str = Field(default="derived", description="original=原文明确给出；derived=Agent 派生")
    source_ref: str = Field(default="", description="对应方案原文的简短摘录依据")
    planned_start_hint: str | None = Field(default=None, description="原文暗示的计划开始时间，ISO 8601 或自然语言")
    estimated_minutes: int | None = Field(default=None, description="估时（分钟），原文没有依据时留空")


class PlanDraftOutput(BaseModel):
    original_points: list[str] = Field(default_factory=list, description="原文明确的信息要点")
    derived_points: list[str] = Field(default_factory=list, description="Agent 派生的拆解或时间安排")
    gaps: list[str] = Field(default_factory=list, description="仍待用户解决的关键缺口")
    candidate_actions: list[DraftCandidate] = Field(default_factory=list)


SYSTEM_PROMPT = """\
你是执行支持应用中的方案导入助手。用户会给你一段已有的学习或求职方案原文。
你的任务：把它整理成"方案导入草案"，供用户在审阅工作区中检查和确认。

硬性边界：
1. 只整理和拆分用户既有方案，不新增目标、截止日期或优先级；
2. 原文明确给出的行动标为 origin=original，并摘录原文依据；
3. 你提出的任务拆分或时间安排标为 origin=derived，必须给出对应原文依据；
4. 无法确定的关键信息写入 gaps（缺口），不要编造；
5. 候选行动按时间顺序排列，title 是最小可观察工作单元；
6. planned_start_hint 无法确定时留空，不要猜测具体时刻；
7. 全部输出使用简体中文。

输出必须是符合结构的 JSON。\
"""


def generate_draft(source_text: str, config: ModelConfig) -> PlanImportDraft:
    """调用 PydanticAI 生成草案；任何失败都会抛出异常，由调用方转为 failed 状态。"""

    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    model = OpenAIChatModel(
        config.model_name,
        provider=OpenAIProvider(base_url=config.base_url, api_key=config.api_key),
    )
    agent: Agent[None, PlanDraftOutput] = Agent(
        model,
        output_type=PlanDraftOutput,
        system_prompt=SYSTEM_PROMPT,
        retries=1,
    )
    result = agent.run_sync(
        f"方案原文如下：\n\n{source_text}",
        model_settings={"timeout": 120},
    )
    return _to_domain_draft(result.output)


def _to_domain_draft(output: PlanDraftOutput) -> PlanImportDraft:
    candidates: list[DraftCandidateAction] = []
    for index, item in enumerate(output.candidate_actions, start=1):
        origin = item.origin if item.origin in {"original", "derived"} else "derived"
        candidates.append(
            DraftCandidateAction(
                local_id=item.local_id or f"c{index}",
                title=item.title.strip(),
                origin=origin,
                source_ref=item.source_ref,
                planned_start_at=None,
                estimated_minutes=item.estimated_minutes,
                user_confirmed=False,
            )
        )
    return PlanImportDraft(
        original_points=[str(p) for p in output.original_points],
        derived_points=[str(p) for p in output.derived_points],
        gaps=[str(p) for p in output.gaps],
        candidate_actions=candidates,
    )


# ---------------------------------------------------------------------------
# 后台任务封装


def run_draft_job(
    service,  # Service（避免循环导入，类型由调用方保证）
    plan_id: str,
    source_text: str,
    source_version: int,
) -> threading.Thread:
    """在后台线程生成草案；完成后回写。绝不把 api key 写入错误信息。"""

    service._draft_jobs.add(plan_id)

    def _job() -> None:
        try:
            config = ModelConfig.load()
            if config is None:
                raise RuntimeError("模型未配置：请在设置中配置模型供应商后重试")
            draft = generate_draft(source_text, config)
            if not draft.candidate_actions:
                raise RuntimeError("模型没有返回任何候选行动，请重试或更换模型")
            service.complete_draft(plan_id, source_version, "ready", draft, None)
        except Exception as error:  # noqa: BLE001 - 后台任务的最终兜底
            message = _safe_message(error)
            service.complete_draft(plan_id, source_version, "failed", None, message)
        finally:
            service._draft_jobs.discard(plan_id)

    thread = threading.Thread(target=_job, name=f"draft-{plan_id}", daemon=True)
    thread.start()
    return thread


def _safe_message(error: Exception) -> str:
    text = str(error)
    if len(text) > 300:
        text = text[:300] + "…"
    return f"{type(error).__name__}: {text}" if text else type(error).__name__
