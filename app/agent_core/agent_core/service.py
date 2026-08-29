"""应用服务：原子命令、确定性调度与恢复扫描。

黄金路径参照 docs/product/mvp-build-readiness.md：
- 必要设置切片：导入 → 草案 → 审阅 → 逐项确认 → 变更确认 → 原子启用。
- 首要执行闭环：开始干预 → 立即开始/我已经开始 → 会话+首次检查点原子建立 →
  检查点三类操作 → 可跳过收尾确认 → 执行证据 + 稳定退出。
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable

from .clock import Clock, parse_utc, utc_now_iso
from .domain import (
    ActionStatus,
    can_reschedule,
    CheckpointResponse,
    CheckpointState,
    DomainError,
    DraftStatus,
    EvidenceOutcome,
    EvidenceSource,
    FollowupState,
    InterventionState,
    PlanImportDraft,
    PlanStatus,
    RecoveryChoice,
    RecoveryState,
    SessionEndReason,
    SessionKind,
    SessionStatus,
    StartResponse,
    checkpoint_passive_deadline,
    surface_deadline,
    validate_enable_preconditions,
)
from .store import Store, new_id

BroadcastFn = Callable[[dict[str, Any]], None]


class Service:
    def __init__(
        self,
        store: Store,
        clock: Clock,
        broadcast: BroadcastFn | None = None,
        on_plan_imported: Callable[[str, str, int], None] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock
        self.broadcast = broadcast or (lambda event: None)
        self.on_plan_imported = on_plan_imported
        self._draft_jobs: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 设置

    def update_settings(self, payload: dict[str, Any]) -> dict[str, str]:
        allowed = {"start_grace_minutes", "quiet_hours_start", "quiet_hours_end", "execution_window_end"}
        unknown = set(payload) - allowed
        if unknown:
            raise DomainError("unknown_setting", f"未知设置项：{sorted(unknown)}")
        if "start_grace_minutes" in payload:
            value = payload["start_grace_minutes"]
            if not isinstance(value, int) or not 1 <= value <= 240:
                raise DomainError("invalid_setting", "开始宽限时间必须在 1-240 分钟之间")
            self.store.set_setting("start_grace_minutes", str(value))
        for key in ("quiet_hours_start", "quiet_hours_end", "execution_window_end"):
            if key in payload:
                value = str(payload[key])
                hour, minute = value.split(":")
                if not (hour.isdigit() and minute.isdigit() and 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
                    raise DomainError("invalid_setting", f"{key} 必须是 HH:MM 格式")
                self.store.set_setting(key, value)
        self.broadcast({"type": "state_changed", "reason": "settings_updated"})
        return self.store.all_settings()

    def grace_minutes(self) -> int:
        return int(self.store.get_setting("start_grace_minutes") or "10")

    # ------------------------------------------------------------------
    # 必要设置切片

    def import_plan(self, source_text: str) -> str:
        if not source_text or not source_text.strip():
            raise DomainError("empty_source", "方案原文不能为空")
        if len(source_text) > 200_000:
            raise DomainError("source_too_large", "方案原文超过 200,000 字符上限")
        plan_id = new_id("pln")
        now = self.clock.now_iso()
        with self.store.transaction():
            self.store.insert_plan(plan_id, source_text, now)
            self.store.insert_draft(plan_id, based_on_version=1, now=now)
            self.store.record_event("plan_imported", {"planId": plan_id}, now)
        if self.on_plan_imported is not None:
            self.on_plan_imported(plan_id, source_text, 1)
        self.broadcast({"type": "state_changed", "reason": "plan_imported"})
        return plan_id

    def regenerate_draft(self, plan_id: str) -> None:
        plan = self.store.get_plan(plan_id)
        if plan is None:
            raise DomainError("plan_not_found", "方案不存在")
        now = self.clock.now_iso()
        with self.store.transaction():
            draft = self.store.get_draft(plan_id)
            if draft is not None and draft["status"] == DraftStatus.GENERATING:
                raise DomainError("draft_generating", "草案正在生成中")
            if draft is None:
                self.store.insert_draft(plan_id, int(plan["source_version"]), now)
            else:
                self.store.connection.execute(
                    "UPDATE plan_drafts SET status = ?, error = NULL, based_on_source_version = ? WHERE plan_id = ?",
                    (DraftStatus.GENERATING, int(plan["source_version"]), plan_id),
                )
            self.store.record_event("draft regeneration requested", {"planId": plan_id}, now)
        if self.on_plan_imported is not None:
            self.on_plan_imported(plan_id, str(plan["source_text"]), int(plan["source_version"]))
        self.broadcast({"type": "state_changed", "reason": "draft_generating"})

    def update_source(self, plan_id: str, source_text: str) -> None:
        if not source_text or not source_text.strip():
            raise DomainError("empty_source", "方案原文不能为空")
        now = self.clock.now_iso()
        with self.store.transaction():
            plan = self.store.get_plan(plan_id)
            if plan is None:
                raise DomainError("plan_not_found", "方案不存在")
            if plan["status"] == PlanStatus.ENABLED:
                raise DomainError("plan_enabled", "已启用的权威方案原文不可修改；请导入新方案")
            new_version = int(plan["source_version"]) + 1
            self.store.connection.execute(
                "UPDATE plans SET source_text = ?, source_version = ? WHERE id = ?",
                (source_text, new_version, plan_id),
            )
            self.store.connection.execute(
                "UPDATE plan_drafts SET status = ?, error = ? WHERE plan_id = ? AND status = ?",
                (DraftStatus.FAILED, "原文已修改：旧草案已被取代，请重新生成", plan_id, DraftStatus.READY),
            )
            self.store.record_event("plan_source_updated", {"planId": plan_id, "version": new_version}, now)
        self.broadcast({"type": "state_changed", "reason": "source_updated"})

    def complete_draft(
        self, plan_id: str, expected_version: int, status: str, draft: PlanImportDraft | None, error: str | None
    ) -> None:
        now = self.clock.now_iso()
        with self.store.transaction():
            plan = self.store.get_plan(plan_id)
            if plan is None:
                return
            current_version = int(plan["source_version"])
            if current_version != expected_version:
                self.store.update_draft_result(
                    plan_id, DraftStatus.FAILED, None, "生成期间原文已修改，草案已被取代", now
                )
                return
            self.store.update_draft_result(
                plan_id,
                status,
                _dump_json(draft.to_json()) if draft is not None else None,
                error,
                now,
            )
            self.store.record_event("draft_completed", {"planId": plan_id, "status": status}, now)
        self._draft_jobs.discard(plan_id)
        self.broadcast({"type": "state_changed", "reason": "draft_completed"})

    def draft_job_running(self, plan_id: str) -> bool:
        return plan_id in self._draft_jobs

    def patch_draft(self, plan_id: str, patch: dict[str, Any]) -> PlanImportDraft:
        now = self.clock.now_iso()
        with self.store.transaction():
            plan = self.store.get_plan(plan_id)
            if plan is None:
                raise DomainError("plan_not_found", "方案不存在")
            draft_row = self.store.get_draft(plan_id)
            if draft_row is None or draft_row["status"] != DraftStatus.READY:
                raise DomainError("draft_not_ready", "草案尚未生成，不能编辑")
            draft = PlanImportDraft.from_json(_load_json(draft_row["draft_json"]))
            _apply_draft_patch(draft, patch)
            self.store.update_draft_result(
                plan_id, DraftStatus.READY, _dump_json(draft.to_json()), None, now
            )
        self.broadcast({"type": "state_changed", "reason": "draft_patched"})
        return draft

    def confirm_candidate_action(self, plan_id: str, local_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = self.clock.now_iso()
        with self.store.transaction():
            draft_row = self.store.get_draft(plan_id)
            if draft_row is None or draft_row["status"] != DraftStatus.READY:
                raise DomainError("draft_not_ready", "草案尚未生成，不能确认")
            draft = PlanImportDraft.from_json(_load_json(draft_row["draft_json"]))
            candidate = next((c for c in draft.candidate_actions if c.local_id == local_id), None)
            if candidate is None:
                raise DomainError("candidate_not_found", "候选行动不存在")
            title = str(payload.get("title", candidate.title)).strip()
            if not title:
                raise DomainError("invalid_action", "标题不能为空")
            planned_start = payload.get("plannedStartAt", candidate.planned_start_at)
            parse_utc(str(planned_start))  # 格式校验
            estimated = payload.get("estimatedMinutes", candidate.estimated_minutes)
            if estimated is not None:
                estimated = int(estimated)
                if not 1 <= estimated <= 24 * 60:
                    raise DomainError("invalid_action", "预计时长必须在 1 分钟到 24 小时之间")
            candidate.title = title
            candidate.planned_start_at = str(planned_start)
            candidate.estimated_minutes = estimated
            candidate.user_confirmed = True
            self.store.update_draft_result(plan_id, DraftStatus.READY, _dump_json(draft.to_json()), None, now)
            self.store.record_event("candidate_confirmed", {"planId": plan_id, "localId": local_id}, now)
        self.broadcast({"type": "state_changed", "reason": "candidate_confirmed"})
        return {
            "localId": candidate.local_id,
            "title": candidate.title,
            "origin": candidate.origin,
            "sourceRef": candidate.source_ref,
            "plannedStartAt": candidate.planned_start_at,
            "estimatedMinutes": candidate.estimated_minutes,
            "userConfirmed": candidate.user_confirmed,
        }

    def unconfirm_candidate_action(self, plan_id: str, local_id: str) -> None:
        now = self.clock.now_iso()
        with self.store.transaction():
            draft_row = self.store.get_draft(plan_id)
            if draft_row is None or draft_row["status"] != DraftStatus.READY:
                raise DomainError("draft_not_ready", "草案尚未生成")
            draft = PlanImportDraft.from_json(_load_json(draft_row["draft_json"]))
            candidate = next((c for c in draft.candidate_actions if c.local_id == local_id), None)
            if candidate is None:
                raise DomainError("candidate_not_found", "候选行动不存在")
            candidate.user_confirmed = False
            self.store.update_draft_result(plan_id, DraftStatus.READY, _dump_json(draft.to_json()), None, now)
        self.broadcast({"type": "state_changed", "reason": "candidate_unconfirmed"})

    def enable_plan(self, plan_id: str) -> dict[str, Any]:
        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            plan = self.store.get_plan(plan_id)
            if plan is None:
                raise DomainError("plan_not_found", "方案不存在")
            if plan["status"] == PlanStatus.ENABLED:
                raise DomainError("plan_already_enabled", "方案已启用")
            draft_row = self.store.get_draft(plan_id)
            draft = (
                PlanImportDraft.from_json(_load_json(draft_row["draft_json"]))
                if draft_row is not None and draft_row["draft_json"]
                else None
            )
            validate_enable_preconditions(
                draft=draft,
                draft_status=str(draft_row["status"]) if draft_row is not None else DraftStatus.FAILED,
                draft_based_on_version=int(draft_row["based_on_source_version"]) if draft_row is not None else -1,
                source_version=int(plan["source_version"]),
            )
            confirmed = [c for c in (draft.candidate_actions if draft else []) if c.user_confirmed]
            for item in confirmed:
                if parse_utc(str(item.planned_start_at)) <= now_dt:
                    raise DomainError(
                        "planned_start_in_past",
                        f"计划开始时间必须晚于当前时间：{item.title}",
                    )
            previous = self.store.get_enabled_plan()
            if previous is not None and previous["id"] != plan_id:
                self.store.connection.execute(
                    "UPDATE plans SET status = ? WHERE id = ?", (PlanStatus.SUPERSEDED, previous["id"])
                )
                for row in self.store.actions_for_plan(previous["id"]):
                    self._cancel_action_locked(str(row["id"]), ActionStatus.CANCELLED_SUPERSEDED, now)
            self.store.connection.execute(
                "UPDATE plans SET status = ?, enabled_at = ? WHERE id = ?", (PlanStatus.ENABLED, now, plan_id)
            )
            created: list[str] = []
            for item in confirmed:
                action_id = new_id("act")
                self.store.insert_action(
                    action_id,
                    plan_id,
                    item.title,
                    "",
                    str(item.planned_start_at),
                    item.estimated_minutes,
                    now,
                )
                created.append(action_id)
            self.store.record_event("plan_enabled", {"planId": plan_id, "actions": created}, now)
        self.broadcast({"type": "state_changed", "reason": "plan_enabled"})
        return {"planId": plan_id, "actionIds": created}

    # ------------------------------------------------------------------
    # 开始干预回应

    def respond_start(self, intervention_id: str, response: str, payload: dict[str, Any]) -> dict[str, Any]:
        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            intervention = self.store.get_intervention(intervention_id)
            if intervention is None:
                raise DomainError("intervention_not_found", "开始干预不存在")
            if intervention["state"] not in {InterventionState.DELIVERED, InterventionState.FOLLOWED_UP}:
                raise DomainError("intervention_closed", "开始干预已结束或已过期")
            action = self.store.get_action(str(intervention["action_id"]))
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if response == StartResponse.START_NOW:
                return self._start_session_locked(action, intervention, SessionKind.START_NOW, payload, now_dt, now)
            if response == StartResponse.ALREADY_STARTED:
                return self._start_session_locked(action, intervention, SessionKind.ALREADY_STARTED, payload, now_dt, now)
            if response == StartResponse.COMPLETED_DIRECT:
                if str(action["status"]) not in {ActionStatus.SCHEDULED, ActionStatus.IN_EXECUTION}:
                    raise DomainError("invalid_transition", "当前状态不能直接标记完成")
                self._mark_intervention_responded(intervention, StartResponse.COMPLETED_DIRECT, now)
                deadline = self._closure_deadline_locked(now_dt)
                self._set_action_locked(
                    str(action["id"]),
                    status=ActionStatus.PENDING_CLOSURE,
                    pending_kind="completed",
                    closure_deadline=deadline,
                    start_settled=1,
                    now=now,
                )
                result = {"session": None, "pendingClosure": True}
                self.store.record_event("start_responded", {"interventionId": intervention_id, "response": response}, now)
                return result
            if response == StartResponse.RESCHEDULED:
                new_start = payload.get("plannedStartAt")
                if not new_start:
                    raise DomainError("missing_field", "缺少新的计划开始时间")
                new_start_dt = parse_utc(str(new_start))
                if new_start_dt <= now_dt:
                    raise DomainError("planned_start_in_past", "新的计划开始时间必须晚于当前时间")
                self._mark_intervention_responded(intervention, StartResponse.RESCHEDULED, now)
                self.store.connection.execute(
                    "UPDATE next_actions SET planned_start_at = ?, start_settled = 0, updated_at = ? WHERE id = ?",
                    (utc_now_iso(new_start_dt), now, action["id"]),
                )
                self.store.record_event("action_rescheduled", {"actionId": action["id"], "plannedStartAt": utc_now_iso(new_start_dt)}, now)
                return {"rescheduledTo": utc_now_iso(new_start_dt)}
            if response == StartResponse.SKIP_TODAY:
                self._mark_intervention_responded(intervention, StartResponse.SKIP_TODAY, now)
                self._set_action_locked(str(action["id"]), status=ActionStatus.CANCELLED_TODAY, start_settled=1, now=now)
                self.store.record_event("start_responded", {"interventionId": intervention_id, "response": response}, now)
                return {"cancelled": True}
            raise DomainError("unknown_response", f"未知回应：{response}")

    def reschedule_action(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """用户主动改期（对已过期或未决记录的显式操作，不新增主动联系）。"""

        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            action = self.store.get_action(action_id)
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if not can_reschedule(str(action["status"])):
                raise DomainError("invalid_transition", "当前状态不能改期")
            new_start = payload.get("plannedStartAt")
            if not new_start:
                raise DomainError("missing_field", "缺少新的计划开始时间")
            new_start_dt = parse_utc(str(new_start))
            if new_start_dt <= now_dt:
                raise DomainError("planned_start_in_past", "新的计划开始时间必须晚于当前时间")
            self.store.connection.execute(
                "UPDATE start_interventions SET state = ? WHERE action_id = ? AND state IN ('delivered','followed_up')",
                (InterventionState.EXPIRED, action_id),
            )
            self.store.connection.execute(
                "UPDATE next_actions SET planned_start_at = ?, start_settled = 0, updated_at = ? WHERE id = ?",
                (utc_now_iso(new_start_dt), now, action_id),
            )
            self.store.record_event("action_rescheduled_by_user", {"actionId": action_id}, now)
        self.broadcast({"type": "state_changed", "reason": "action_rescheduled"})
        return {"rescheduledTo": utc_now_iso(new_start_dt)}

    def skip_today_action(self, action_id: str) -> dict[str, Any]:
        """用户主动放下今天这一项（显式决定，不修改权威方案）。"""

        now = self.clock.now_iso()
        with self.store.transaction():
            action = self.store.get_action(action_id)
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if not can_reschedule(str(action["status"])):
                raise DomainError("invalid_transition", "当前状态不能执行该操作")
            self.store.connection.execute(
                "UPDATE start_interventions SET state = ? WHERE action_id = ? AND state IN ('delivered','followed_up')",
                (InterventionState.EXPIRED, action_id),
            )
            self.store.connection.execute(
                "UPDATE next_actions SET status = ?, start_settled = 1, pending_kind = NULL, closure_deadline = NULL, updated_at = ? WHERE id = ?",
                (ActionStatus.CANCELLED_TODAY, now, action_id),
            )
            self.store.record_event("action_skipped_today_by_user", {"actionId": action_id}, now)
        self.broadcast({"type": "state_changed", "reason": "action_skipped_today"})
        return {"cancelled": True}

    def _start_session_locked(
        self,
        action: Any,
        intervention: Any,
        kind: str,
        payload: dict[str, Any],
        now_dt: datetime,
        now: str,
    ) -> dict[str, Any]:
        if not (str(action["status"]) in {ActionStatus.SCHEDULED, ActionStatus.PAUSED}):
            raise DomainError("invalid_transition", "当前状态不能开始执行会话")
        # 同一时刻只允许一个活动执行会话（上下文竞争规则）。
        existing = self.store.active_session()
        if existing is not None:
            raise DomainError("session_exists", "已存在活动执行会话；请先完成、暂停或结束当前会话")
        estimated = payload.get("estimatedMinutes")
        if estimated is None and kind == SessionKind.START_NOW:
            estimated = action["estimated_minutes"]
        if estimated is None:
            raise DomainError("duration_required", "需要先确认本次预计时长")
        estimated = int(estimated)
        if not 1 <= estimated <= 24 * 60:
            raise DomainError("invalid_duration", "预计时长必须在 1 分钟到 24 小时之间")
        session_id = new_id("ses")
        checkpoint_id = new_id("chk")
        checkpoint_due = now_dt + timedelta(minutes=estimated)
        # 同一事务原子建立会话与首次检查点：取消或不确认时两者都不建立。
        self.store.insert_session(session_id, str(action["id"]), kind, now, estimated)
        self.store.insert_checkpoint(checkpoint_id, session_id, 1, utc_now_iso(checkpoint_due))
        self._mark_intervention_responded(
            intervention,
            StartResponse.START_NOW if kind == SessionKind.START_NOW else StartResponse.ALREADY_STARTED,
            now,
        )
        self._set_action_locked(
            str(action["id"]), status=ActionStatus.IN_EXECUTION, start_settled=1, now=now
        )
        self.store.record_event(
            "execution_session_started",
            {"sessionId": session_id, "checkpointId": checkpoint_id, "kind": kind},
            now,
        )
        return {
            "sessionId": session_id,
            "checkpointId": checkpoint_id,
            "checkpointDueAt": utc_now_iso(checkpoint_due),
            "estimatedMinutes": estimated,
        }

    def _mark_intervention_responded(self, intervention: Any, response: str, now: str) -> None:
        self.store.connection.execute(
            "UPDATE start_interventions SET state = ?, response_kind = ?, responded_at = ? WHERE id = ?",
            (InterventionState.RESPONDED, response, now, intervention["id"]),
        )

    # ------------------------------------------------------------------
    # 执行会话与检查点

    def respond_checkpoint(self, checkpoint_id: str, response: str, payload: dict[str, Any]) -> dict[str, Any]:
        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            checkpoint = self.store.get_checkpoint(checkpoint_id)
            if checkpoint is None:
                raise DomainError("checkpoint_not_found", "检查点不存在")
            session = self.store.get_session(str(checkpoint["session_id"]))
            if session is None or session["status"] != SessionStatus.ACTIVE:
                raise DomainError("session_not_active", "执行会话不在活动状态")
            action = self.store.get_action(str(session["action_id"]))
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if response == CheckpointResponse.COMPLETED:
                if checkpoint["state"] not in {CheckpointState.SCHEDULED, CheckpointState.DELIVERED}:
                    raise DomainError("invalid_transition", "检查点已结束")
                self.store.connection.execute(
                    "UPDATE checkpoints SET state = ?, response_kind = ?, responded_at = ? WHERE id = ?",
                    (CheckpointState.RESPONDED, CheckpointResponse.COMPLETED, now, checkpoint_id),
                )
                deadline = self._closure_deadline_locked(now_dt)
                self._set_action_locked(
                    str(action["id"]),
                    status=ActionStatus.PENDING_CLOSURE,
                    pending_kind="completed",
                    closure_deadline=deadline,
                    now=now,
                )
                self.store.record_event("checkpoint_responded", {"checkpointId": checkpoint_id, "response": response}, now)
                return {"pendingClosure": True}
            if response == CheckpointResponse.CONTINUE:
                minutes = payload.get("nextCheckpointMinutes")
                if minutes is None:
                    raise DomainError("duration_required", "需要确认下一检查时间")
                minutes = int(minutes)
                if not 1 <= minutes <= 24 * 60:
                    raise DomainError("invalid_duration", "下一检查间隔必须在 1 分钟到 24 小时之间")
                if checkpoint["state"] not in {CheckpointState.SCHEDULED, CheckpointState.DELIVERED}:
                    raise DomainError("invalid_transition", "检查点已结束")
                self.store.connection.execute(
                    "UPDATE checkpoints SET state = ?, response_kind = ?, responded_at = ? WHERE id = ?",
                    (CheckpointState.RESPONDED, CheckpointResponse.CONTINUE, now, checkpoint_id),
                )
                next_id = new_id("chk")
                self.store.insert_checkpoint(
                    next_id,
                    str(session["id"]),
                    int(checkpoint["seq"]) + 1,
                    utc_now_iso(now_dt + timedelta(minutes=minutes)),
                )
                self.store.record_event("checkpoint_continued", {"checkpointId": checkpoint_id, "next": next_id}, now)
                return {"nextCheckpointId": next_id}
            if response == CheckpointResponse.PAUSE:
                if checkpoint["state"] not in {CheckpointState.SCHEDULED, CheckpointState.DELIVERED}:
                    raise DomainError("invalid_transition", "检查点已结束")
                self.store.connection.execute(
                    "UPDATE checkpoints SET state = ?, response_kind = ?, responded_at = ? WHERE id = ?",
                    (CheckpointState.RESPONDED, CheckpointResponse.PAUSE, now, checkpoint_id),
                )
                self._pause_session_locked(session, action, payload, now_dt, now)
                self.store.record_event("checkpoint_responded", {"checkpointId": checkpoint_id, "response": response}, now)
                return {"paused": True}
            raise DomainError("unknown_response", f"未知回应：{response}")

    def pause_session(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """检查点前用户随时暂停并保存恢复包。"""

        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            session = self.store.get_session(session_id)
            if session is None or session["status"] != SessionStatus.ACTIVE:
                raise DomainError("session_not_active", "执行会话不在活动状态")
            checkpoint = self.store.latest_checkpoint(session_id)
            if checkpoint is not None and checkpoint["state"] in {CheckpointState.SCHEDULED, CheckpointState.DELIVERED}:
                self.store.connection.execute(
                    "UPDATE checkpoints SET state = ?, response_kind = ?, responded_at = ? WHERE id = ?",
                    (CheckpointState.RESPONDED, CheckpointResponse.PAUSE, now, checkpoint["id"]),
                )
            action = self.store.get_action(str(session["action_id"]))
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            self._pause_session_locked(session, action, payload, now_dt, now)
            return {"paused": True}

    def _pause_session_locked(self, session: Any, action: Any, payload: dict[str, Any], now_dt: datetime, now: str) -> None:
        started_at = parse_utc(str(session["started_at"]))
        worked = max(0, int((now_dt - started_at).total_seconds() // 60))
        packet = {
            "actionId": str(action["id"]),
            "actionTitle": str(action["title"]),
            "sessionKind": str(session["kind"]),
            "workedMinutes": worked,
            "note": str(payload.get("note", "") or ""),
            "startedAt": str(session["started_at"]),
        }
        self.store.connection.execute(
            "UPDATE execution_sessions SET status = ?, end_reason = ?, ended_at = ?, resume_packet_json = ? WHERE id = ?",
            (SessionStatus.ENDED, SessionEndReason.PAUSED, now, _dump_json(packet), session["id"]),
        )
        deadline = self._closure_deadline_locked(now_dt)
        self._set_action_locked(
            str(action["id"]),
            status=ActionStatus.PENDING_CLOSURE,
            pending_kind="paused",
            closure_deadline=deadline,
            now=now,
        )
        self.store.record_event("session_paused", {"sessionId": session["id"], "resumePacket": True}, now)

    def submit_closure(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            action = self.store.get_action(action_id)
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if action["status"] != ActionStatus.PENDING_CLOSURE:
                raise DomainError("not_pending_closure", "当前没有待收尾的执行")
            pending_kind = str(action["pending_kind"] or "completed")
            skipped = bool(payload.get("skipped", False))
            actual = payload.get("actualMinutes")
            if actual is not None:
                actual = int(actual)
                if not 0 <= actual <= 24 * 60:
                    raise DomainError("invalid_duration", "实际用时必须在 0 分钟到 24 小时之间")
            note = str(payload.get("note", "") or "")
            session = self.store.active_session_for_action(action_id)
            if session is None:
                # 暂停路径的会话已在暂停时结束；收尾证据仍应关联最近一次会话。
                session = self.store.connection.execute(
                    "SELECT * FROM execution_sessions WHERE action_id = ? ORDER BY started_at DESC LIMIT 1",
                    (action_id,),
                ).fetchone()
            evidence_source = EvidenceSource.CLOSURE_SKIPPED if skipped else EvidenceSource.CLOSURE_CHECK
            self.store.insert_evidence(
                new_id("ev"),
                action_id,
                str(session["id"]) if session is not None else None,
                EvidenceOutcome.PAUSED if pending_kind == "paused" else EvidenceOutcome.COMPLETED,
                actual,
                note,
                evidence_source,
                now,
            )
            if session is not None and session["status"] == SessionStatus.ACTIVE:
                self.store.connection.execute(
                    "UPDATE execution_sessions SET status = ?, end_reason = ?, ended_at = ? WHERE id = ?",
                    (SessionStatus.ENDED, SessionEndReason.COMPLETED, now, session["id"]),
                )
            final_status = ActionStatus.PAUSED if pending_kind == "paused" else ActionStatus.COMPLETED
            self.store.connection.execute(
                "UPDATE next_actions SET status = ?, pending_kind = NULL, closure_deadline = NULL, updated_at = ? WHERE id = ?",
                (final_status, now, action_id),
            )
            self.store.record_event("closure_submitted", {"actionId": action_id, "skipped": skipped}, now)
        self.broadcast({"type": "state_changed", "reason": "closure_submitted"})
        return {"finalStatus": final_status}

    def resume_action(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """从恢复包重新进入：会话与首次检查点原子建立。"""

        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        with self.store.transaction():
            action = self.store.get_action(action_id)
            if action is None:
                raise DomainError("action_not_found", "下一步行动不存在")
            if action["status"] != ActionStatus.PAUSED:
                raise DomainError("invalid_transition", "只有已暂停的行动可以恢复")
            existing = self.store.active_session()
            if existing is not None:
                raise DomainError("session_exists", "已存在活动执行会话；请先完成、暂停或结束当前会话")
            minutes = payload.get("remainingMinutes")
            if minutes is None:
                raise DomainError("duration_required", "需要确认从现在起多久后检查")
            minutes = int(minutes)
            if not 1 <= minutes <= 24 * 60:
                raise DomainError("invalid_duration", "预计时长必须在 1 分钟到 24 小时之间")
            session_id = new_id("ses")
            checkpoint_id = new_id("chk")
            self.store.insert_session(session_id, action_id, SessionKind.RESUMED, now, minutes)
            self.store.insert_checkpoint(checkpoint_id, session_id, 1, utc_now_iso(now_dt + timedelta(minutes=minutes)))
            self._set_action_locked(action_id, status=ActionStatus.IN_EXECUTION, now=now)
            self.store.record_event("session_resumed", {"sessionId": session_id, "from": action_id}, now)
            return {"sessionId": session_id, "checkpointId": checkpoint_id}

    # ------------------------------------------------------------------
    # 恢复干预

    def run_recovery_scan(self) -> dict[str, Any] | None:
        """启动/恢复后扫描：至多生成一个合并恢复干预（确定性，不调用 LLM）。"""

        now = self.clock.now_iso()
        with self.store.transaction():
            if self.store.pending_recovery() is not None:
                return None
            active = self.store.connection.execute(
                "SELECT * FROM execution_sessions WHERE status = ? ORDER BY started_at DESC LIMIT 1",
                (SessionStatus.ACTIVE,),
            ).fetchone()
            pending_closure = self.store.connection.execute(
                "SELECT * FROM next_actions WHERE status = ? LIMIT 1", (ActionStatus.PENDING_CLOSURE,)
            ).fetchone()
            packet_session = self.store.connection.execute(
                """
                SELECT s.*, a.status AS action_status FROM execution_sessions s
                JOIN next_actions a ON a.id = s.action_id
                WHERE s.end_reason = 'paused' AND s.resume_packet_json IS NOT NULL AND a.status = ?
                ORDER BY s.ended_at DESC LIMIT 1
                """,
                (ActionStatus.PAUSED,),
            ).fetchone()
            missed = self.store.connection.execute(
                """
                SELECT a.* FROM next_actions a
                WHERE a.status = ? AND a.start_settled = 1
                  AND NOT EXISTS (SELECT 1 FROM execution_sessions s WHERE s.action_id = a.id)
                  AND a.planned_start_at <= ?
                ORDER BY a.planned_start_at
                """,
                (ActionStatus.SCHEDULED, now),
            ).fetchall()
            next_scheduled = self.store.connection.execute(
                "SELECT * FROM next_actions WHERE status = ? AND planned_start_at > ? ORDER BY planned_start_at LIMIT 1",
                (ActionStatus.SCHEDULED, now),
            ).fetchone()
            if active is None and pending_closure is None and packet_session is None and not missed:
                return None
            basis = {
                "hasActiveSession": active is not None,
                "activeSessionId": str(active["id"]) if active is not None else None,
                "hasPendingClosure": pending_closure is not None,
                "hasResumePacket": packet_session is not None,
                "resumePacket": _load_json(packet_session["resume_packet_json"]) if packet_session is not None else None,
                "missedActionIds": [str(row["id"]) for row in missed],
                "missedActionTitles": [str(row["title"]) for row in missed],
                "nextScheduledActionId": str(next_scheduled["id"]) if next_scheduled is not None else None,
                "nextScheduledActionTitle": str(next_scheduled["title"]) if next_scheduled is not None else None,
            }
            recovery_id = new_id("rcv")
            self.store.insert_recovery(recovery_id, basis, now)
            self.store.record_event("recovery_intervention_created", {"recoveryId": recovery_id}, now)
        self.broadcast({"type": "state_changed", "reason": "recovery_pending"})
        return basis

    def decide_recovery(self, recovery_id: str, choice: str) -> dict[str, Any]:
        now = self.clock.now_iso()
        with self.store.transaction():
            recovery = self.store.connection.execute(
                "SELECT * FROM recovery_interventions WHERE id = ?", (recovery_id,)
            ).fetchone()
            if recovery is None:
                raise DomainError("recovery_not_found", "恢复干预不存在")
            if recovery["state"] != RecoveryState.PENDING:
                raise DomainError("recovery_decided", "恢复干预已处理")
            if choice not in {RecoveryChoice.CONTINUE_PREVIOUS, RecoveryChoice.HANDLE_PREVIOUS, RecoveryChoice.FOLLOW_PLAN, RecoveryChoice.DEFER}:
                raise DomainError("unknown_response", f"未知选择：{choice}")
            self.store.connection.execute(
                "UPDATE recovery_interventions SET state = ?, choice = ?, decided_at = ? WHERE id = ?",
                (RecoveryState.DECIDED, choice, now, recovery_id),
            )
            self.store.record_event("recovery_decided", {"recoveryId": recovery_id, "choice": choice}, now)
            basis = _load_json(recovery["basis_json"])
        self.broadcast({"type": "state_changed", "reason": "recovery_decided"})
        result: dict[str, Any] = {"choice": choice}
        if choice == RecoveryChoice.CONTINUE_PREVIOUS and basis.get("hasResumePacket") and not basis.get("hasActiveSession"):
            result["needsDuration"] = True
            result["resumeActionId"] = (basis.get("resumePacket") or {}).get("actionId")
        return result

    # ------------------------------------------------------------------
    # 调度 tick

    def tick(self) -> list[dict[str, Any]]:
        """确定性调度扫描：到期开始干预、跟进、检查点、过期、收尾超时。"""

        changed = False
        now_dt = self.clock.now_utc()
        now = utc_now_iso(now_dt)
        quiet = self.clock.in_quiet_hours(now_dt, self.store.get_setting("quiet_hours_start"), self.store.get_setting("quiet_hours_end"))
        window_end = self.store.get_setting("execution_window_end")
        with self.store.transaction():
            changed |= self._create_due_interventions(now_dt, now, quiet, window_end)
            changed |= self._deliver_followups(now_dt, now, quiet)
            changed |= self._expire_interventions(now)
            changed |= self._deliver_due_checkpoints(now_dt, now, quiet, window_end)
            changed |= self._reconfirm_checkpoints(now_dt, now, quiet)
            changed |= self._expire_checkpoints(now)
            changed |= self._close_pending_closures(now)
        if changed:
            self.broadcast({"type": "state_changed", "reason": "scheduler_tick"})
        return []

    def _create_due_interventions(self, now_dt: datetime, now: str, quiet: bool, window_end: str) -> bool:
        rows = self.store.connection.execute(
            """
            SELECT * FROM next_actions a
            WHERE a.status = ? AND a.start_settled = 0 AND a.planned_start_at <= ?
              AND NOT EXISTS (
                SELECT 1 FROM start_interventions i
                WHERE i.action_id = a.id AND i.state IN ('delivered','followed_up')
              )
            """,
            (ActionStatus.SCHEDULED, now),
        ).fetchall()
        changed = False
        for action in rows:
            planned = parse_utc(str(action["planned_start_at"]))
            grace_deadline = now_dt + timedelta(minutes=self.grace_minutes())
            estimated = action["estimated_minutes"]
            next_midnight = self.clock.next_local_midnight(now_dt)
            deadline = surface_deadline(
                planned_start_at=planned,
                estimated_minutes=int(estimated) if estimated is not None else None,
                execution_window_end=window_end,
                next_midnight=next_midnight,
                window_end_fn=self.clock.local_window_end,
            )
            if now_dt > planned + timedelta(minutes=self.grace_minutes()):
                # 交付时机已超过开始宽限窗口：错过有效时机，不补发（ADR-0012），
                # 记录失效事实并进入恢复合并。
                self.store.connection.execute(
                    "UPDATE next_actions SET start_settled = 1, updated_at = ? WHERE id = ?", (now, action["id"])
                )
                self.store.record_event("start_window_missed_offline", {"actionId": action["id"]}, now)
                changed = True
                continue
            delivery_mode = "quiet_suppressed" if quiet else "active"
            intervention_id = new_id("int")
            self.store.insert_intervention(
                intervention_id,
                str(action["id"]),
                str(action["planned_start_at"]),
                now,
                utc_now_iso(grace_deadline),
                delivery_mode,
                utc_now_iso(deadline),
                now,
            )
            self.store.record_event(
                "start_intervention_delivered",
                {"interventionId": intervention_id, "actionId": action["id"], "mode": delivery_mode},
                now,
            )
            if delivery_mode == "active":
                self.broadcast(
                    {
                        "type": "notify",
                        "salience": "normal",
                        "title": "到计划开始时间了",
                        "body": str(action["title"]),
                        "kind": "start_intervention",
                        "actionId": str(action["id"]),
                    }
                )
            changed = True
        return changed

    def _deliver_followups(self, now_dt: datetime, now: str, quiet: bool) -> bool:
        rows = self.store.connection.execute(
            """
            SELECT i.*, a.title AS action_title, a.planned_start_at AS action_planned FROM start_interventions i
            JOIN next_actions a ON a.id = i.action_id
            WHERE i.state = ? AND i.followup_state = 'none' AND i.grace_deadline <= ?
            """,
            (InterventionState.DELIVERED, now),
        ).fetchall()
        changed = False
        for intervention in rows:
            # 下一项计划工作已经开始时，跟进直接失效（上下文竞争规则）。
            superseded = self.store.connection.execute(
                "SELECT COUNT(*) AS n FROM start_interventions WHERE delivered_at > ? AND state IN ('delivered','followed_up')",
                (str(intervention["delivered_at"]),),
            ).fetchone()
            skip: str | None
            if quiet:
                skip = FollowupState.SKIPPED_QUIET
            elif int(superseded["n"]) > 1:
                skip = FollowupState.SKIPPED_SUPERSEDED
            else:
                skip = None
            if skip is not None:
                self.store.connection.execute(
                    "UPDATE start_interventions SET followup_state = ? WHERE id = ?",
                    (skip, intervention["id"]),
                )
            else:
                self.store.connection.execute(
                    "UPDATE start_interventions SET state = ?, followup_state = ?, followup_delivered_at = ? WHERE id = ?",
                    (InterventionState.FOLLOWED_UP, FollowupState.DELIVERED, now, intervention["id"]),
                )
                self.broadcast(
                    {
                        "type": "notify",
                        "salience": "low",
                        "title": "跟进：上一步还没有回应",
                        "body": str(intervention["action_title"]),
                        "kind": "start_followup",
                        "actionId": str(intervention["action_id"]),
                    }
                )
            changed = True
        return changed

    def _expire_interventions(self, now: str) -> bool:
        rows = self.store.connection.execute(
            "SELECT * FROM start_interventions WHERE state IN ('delivered','followed_up') AND surface_deadline <= ?",
            (now,),
        ).fetchall()
        for intervention in rows:
            self.store.connection.execute(
                "UPDATE start_interventions SET state = ? WHERE id = ?",
                (InterventionState.EXPIRED, intervention["id"]),
            )
            self.store.connection.execute(
                "UPDATE next_actions SET start_settled = 1, updated_at = ? WHERE id = ?",
                (now, intervention["action_id"]),
            )
            self.store.record_event(
                "start_surface_expired",
                {"interventionId": intervention["id"], "responseKind": None},
                now,
            )
        return bool(rows)

    def _deliver_due_checkpoints(self, now_dt: datetime, now: str, quiet: bool, window_end: str) -> bool:
        rows = self.store.connection.execute(
            """
            SELECT c.*, s.action_id FROM checkpoints c
            JOIN execution_sessions s ON s.id = c.session_id
            WHERE c.state = ? AND c.due_at <= ?
            """,
            (CheckpointState.SCHEDULED, now),
        ).fetchall()
        changed = False
        for checkpoint in rows:
            deadline = checkpoint_passive_deadline(
                delivered_at=now_dt,
                execution_window_end=window_end,
                next_midnight=self.clock.next_local_midnight(now_dt),
                window_end_fn=self.clock.local_window_end,
            )
            delivery_mode = "quiet_suppressed" if quiet else "active"
            self.store.connection.execute(
                "UPDATE checkpoints SET state = ?, delivered_at = ?, delivery_mode = ?, deadline = ?, reconfirm_state = 'none' WHERE id = ?",
                (CheckpointState.DELIVERED, now, delivery_mode, utc_now_iso(deadline), checkpoint["id"]),
            )
            self.store.record_event("checkpoint_delivered", {"checkpointId": checkpoint["id"], "mode": delivery_mode}, now)
            if delivery_mode == "active":
                action = self.store.get_action(str(checkpoint["action_id"]))
                self.broadcast(
                    {
                        "type": "notify",
                        "salience": "normal",
                        "title": "检查点到了",
                        "body": str(action["title"]) if action is not None else "",
                        "kind": "checkpoint",
                        "sessionId": str(checkpoint["session_id"]),
                    }
                )
            changed = True
        return changed

    def _expire_checkpoints(self, now: str) -> bool:
        rows = self.store.connection.execute(
            "SELECT * FROM checkpoints WHERE state = ? AND deadline <= ?",
            (CheckpointState.DELIVERED, now),
        ).fetchall()
        changed = False
        for checkpoint in rows:
            # 到期只结束应用内跟踪并保存未确认事实，不推断执行结果（ADR-0016）。
            self.store.connection.execute(
                "UPDATE checkpoints SET state = ? WHERE id = ?",
                (CheckpointState.EXPIRED_TRACKING_ENDED, checkpoint["id"]),
            )
            session = self.store.get_session(str(checkpoint["session_id"]))
            if session is not None and session["status"] == SessionStatus.ACTIVE:
                self.store.connection.execute(
                    "UPDATE execution_sessions SET status = ?, end_reason = ?, ended_at = ? WHERE id = ?",
                    (SessionStatus.ENDED, SessionEndReason.TRACKING_ENDED_UNCONFIRMED, now, session["id"]),
                )
                action = self.store.get_action(str(session["action_id"]))
                if action is not None:
                    # 只保存会话跟踪结束事实与未确认执行状态；这不形成执行证据（ADR-0016）。
                    self.store.connection.execute(
                        "UPDATE next_actions SET status = ?, start_settled = 1, updated_at = ? WHERE id = ?",
                        (ActionStatus.SCHEDULED, now, action["id"]),
                    )
            self.store.record_event("checkpoint_tracking_ended", {"checkpointId": checkpoint["id"]}, now)
            changed = True
        return changed

    def _close_pending_closures(self, now: str) -> bool:
        rows = self.store.connection.execute(
            "SELECT * FROM next_actions WHERE status = ? AND closure_deadline <= ?",
            (ActionStatus.PENDING_CLOSURE, now),
        ).fetchall()
        changed = False
        for action in rows:
            pending_kind = str(action["pending_kind"] or "completed")
            session = self.store.connection.execute(
                "SELECT * FROM execution_sessions WHERE action_id = ? AND status = ? ORDER BY started_at DESC LIMIT 1",
                (str(action["id"]), SessionStatus.ACTIVE),
            ).fetchone()
            self.store.insert_evidence(
                new_id("ev"),
                str(action["id"]),
                str(session["id"]) if session is not None else None,
                EvidenceOutcome.PAUSED if pending_kind == "paused" else EvidenceOutcome.COMPLETED,
                None,
                "",
                EvidenceSource.CLOSURE_DEADLINE,
                now,
            )
            if session is not None:
                self.store.connection.execute(
                    "UPDATE execution_sessions SET status = ?, end_reason = ?, ended_at = ? WHERE id = ?",
                    (SessionStatus.ENDED, SessionEndReason.COMPLETED_BY_DEADLINE, now, session["id"]),
                )
            final_status = ActionStatus.PAUSED if pending_kind == "paused" else ActionStatus.COMPLETED
            self.store.connection.execute(
                "UPDATE next_actions SET status = ?, pending_kind = NULL, closure_deadline = NULL, updated_at = ? WHERE id = ?",
                (final_status, now, action["id"]),
            )
            self.store.record_event("closure_deadline_applied", {"actionId": action["id"]}, now)
            changed = True
        return changed

    # 检查点低显著一次再确认：grace 结束后仍无回应时最多一次
    def _reconfirm_checkpoints(self, now_dt: datetime, now: str, quiet: bool) -> bool:
        grace_cutoff = utc_now_iso(now_dt - timedelta(minutes=self.grace_minutes()))
        rows = self.store.connection.execute(
            """
            SELECT c.*, a.title AS action_title FROM checkpoints c
            JOIN execution_sessions s ON s.id = c.session_id
            JOIN next_actions a ON a.id = s.action_id
            WHERE c.state = ? AND c.reconfirm_state = 'none' AND c.delivered_at IS NOT NULL AND c.delivered_at <= ?
            """,
            (CheckpointState.DELIVERED, grace_cutoff),
        ).fetchall()
        changed = False
        for checkpoint in rows:
            if quiet:
                self.store.connection.execute(
                    "UPDATE checkpoints SET reconfirm_state = 'skipped_quiet' WHERE id = ?",
                    (checkpoint["id"],),
                )
            else:
                self.store.connection.execute(
                    "UPDATE checkpoints SET reconfirm_state = 'delivered' WHERE id = ?",
                    (checkpoint["id"],),
                )
                self.broadcast(
                    {
                        "type": "notify",
                        "salience": "low",
                        "title": "检查点还在等待回应",
                        "body": str(checkpoint["action_title"]),
                        "kind": "checkpoint_reconfirm",
                        "sessionId": str(checkpoint["session_id"]),
                    }
                )
            changed = True
        return changed

    def _closure_deadline_locked(self, now_dt: datetime) -> str:
        window_end = self.store.get_setting("execution_window_end")
        deadline = checkpoint_passive_deadline(
            delivered_at=now_dt,
            execution_window_end=window_end,
            next_midnight=self.clock.next_local_midnight(now_dt),
            window_end_fn=self.clock.local_window_end,
        )
        return utc_now_iso(deadline)

    def _set_action_locked(
        self,
        action_id: str,
        *,
        status: str | None = None,
        start_settled: int | None = None,
        pending_kind: str | None = None,
        closure_deadline: str | None = None,
        now: str,
    ) -> None:
        sets = ["updated_at = ?"]
        params: list[Any] = [now]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if start_settled is not None:
            sets.append("start_settled = ?")
            params.append(start_settled)
        if pending_kind is not None:
            sets.append("pending_kind = ?")
            params.append(pending_kind)
        if closure_deadline is not None:
            sets.append("closure_deadline = ?")
            params.append(closure_deadline)
        params.append(action_id)
        self.store.connection.execute(f"UPDATE next_actions SET {', '.join(sets)} WHERE id = ?", params)

    def _cancel_action_locked(self, action_id: str, status: str, now: str) -> None:
        self.store.connection.execute(
            "UPDATE next_actions SET status = ?, pending_kind = NULL, closure_deadline = NULL, updated_at = ? WHERE id = ?",
            (status, now, action_id),
        )
        self.store.connection.execute(
            "UPDATE start_interventions SET state = ? WHERE action_id = ? AND state IN ('delivered','followed_up')",
            (InterventionState.EXPIRED, action_id),
        )
        self.store.connection.execute(
            """
            UPDATE execution_sessions SET status = ?, end_reason = ?, ended_at = ?
            WHERE action_id = ? AND status = 'active'
            """,
            (SessionStatus.ENDED, SessionEndReason.TRACKING_ENDED_UNCONFIRMED, now, action_id),
        )


    # ------------------------------------------------------------------
    # UI 快照（主窗口唯一读取入口）

    def build_state(self) -> dict[str, Any]:
        now = self.clock.now_iso()
        plan = self.store.get_latest_plan()
        plan_view: dict[str, Any] | None = None
        draft_view: dict[str, Any] | None = None
        actions: list[dict[str, Any]] = []
        if plan is not None:
            plan_view = {
                "id": str(plan["id"]),
                "status": str(plan["status"]),
                "sourceVersion": int(plan["source_version"]),
                "enabledAt": plan["enabled_at"],
                "createdAt": str(plan["created_at"]),
            }
            if plan["status"] == PlanStatus.DRAFT:
                # 审阅工作区需要原文（权威依据）随草案一起展示。
                plan_view["sourceText"] = str(plan["source_text"])
            draft_row = self.store.get_draft(str(plan["id"]))
            if draft_row is not None:
                draft_view = {
                    "status": str(draft_row["status"]),
                    "error": draft_row["error"],
                    "basedOnSourceVersion": int(draft_row["based_on_source_version"]),
                    "generatedAt": draft_row["generated_at"],
                    "draft": _load_json(draft_row["draft_json"]) if draft_row["draft_json"] else None,
                    "stale": int(draft_row["based_on_source_version"]) != int(plan["source_version"]),
                    "generating": self.draft_job_running(str(plan["id"])),
                }
            # 返回所有方案的行动（含被取代方案）：旧行动被明确取消而非抹除。
            for row in self.store.connection.execute(
                "SELECT * FROM next_actions ORDER BY planned_start_at"
            ).fetchall():
                actions.append(self._action_view(row))

        pending_surfaces = [
            self._surface_view(row)
            for row in self.store.connection.execute(
                "SELECT * FROM start_interventions WHERE state IN ('delivered','followed_up') ORDER BY delivered_at"
            ).fetchall()
        ]
        active_session = self.store.active_session()
        session_view = self._session_view(active_session) if active_session is not None else None
        pending_closure = self.store.connection.execute(
            "SELECT * FROM next_actions WHERE status = ? ORDER BY closure_deadline LIMIT 1",
            (ActionStatus.PENDING_CLOSURE,),
        ).fetchone()
        pending_recovery_row = self.store.pending_recovery()
        pending_recovery = None
        if pending_recovery_row is not None:
            pending_recovery = {
                "id": str(pending_recovery_row["id"]),
                "createdAt": str(pending_recovery_row["created_at"]),
                "basis": _load_json(pending_recovery_row["basis_json"]),
            }
        quiet_unresolved = [
            self._action_view(row)
            for row in self.store.connection.execute(
                """
                SELECT * FROM next_actions
                WHERE status = 'scheduled' AND start_settled = 1
                ORDER BY planned_start_at
                """
            ).fetchall()
        ]
        resumable = [
            self._action_view(row)
            for row in self.store.connection.execute(
                "SELECT * FROM next_actions WHERE status = 'paused' ORDER BY updated_at"
            ).fetchall()
        ]
        model_status = self.model_status()
        return {
            "now": now,
            "plan": plan_view,
            "draft": draft_view,
            "actions": actions,
            "pendingSurfaces": pending_surfaces,
            "activeSession": session_view,
            "pendingClosure": self._action_view(pending_closure) if pending_closure is not None else None,
            "pendingRecovery": pending_recovery,
            "quietUnresolved": quiet_unresolved,
            "resumable": resumable,
            "settings": self.store.all_settings(),
            "model": model_status,
        }

    def model_status(self) -> dict[str, Any]:
        from .draft import model_config_summary

        return model_config_summary()

    def _action_view(self, row: Any) -> dict[str, Any]:
        intervention = self.store.latest_intervention(str(row["id"]))
        evidence = self.store.evidence_for_action(str(row["id"]))
        sessions = self.store.connection.execute(
            "SELECT id, status, end_reason, started_at, ended_at FROM execution_sessions WHERE action_id = ? ORDER BY started_at",
            (str(row["id"]),),
        ).fetchall()
        return {
            "id": str(row["id"]),
            "planId": str(row["plan_id"]),
            "title": str(row["title"]),
            "detail": str(row["detail"] or ""),
            "plannedStartAt": str(row["planned_start_at"]),
            "estimatedMinutes": row["estimated_minutes"],
            "status": str(row["status"]),
            "startSettled": bool(row["start_settled"]),
            "pendingKind": row["pending_kind"],
            "closureDeadline": row["closure_deadline"],
            "latestIntervention": {
                "id": str(intervention["id"]),
                "state": str(intervention["state"]),
                "deliveryMode": str(intervention["delivery_mode"]),
                "deliveredAt": str(intervention["delivered_at"]),
                "surfaceDeadline": str(intervention["surface_deadline"]),
                "responseKind": intervention["response_kind"],
            }
            if intervention is not None
            else None,
            "hasEvidence": bool(evidence),
            "sessions": [
                {
                    "id": str(s["id"]),
                    "status": str(s["status"]),
                    "endReason": s["end_reason"],
                    "startedAt": str(s["started_at"]),
                    "endedAt": s["ended_at"],
                }
                for s in sessions
            ],
        }

    def _surface_view(self, row: Any) -> dict[str, Any]:
        action = self.store.get_action(str(row["action_id"]))
        return {
            "interventionId": str(row["id"]),
            "actionId": str(row["action_id"]),
            "actionTitle": str(action["title"]) if action is not None else "",
            "plannedStartAt": str(row["planned_start_at"]),
            "deliveredAt": str(row["delivered_at"]),
            "graceDeadline": str(row["grace_deadline"]),
            "surfaceDeadline": str(row["surface_deadline"]),
            "deliveryMode": str(row["delivery_mode"]),
            "state": str(row["state"]),
            "estimatedMinutes": action["estimated_minutes"] if action is not None else None,
        }

    def _session_view(self, session: Any) -> dict[str, Any]:
        action = self.store.get_action(str(session["action_id"]))
        checkpoints = self.store.checkpoints_for_session(str(session["id"]))
        current = None
        for checkpoint in checkpoints:
            if checkpoint["state"] in {CheckpointState.SCHEDULED, CheckpointState.DELIVERED}:
                current = checkpoint
                break
        started = parse_utc(str(session["started_at"]))
        worked = max(0, int((self.clock.now_utc() - started).total_seconds() // 60))
        return {
            "id": str(session["id"]),
            "actionId": str(session["action_id"]),
            "actionTitle": str(action["title"]) if action is not None else "",
            "kind": str(session["kind"]),
            "startedAt": str(session["started_at"]),
            "estimatedMinutes": int(session["estimated_minutes"]),
            "workedMinutes": worked,
            "checkpoint": {
                "id": str(current["id"]),
                "seq": int(current["seq"]),
                "dueAt": str(current["due_at"]),
                "state": str(current["state"]),
                "deliveryMode": current["delivery_mode"],
                "deadline": current["deadline"],
            }
            if current is not None
            else None,
        }



def _load_json(raw: Any) -> dict[str, Any]:
    import json

    if not raw:
        return {}
    return json.loads(str(raw))


def _dump_json(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False)


def _apply_draft_patch(draft: PlanImportDraft, patch: dict[str, Any]) -> None:
    if "originalPoints" in patch:
        draft.original_points = [str(p) for p in patch["originalPoints"]]
    if "derivedPoints" in patch:
        draft.derived_points = [str(p) for p in patch["derivedPoints"]]
    if "gaps" in patch:
        draft.gaps = [str(p) for p in patch["gaps"]]
    for candidate_patch in patch.get("candidateActions", []):
        local_id = str(candidate_patch.get("localId", ""))
        candidate = next((c for c in draft.candidate_actions if c.local_id == local_id), None)
        if candidate is None:
            draft.candidate_actions.append(
                PlanImportDraft.__dataclass_fields__ and _candidate_from_patch(candidate_patch)
            )
            continue
        if "title" in candidate_patch:
            candidate.title = str(candidate_patch["title"])
        if "plannedStartAt" in candidate_patch:
            candidate.planned_start_at = candidate_patch["plannedStartAt"] or None
        if "estimatedMinutes" in candidate_patch:
            candidate.estimated_minutes = candidate_patch["estimatedMinutes"]
        if "sourceRef" in candidate_patch:
            candidate.source_ref = str(candidate_patch["sourceRef"])


def _candidate_from_patch(patch: dict[str, Any]) -> Any:
    from .domain import DraftCandidateAction

    return DraftCandidateAction(
        local_id=str(patch.get("localId") or new_id("cnd")),
        title=str(patch.get("title", "")),
        origin=str(patch.get("origin", "derived")),
        source_ref=str(patch.get("sourceRef", "")),
        planned_start_at=patch.get("plannedStartAt"),
        estimated_minutes=patch.get("estimatedMinutes"),
        user_confirmed=bool(patch.get("userConfirmed", False)),
    )
