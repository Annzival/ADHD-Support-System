"""调度生命周期：开始宽限、唯一跟进、被动过期、检查点跟踪结束、收尾超时。"""

from __future__ import annotations

from agent_core.domain import (
    ActionStatus,
    CheckpointState,
    InterventionState,
    SessionEndReason,
    StartResponse,
)

from .conftest import seed_enabled_plan


def test_followup_fires_once_after_grace(service, clock, recorder) -> None:
    seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    clock.advance_from_utc_to("2026-09-01T10:10:00Z")  # 宽限 10 分钟结束
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 1
    assert str(surfaces[0]["state"]) == InterventionState.FOLLOWED_UP
    followups = [n for n in recorder.notifications() if n.get("kind") == "start_followup"]
    assert len(followups) == 1
    # 再次 tick 不重复跟进
    clock.advance(60)
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 1
    assert str(surfaces[0]["state"]) == InterventionState.FOLLOWED_UP
    followups = [n for n in recorder.notifications() if n.get("kind") == "start_followup"]
    assert len(followups) == 1


def test_quiet_hours_suppress_delivery_and_followup(service, clock) -> None:
    # 23:30 本地开始 → 安静时段（22:00-08:00）
    seed_enabled_plan(service, planned_start="2026-09-01T15:30:00Z", estimated=60)  # 23:30 北京
    clock.advance_from_utc_to("2026-09-01T15:30:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert len(surfaces) == 1
    assert str(surfaces[0]["deliveryMode"]) == "quiet_suppressed"
    clock.advance_from_utc_to("2026-09-01T15:41:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    assert str(surfaces[0]["state"]) == InterventionState.DELIVERED  # 跟进被安静时段跳过


def test_surface_expiry_keeps_facts_and_settles_start(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    # 界面过期：计划开始 + 45 分钟（预计时长项）
    clock.advance_from_utc_to("2026-09-01T10:46:00Z")
    service.tick()
    state = service.build_state()
    assert len(state["pendingSurfaces"]) == 0
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.SCHEDULED  # 不推断结果
    assert int(action["start_settled"]) == 1
    intervention = service.store.latest_intervention(action_id)
    assert str(intervention["state"]) == InterventionState.EXPIRED
    assert intervention["response_kind"] is None


def test_checkpoint_tracking_ends_unconfirmed_at_deadline(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    started = service.respond_start(surfaces[0]["interventionId"], StartResponse.START_NOW, {})
    clock.advance_from_utc_to("2026-09-01T10:45:00Z")
    service.tick()  # 检查点送达
    clock.advance_from_utc_to("2026-09-01T23:00:00Z")  # 执行窗口结束
    service.tick()
    session = service.store.get_session(started["sessionId"])
    assert str(session["status"]) == "ended"
    assert str(session["end_reason"]) == SessionEndReason.TRACKING_ENDED_UNCONFIRMED
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.SCHEDULED
    assert int(action["start_settled"]) == 1
    # 未确认状态不形成执行证据
    assert service.store.evidence_for_action(action_id) == []


def test_pending_closure_deadline_auto_closes(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    service.respond_start(surfaces[0]["interventionId"], StartResponse.START_NOW, {})
    # 进入待收尾（此处直接置位以隔离测试收尾超时分支本身）
    service.store.connection.execute(
        "UPDATE next_actions SET status = 'pending_closure', pending_kind = 'completed', closure_deadline = ? WHERE id = ?",
        ("2026-09-01T10:30:00Z", action_id),
    )
    clock.advance_from_utc_to("2026-09-01T10:31:00Z")
    service.tick()
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.COMPLETED
    evidence = service.store.evidence_for_action(action_id)
    assert len(evidence) == 1


def test_settings_are_hard_constraints(service) -> None:
    service.update_settings({"start_grace_minutes": 30, "quiet_hours_start": "23:00", "quiet_hours_end": "07:00"})
    settings = service.store.all_settings()
    assert settings["start_grace_minutes"] == "30"
    assert settings["quiet_hours_start"] == "23:00"
    with __import__("pytest").raises(Exception, match="invalid_setting"):
        service.update_settings({"start_grace_minutes": 0})
    with __import__("pytest").raises(Exception, match="invalid_setting"):
        service.update_settings({"quiet_hours_start": "25:99"})
