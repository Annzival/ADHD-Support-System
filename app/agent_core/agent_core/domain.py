"""最小领域模型与状态转换规则（从 MVP 黄金路径推导，实现 B-03 的最小子集）。

边界约束（来自既有 ADR，不在本模块重新发明）：

- ADR-0025/0026：开始干预提供不同操作；未决界面过期前被动保留。
- ADR-0016：沉默 = 未确认执行状态，不是失败或拒绝。
- ADR-0022/0023：一次会话检查点 + 可跳过收尾确认。
- ADR-0012：错过的干预合并为一次恢复干预，不逐条补发。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# 枚举值（以字符串存入 SQLite，避免动态导入依赖）


class PlanStatus:
    DRAFT = "draft"
    ENABLED = "enabled"
    SUPERSEDED = "superseded"


class DraftStatus:
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class ActionStatus:
    SCHEDULED = "scheduled"
    IN_EXECUTION = "in_execution"
    PENDING_CLOSURE = "pending_closure"
    COMPLETED = "completed"
    PAUSED = "paused"
    CANCELLED_TODAY = "cancelled_today"
    CANCELLED_SUPERSEDED = "cancelled_superseded"


class InterventionState:
    DELIVERED = "delivered"          # 等待明确回应（可能安静时段被抑制，仅被动界面）
    FOLLOWED_UP = "followed_up"      # 已发送唯一一次低显著跟进
    RESPONDED = "responded"          # 用户作出明确决定（终态）
    EXPIRED = "expired"              # 被动界面过期（终态，保留事实）


class FollowupState:
    NONE = "none"
    PENDING = "pending"
    DELIVERED = "delivered"
    SKIPPED_QUIET = "skipped_quiet"
    SKIPPED_SUPERSEDED = "skipped_superseded"


class SessionStatus:
    ACTIVE = "active"
    ENDED = "ended"


class SessionKind:
    START_NOW = "start_now"
    ALREADY_STARTED = "already_started"
    RESUMED = "resumed"


class SessionEndReason:
    COMPLETED = "completed"
    PAUSED = "paused"
    TRACKING_ENDED_UNCONFIRMED = "tracking_ended_unconfirmed"
    COMPLETED_BY_DEADLINE = "completed_by_deadline"


class CheckpointState:
    SCHEDULED = "scheduled"
    DELIVERED = "delivered"
    PASSIVE_ONLY = "passive_only"
    RESPONDED = "responded"
    EXPIRED_TRACKING_ENDED = "expired_tracking_ended"


class CheckpointResponse:
    COMPLETED = "completed"
    CONTINUE = "continue"
    PAUSE = "pause"


class StartResponse:
    START_NOW = "start_now"
    ALREADY_STARTED = "already_started"
    COMPLETED_DIRECT = "completed_direct"
    RESCHEDULED = "rescheduled"
    SKIP_TODAY = "skip_today"


class EvidenceOutcome:
    COMPLETED = "completed"
    PAUSED = "paused"
    UNKNOWN = "unknown"


class EvidenceSource:
    CLOSURE_CHECK = "closure_check"
    CLOSURE_SKIPPED = "closure_skipped"
    CLOSURE_DEADLINE = "closure_deadline"       # 收尾确认超时，按已有明确操作保存最小证据
    DIRECT_COMPLETED = "direct_completed"       # "我已经完成"
    TRACKING_ENDED = "tracking_ended"           # 检查点无回应，跟踪结束（非执行证据语义，仅事实）


class RecoveryChoice:
    CONTINUE_PREVIOUS = "continue_previous"
    HANDLE_PREVIOUS = "handle_previous"
    FOLLOW_PLAN = "follow_plan"
    DEFER = "defer"


class RecoveryState:
    PENDING = "pending"
    DECIDED = "decided"


# ---------------------------------------------------------------------------
# 领域异常


class DomainError(Exception):
    """非法转换或前置条件不满足；不得破坏权威状态。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code


# ---------------------------------------------------------------------------
# 状态机片段（非法转换一律拒绝）


ACTION_TERMINAL = {
    ActionStatus.COMPLETED,
    ActionStatus.CANCELLED_TODAY,
    ActionStatus.CANCELLED_SUPERSEDED,
}


def can_begin_execution(action_status: str) -> bool:
    return action_status in {ActionStatus.SCHEDULED, ActionStatus.PAUSED}


def can_direct_complete(action_status: str) -> bool:
    return action_status in {ActionStatus.SCHEDULED, ActionStatus.IN_EXECUTION}


def can_reschedule(action_status: str) -> bool:
    return action_status in {ActionStatus.SCHEDULED, ActionStatus.PAUSED}


def can_skip_today(action_status: str) -> bool:
    return action_status in {ActionStatus.SCHEDULED, ActionStatus.PAUSED}


# ---------------------------------------------------------------------------
# 截止时间计算


def surface_deadline(
    *,
    planned_start_at: datetime,
    estimated_minutes: int | None,
    execution_window_end: str | None,
    next_midnight: datetime,
    window_end_fn,
) -> datetime:
    """开始干预被动界面的过期时间：执行窗口结束、计划开始+预计时长、次日 00:00 中取最早可用项。

    计算结果允许早于当前时间：调用方据此判定错过窗口（记录失效事实，不补发）。
    """

    candidates: list[datetime] = [next_midnight]
    if execution_window_end:
        candidates.append(window_end_fn(planned_start_at, execution_window_end))
    if estimated_minutes and estimated_minutes > 0:
        candidates.append(planned_start_at + timedelta(minutes=estimated_minutes))
    return min(candidates)


def checkpoint_passive_deadline(*, delivered_at: datetime, execution_window_end: str | None, next_midnight: datetime, window_end_fn) -> datetime:
    """检查点被动核对期限：执行窗口结束与次日 00:00 中取较早者；没有执行窗口时次日 00:00。"""

    if execution_window_end:
        return min(window_end_fn(delivered_at, execution_window_end), next_midnight)
    return next_midnight


# ---------------------------------------------------------------------------
# 恢复包


@dataclass
class ResumePacket:
    action_id: str
    action_title: str
    session_kind: str
    worked_minutes: int
    note: str = ""
    started_at: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "actionId": self.action_id,
            "actionTitle": self.action_title,
            "sessionKind": self.session_kind,
            "workedMinutes": self.worked_minutes,
            "note": self.note,
            "startedAt": self.started_at,
        }


# ---------------------------------------------------------------------------
# 方案导入草案（非权威表示；权威用户方案仅在最终确认后由 enable 建立）


@dataclass
class DraftCandidateAction:
    local_id: str
    title: str
    origin: str = "derived"                  # original | derived
    source_ref: str = ""                     # 原文依据摘录
    planned_start_at: str | None = None      # ISO，可空（启用前必须确认）
    estimated_minutes: int | None = None
    user_confirmed: bool = False             # 逐项确认标志；整体确认不能代替


@dataclass
class PlanImportDraft:
    original_points: list[str] = field(default_factory=list)
    derived_points: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    candidate_actions: list[DraftCandidateAction] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "originalPoints": self.original_points,
            "derivedPoints": self.derived_points,
            "gaps": self.gaps,
            "candidateActions": [
                {
                    "localId": item.local_id,
                    "title": item.title,
                    "origin": item.origin,
                    "sourceRef": item.source_ref,
                    "plannedStartAt": item.planned_start_at,
                    "estimatedMinutes": item.estimated_minutes,
                    "userConfirmed": item.user_confirmed,
                }
                for item in self.candidate_actions
            ],
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> "PlanImportDraft":
        candidates = [
            DraftCandidateAction(
                local_id=str(item.get("localId", "")),
                title=str(item.get("title", "")),
                origin=str(item.get("origin", "derived")),
                source_ref=str(item.get("sourceRef", "")),
                planned_start_at=item.get("plannedStartAt"),
                estimated_minutes=item.get("estimatedMinutes"),
                user_confirmed=bool(item.get("userConfirmed", False)),
            )
            for item in payload.get("candidateActions", [])
        ]
        return cls(
            original_points=[str(p) for p in payload.get("originalPoints", [])],
            derived_points=[str(p) for p in payload.get("derivedPoints", [])],
            gaps=[str(p) for p in payload.get("gaps", [])],
            candidate_actions=candidates,
        )


def validate_enable_preconditions(
    *,
    draft: PlanImportDraft | None,
    draft_status: str,
    draft_based_on_version: int,
    source_version: int,
) -> None:
    """启用前的确定性校验：最终确认必须来自与当前原文一致的草案。"""

    if draft is None or draft_status != DraftStatus.READY:
        if draft_based_on_version != source_version:
            raise DomainError("source_superseded", "方案原文在草案生成后发生修改，必须基于新版原文重新生成并审阅")
        raise DomainError("draft_not_ready", "方案导入草案尚未生成完成，不能启用")
    if draft_based_on_version != source_version:
        raise DomainError("source_superseded", "方案原文在草案生成后发生修改，必须基于新版原文重新审阅")
    confirmed = [item for item in draft.candidate_actions if item.user_confirmed]
    if not confirmed:
        raise DomainError("first_action_unconfirmed", "尚未逐项确认第一项下一步行动及其计划开始时间")
    for item in confirmed:
        if not item.title.strip():
            raise DomainError("invalid_action", "已确认行动缺少标题")
        if not item.planned_start_at:
            raise DomainError("invalid_action", f"已确认行动缺少计划开始时间：{item.title}")
        if item.estimated_minutes is not None and (item.estimated_minutes < 1 or item.estimated_minutes > 24 * 60):
            raise DomainError("invalid_action", f"预计时长必须在 1 分钟到 24 小时之间：{item.title}")
