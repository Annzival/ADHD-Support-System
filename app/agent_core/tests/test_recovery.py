"""恢复干预：离线错过合并、恢复包继续、暂不决定与被动入口。"""

from __future__ import annotations

from agent_core.domain import (
    ActionStatus,
    RecoveryChoice,
    RecoveryState,
    SessionEndReason,
    StartResponse,
)

from .conftest import seed_enabled_plan


def test_offline_missed_start_generates_one_recovery_with_handle_previous(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    # 模拟 Core/PC 离线跨越整个界面窗口
    clock.advance_from_utc_to("2026-09-02T02:00:00Z")  # 次日 10:00 本地
    service.tick()  # 启动后的首次 tick：错过窗口 → start_settled
    service.run_recovery_scan()
    state = service.build_state()
    recovery = state["pendingRecovery"]
    assert recovery is not None
    assert action_id in recovery["basis"]["missedActionIds"]
    action = service.store.get_action(action_id)
    assert str(action["status"]) == ActionStatus.SCHEDULED  # 不改写为失败
    # 决定：处理上一项
    result = service.decide_recovery(recovery["id"], RecoveryChoice.HANDLE_PREVIOUS)
    assert result["choice"] == RecoveryChoice.HANDLE_PREVIOUS
    assert service.build_state()["pendingRecovery"] is None


def test_recovery_continue_previous_with_resume_packet(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    started = service.respond_start(surfaces[0]["interventionId"], StartResponse.START_NOW, {})
    clock.advance_from_utc_to("2026-09-01T10:15:00Z")
    service.pause_session(started["sessionId"], {"note": "中断了"})
    service.submit_closure(action_id, {"skipped": True})
    assert str(service.store.get_action(action_id)["status"]) == ActionStatus.PAUSED

    # 模拟重启
    clock.advance_from_utc_to("2026-09-01T11:00:00Z")
    service.tick()
    basis = service.run_recovery_scan()
    assert basis is not None and basis["hasResumePacket"]
    recovery = service.build_state()["pendingRecovery"]
    result = service.decide_recovery(recovery["id"], RecoveryChoice.CONTINUE_PREVIOUS)
    assert result["needsDuration"] and result["resumeActionId"] == action_id
    resumed = service.resume_action(action_id, {"remainingMinutes": 30})
    assert service.store.get_checkpoint(resumed["checkpointId"]) is not None


def test_recovery_with_active_session_offers_continue(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=60)
    clock.advance_from_utc_to("2026-09-01T10:00:00Z")
    service.tick()
    surfaces = service.build_state()["pendingSurfaces"]
    service.respond_start(surfaces[0]["interventionId"], StartResponse.START_NOW, {})
    # Core 重启：会话仍在权威状态中
    clock.advance_from_utc_to("2026-09-01T10:20:00Z")
    service.tick()
    basis = service.run_recovery_scan()
    assert basis is not None and basis["hasActiveSession"]
    recovery = service.build_state()["pendingRecovery"]
    result = service.decide_recovery(recovery["id"], RecoveryChoice.CONTINUE_PREVIOUS)
    assert "needsDuration" not in result or not result.get("needsDuration")
    session = service.store.active_session()
    assert session is not None  # 直接回到现有活动会话


def test_defer_keeps_quiet_passive_entry(service, clock) -> None:
    action_id = seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-02T02:00:00Z")
    service.tick()
    service.run_recovery_scan()
    recovery = service.build_state()["pendingRecovery"]
    service.decide_recovery(recovery["id"], RecoveryChoice.DEFER)
    state = service.build_state()
    assert state["pendingRecovery"] is None
    assert any(item["id"] == action_id for item in state["quietUnresolved"])


def test_recovery_generated_once_only(service, clock) -> None:
    seed_enabled_plan(service, planned_start="2026-09-01T10:00:00Z", estimated=45)
    clock.advance_from_utc_to("2026-09-02T02:00:00Z")
    service.tick()
    assert service.run_recovery_scan() is not None
    # 再次扫描不产生第二个恢复干预
    assert service.run_recovery_scan() is None
    recoveries = service.store.connection.execute("SELECT COUNT(*) AS n FROM recovery_interventions").fetchone()
    assert int(recoveries["n"]) == 1
