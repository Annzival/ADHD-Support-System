"""共享测试夹具：固定时钟 + 临时 SQLite + 事件记录器。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_core.clock import FixedClock  # noqa: E402
from agent_core.domain import PlanImportDraft, DraftCandidateAction  # noqa: E402
from agent_core.service import Service  # noqa: E402
from agent_core.store import Store  # noqa: E402


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def notifications(self) -> list[dict[str, Any]]:
        return [event for event in self.events if event.get("type") == "notify"]

    def state_changes(self) -> list[dict[str, Any]]:
        return [event for event in self.events if event.get("type") == "state_changed"]


@pytest.fixture()
def clock() -> FixedClock:
    # 2026-09-01 09:00 本地（上海）——工作日上午，不在默认安静时段。
    return FixedClock(datetime(2026, 9, 1, 9, 0, tzinfo=timezone.utc), tz="Asia/Shanghai")


@pytest.fixture()
def recorder() -> EventRecorder:
    return EventRecorder()


@pytest.fixture()
def service(clock: FixedClock, recorder: EventRecorder, tmp_path: Path) -> Service:
    store = Store(tmp_path / "test.sqlite3")
    store.initialise()
    return Service(store, clock, broadcast=recorder)


def make_ready_draft(plan_id: str, based_on_version: int = 1, confirmed: bool = True, planned_start: str | None = None) -> PlanImportDraft:
    return PlanImportDraft(
        original_points=["完成简历"],
        derived_points=["拆分为初稿与修改"],
        gaps=[],
        candidate_actions=[
            DraftCandidateAction(
                local_id="c1",
                title="写简历初稿",
                origin="original",
                source_ref="完成简历",
                planned_start_at=planned_start or "2026-09-01T10:00:00Z",
                estimated_minutes=45,
                user_confirmed=confirmed,
            )
        ],
    )


def seed_enabled_plan(service: Service, planned_start: str = "2026-09-01T10:00:00Z", estimated: int | None = 45) -> str:
    """直接走设置切片黄金路径启用一个方案，返回 action_id。"""

    plan_id = service.import_plan("学习方案：完成简历")
    service.complete_draft(plan_id, 1, "ready", make_ready_draft(plan_id, planned_start=planned_start), None)
    service.patch_draft(
        plan_id,
        {"candidateActions": [{"localId": "c1", "estimatedMinutes": estimated}]},
    )
    service.enable_plan(plan_id)
    actions = service.build_state()["actions"]
    return str(actions[0]["id"])
