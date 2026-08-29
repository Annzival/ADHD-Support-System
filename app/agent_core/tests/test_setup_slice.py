"""必要设置切片：导入 → 草案 → 逐项确认 → 原子启用，以及四类异常路径。"""

from __future__ import annotations

import pytest

from agent_core.domain import ActionStatus, DraftStatus, PlanStatus
from agent_core.service import Service

from .conftest import make_ready_draft


def test_import_creates_draft_and_keeps_source(service: Service) -> None:
    plan_id = service.import_plan("我的学习方案原文")
    plan = service.store.get_plan(plan_id)
    assert plan is not None
    assert str(plan["status"]) == PlanStatus.DRAFT
    assert str(plan["source_text"]) == "我的学习方案原文"
    draft = service.store.get_draft(plan_id)
    assert draft is not None
    assert str(draft["status"]) == DraftStatus.GENERATING


def test_enable_requires_confirmed_first_action(service: Service) -> None:
    plan_id = service.import_plan("方案")
    service.complete_draft(plan_id, 1, "ready", make_ready_draft(plan_id, confirmed=False), None)
    with pytest.raises(Exception, match="first_action_unconfirmed"):
        service.enable_plan(plan_id)


def test_enable_rejects_stale_draft(service: Service) -> None:
    plan_id = service.import_plan("方案")
    service.complete_draft(plan_id, 1, "ready", make_ready_draft(plan_id), None)
    service.update_source(plan_id, "修改后的方案 v2")
    with pytest.raises(Exception, match="source_superseded"):
        service.enable_plan(plan_id)


def test_enable_rejects_planned_start_in_past(service: Service, clock) -> None:
    plan_id = service.import_plan("方案")
    service.complete_draft(plan_id, 1, "ready", make_ready_draft(plan_id, planned_start="2026-01-01T09:00:00Z"), None)
    with pytest.raises(Exception, match="planned_start_in_past"):
        service.enable_plan(plan_id)


def test_enable_creates_actions_atomically(service: Service, clock) -> None:
    plan_id = service.import_plan("方案")
    draft = make_ready_draft(plan_id)
    draft.candidate_actions.append(
        type(draft.candidate_actions[0])(
            local_id="c2",
            title="修改简历",
            origin="derived",
            source_ref="完成简历",
            planned_start_at="2026-09-02T10:00:00Z",
            estimated_minutes=30,
            user_confirmed=True,
        )
    )
    service.complete_draft(plan_id, 1, "ready", draft, None)
    result = service.enable_plan(plan_id)
    assert len(result["actionIds"]) == 2
    plan = service.store.get_plan(plan_id)
    assert str(plan["status"]) == PlanStatus.ENABLED
    actions = service.build_state()["actions"]
    assert [action["status"] for action in actions] == [ActionStatus.SCHEDULED, ActionStatus.SCHEDULED]
    assert actions[0]["estimatedMinutes"] == 45


def test_reimport_supersedes_previous_plan(service: Service, clock) -> None:
    first = service.import_plan("方案一")
    service.complete_draft(first, 1, "ready", make_ready_draft(first), None)
    service.enable_plan(first)
    old_action = service.build_state()["actions"][0]["id"]

    second = service.import_plan("方案二")
    service.complete_draft(second, 1, "ready", make_ready_draft(second), None)
    service.enable_plan(second)

    assert str(service.store.get_plan(first)["status"]) == PlanStatus.SUPERSEDED
    assert str(service.store.get_action(old_action)["status"]) == ActionStatus.CANCELLED_SUPERSEDED
    state = service.build_state()
    assert len(state["pendingSurfaces"]) == 0


def test_patch_draft_clears_on_candidate_edit_then_reconfirm(service: Service) -> None:
    plan_id = service.import_plan("方案")
    service.complete_draft(plan_id, 1, "ready", make_ready_draft(plan_id, confirmed=False), None)
    service.patch_draft(plan_id, {"candidateActions": [{"localId": "c1", "title": "新标题"}]})
    draft_row = service.store.get_draft(plan_id)
    payload = draft_row["draft_json"]
    assert "新标题" in payload

    service.confirm_candidate_action(plan_id, "c1", {"title": "确认标题", "plannedStartAt": "2026-09-01T10:00:00Z", "estimatedMinutes": 40})
    payload = service.store.get_draft(plan_id)["draft_json"]
    assert '"userConfirmed": true' in payload


def test_draft_failure_keeps_source_and_allows_retry(service: Service) -> None:
    plan_id = service.import_plan("方案")
    service.complete_draft(plan_id, 1, "failed", None, "模型未配置")
    plan = service.store.get_plan(plan_id)
    assert str(plan["source_text"]) == "方案"
    draft = service.store.get_draft(plan_id)
    assert str(draft["status"]) == DraftStatus.FAILED
    service.regenerate_draft(plan_id)
    assert str(service.store.get_draft(plan_id)["status"]) == DraftStatus.GENERATING
