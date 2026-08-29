"""首要执行闭环黄金路径与四个确定性开始状态校正分支。"""

from __future__ import annotations

from datetime import timedelta

import pytest

from agent_core.domain import (
    ActionStatus,
    CheckpointResponse,
    EvidenceSource,
    InterventionState,
    SessionEndReason,
    SessionKind,
    StartResponse,
)

from .conftest import seed_enabled_plan


def drive_to_start_intervention(service, clock):
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 1
    return action_id, surfaces[0]["interventionId"]


def test_start_now_creates_session_and_checkpoint_atomically(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    result = service.respond_start(intervention_id, StartResponse.START_NOW, {})
    session = service.store.get_session(result["sessionId"])
    checkpoint = service.store.get_checkpoint(result["checkpointId"])
    assert session is not None and checkpoint is not None
    assert result["checkpointDueAt"] == "2026-09-01T10:45:00Z"  # 开始 + 45 分钟
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.IN_EXECUTION
    intervention = service.store.get_intervention(intervention_id)
    assert str(intervention["state"]) == InterventionState.RESPONDED


def test_start_now_without_estimate_requires_duration(service, clock) -> None:
    action_id = seed_enabled_plan(service, estimated=None)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    intervention_id = service.build_state()["pendingSurfaces"][0]["interventionId"]
    with pytest.raises(Exception, match="duration_required"):
        service.respond_start(intervention_id, StartResponse.START_NOW, {})
    # 未确认时长时会话与检查点都不建立
    assert service.store.active_session() is None
    result = service.respond_start(intervention_id, StartResponse.START_NOW, {"estimatedMinutes": 30})
    assert service.store.get_checkpoint(result["checkpointId"]) is not None


def test_already_started_requires_remaining_minutes(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    with pytest.raises(Exception, match="duration_required"):
        service.respond_start(intervention_id, StartResponse.ALREADY_STARTED, {})
    result = service.respond_start(intervention_id, StartResponse.ALREADY_STARTED, {"estimatedMinutes": 20})
    session = service.store.get_session(result["sessionId"])
    assert str(session["kind"]) == SessionKind.ALREADY_STARTED
    assert result["checkpointDueAt"] == "2026-09-01T10:20:00Z"


def test_golden_path_complete_at_checkpoint_then_closure(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    started = service.respond_start(intervention_id, StartResponse.START_NOW, {})
    clock.advance_from_utc_to("2026-09-01T10:45:00Z")
    service.tick()
    checkpoint = service.store.latest_checkpoint(started["sessionId"])
    assert str(checkpoint["state"]) == "delivered"
    service.respond_checkpoint(str(checkpoint["id"]), CheckpointResponse.COMPLETED, {})
    # 收尾确认：填写
    service.submit_closure(action_id, {"skipped": False, "actualMinutes": 50, "note": "完成"})
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.COMPLETED
    evidence = service.store.evidence_for_action(action_id)
    assert len(evidence) == 1
    assert str(evidence[0]["source"]) == EvidenceSource.CLOSURE_CHECK
    assert int(evidence[0]["actual_minutes"]) == 50
    session = service.store.get_session(started["sessionId"])
    assert str(session["status"]) == "ended"


def test_closure_skip_still_saves_minimal_evidence(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    started = service.respond_start(intervention_id, StartResponse.START_NOW, {})
    service.respond_checkpoint(str(started["checkpointId"]), CheckpointResponse.COMPLETED, {})
    service.submit_closure(action_id, {"skipped": True})
    evidence = service.store.evidence_for_action(action_id)
    assert str(evidence[0]["source"]) == EvidenceSource.CLOSURE_SKIPPED
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.COMPLETED


def test_continue_extends_same_session(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    started = service.respond_start(intervention_id, StartResponse.START_NOW, {})
    clock.advance_from_utc_to("2026-09-01T10:45:00Z")
    service.tick()
    checkpoint = service.store.latest_checkpoint(started["sessionId"])
    result = service.respond_checkpoint(str(checkpoint["id"]), CheckpointResponse.CONTINUE, {"nextCheckpointMinutes": 15})
    session = service.store.get_session(started["sessionId"])
    assert str(session["status"]) == "active"  # 同一会话延续
    next_checkpoint = service.store.get_checkpoint(result["nextCheckpointId"])
    assert str(next_checkpoint["due_at"]) == "2026-09-01T11:00:00Z"


def test_pause_saves_resume_packet_then_closure(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    started = service.respond_start(intervention_id, StartResponse.START_NOW, {})
    clock.advance_from_utc_to("2026-09-01T10:20:00Z")
    service.pause_session(started["sessionId"], {"note": "需要休息"})
    session = service.store.get_session(started["sessionId"])
    assert str(session["status"]) == "ended"
    assert str(session["end_reason"]) == SessionEndReason.PAUSED
    packet = service.store.connection.execute(
        "SELECT resume_packet_json FROM execution_sessions WHERE id = ?", (started["sessionId"],)
    ).fetchone()
    assert packet["resume_packet_json"] is not None
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.PENDING_CLOSURE
    service.submit_closure(action_id, {"skipped": True})
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.PAUSED
    # 恢复：继续上次执行（新会话 + 检查点原子建立）
    resumed = service.resume_action(action_id, {"remainingMinutes": 25})
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.IN_EXECUTION
    assert service.store.get_checkpoint(resumed["checkpointId"]) is not None


def test_direct_completed_branch(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    service.respond_start(intervention_id, StartResponse.COMPLETED_DIRECT, {})
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.PENDING_CLOSURE
    service.submit_closure(action_id, {"skipped": True})
    evidence = service.store.evidence_for_action(action_id)
    assert str(evidence[0]["source"]) in {EvidenceSource.CLOSURE_SKIPPED}
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.COMPLETED


def test_reschedule_branch_rearms_intervention(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    service.respond_start(intervention_id, StartResponse.RESCHEDULED, {"plannedStartAt": "2026-09-01T14:00:00Z"})
    action = service.store.get_action(action_id)
    assert str(action["planned_start_at"]) == "2026-09-01T14:00:00Z"
    assert int(action["start_settled"]) == 0
    # 到新时间后再次产生开始干预
    clock.advance_from_utc_to("2026-09-01T14:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 1 and surfaces[0]["actionId"] == action_id


def test_skip_today_branch(service, clock) -> None:
    action_id, intervention_id = drive_to_start_intervention(service, clock)
    service.respond_start(intervention_id, StartResponse.SKIP_TODAY, {})
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.CANCELLED_TODAY


def test_cannot_have_two_active_sessions(service, clock) -> None:
    plan_id = service.import_plan("方案")
    from .conftest import make_ready_draft

    draft = make_ready_draft(plan_id)
    from agent_core.domain import DraftCandidateAction

    draft.candidate_actions.append(
        DraftCandidateAction(
            local_id="c2",
            title="第二项",
            origin="derived",
            source_ref="方案",
            planned_start_at="2026-09-01T10:00:00Z",
            estimated_minutes=30,
            user_confirmed=True,
        )
    )
    service.complete_draft(plan_id, 1, "ready", draft, None)
    service.enable_plan(plan_id)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 2
    first = service.respond_start(surfaces[0]["interventionId"], StartResponse.START_NOW, {})
    assert first["sessionId"]
    with pytest.raises(Exception, match="session_exists"):
        service.respond_start(surfaces[1]["interventionId"], StartResponse.START_NOW, {})
    active = service.store.connection.execute("SELECT COUNT(*) AS n FROM execution_sessions WHERE status='active'").fetchone()
    assert int(active["n"]) == 1
