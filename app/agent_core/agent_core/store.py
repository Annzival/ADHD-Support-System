"""SQLite 权威状态存储（智能体核心是唯一访问者）。

沿用 V-03 spike 验证过的机制：WAL + synchronous=FULL、BEGIN IMMEDIATE 事务、
原子恢复扫描；表结构承载 MVP 最小领域对象。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .clock import utc_now_iso
from .domain import (
    ActionStatus,
    CheckpointState,
    DraftStatus,
    InterventionState,
    PlanStatus,
    SessionStatus,
)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('draft','enabled','superseded')),
  source_text TEXT NOT NULL,
  source_version INTEGER NOT NULL DEFAULT 1,
  enabled_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_drafts (
  plan_id TEXT PRIMARY KEY REFERENCES plans(id),
  status TEXT NOT NULL CHECK (status IN ('generating','ready','failed')),
  draft_json TEXT,
  error TEXT,
  based_on_source_version INTEGER NOT NULL,
  generated_at TEXT
);
CREATE TABLE IF NOT EXISTS next_actions (
  id TEXT PRIMARY KEY,
  plan_id TEXT NOT NULL,
  title TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  planned_start_at TEXT NOT NULL,
  estimated_minutes INTEGER,
  status TEXT NOT NULL CHECK (status IN ('scheduled','in_execution','pending_closure','completed','paused','cancelled_today','cancelled_superseded')),
  start_settled INTEGER NOT NULL DEFAULT 0,
  pending_kind TEXT,
  closure_deadline TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS start_interventions (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL,
  planned_start_at TEXT NOT NULL,
  delivered_at TEXT NOT NULL,
  grace_deadline TEXT NOT NULL,
  delivery_mode TEXT NOT NULL CHECK (delivery_mode IN ('active','quiet_suppressed')),
  followup_state TEXT NOT NULL DEFAULT 'none' CHECK (followup_state IN ('none','pending','delivered','skipped_quiet','skipped_superseded')),
  followup_delivered_at TEXT,
  state TEXT NOT NULL CHECK (state IN ('delivered','followed_up','responded','expired')),
  response_kind TEXT,
  responded_at TEXT,
  surface_deadline TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_sessions (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('start_now','already_started','resumed')),
  started_at TEXT NOT NULL,
  estimated_minutes INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','pending_closure','ended')),
  pending_kind TEXT,
  closure_deadline TEXT,
  end_reason TEXT CHECK (end_reason IN ('completed','paused','tracking_ended_unconfirmed','completed_by_deadline')),
  ended_at TEXT,
  resume_packet_json TEXT
);
CREATE TABLE IF NOT EXISTS checkpoints (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  due_at TEXT NOT NULL,
  delivered_at TEXT,
  delivery_mode TEXT CHECK (delivery_mode IN ('active','quiet_suppressed')),
  reconfirm_state TEXT NOT NULL DEFAULT 'none' CHECK (reconfirm_state IN ('none','pending','delivered','skipped_quiet','skipped_offline')),
  state TEXT NOT NULL CHECK (state IN ('scheduled','delivered','passive_only','responded','expired_tracking_ended')),
  response_kind TEXT,
  responded_at TEXT,
  deadline TEXT
);
CREATE TABLE IF NOT EXISTS execution_evidence (
  id TEXT PRIMARY KEY,
  action_id TEXT NOT NULL,
  session_id TEXT,
  outcome TEXT NOT NULL CHECK (outcome IN ('completed','paused','unknown')),
  actual_minutes INTEGER,
  note TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL CHECK (source IN ('closure_check','closure_skipped','closure_deadline','direct_completed','tracking_ended')),
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recovery_interventions (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  basis_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK (state IN ('pending','decided')),
  choice TEXT,
  decided_at TEXT
);
CREATE TABLE IF NOT EXISTS domain_event_log (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_actions_plan ON next_actions(plan_id);
CREATE INDEX IF NOT EXISTS idx_interventions_action ON start_interventions(action_id);
CREATE INDEX IF NOT EXISTS idx_checkpoints_session ON checkpoints(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_action ON execution_sessions(action_id);
"""

DEFAULT_SETTINGS: dict[str, str] = {
    "start_grace_minutes": "10",
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "08:00",
    "execution_window_end": "23:00",
}


class Store:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(database_path), timeout=5, isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def initialise(self) -> None:
        # executescript 会隐式提交，因此建表在事务外执行。
        self.connection.executescript(_SCHEMA)
        with self.transaction():
            self.connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
            for key, value in DEFAULT_SETTINGS.items():
                self.connection.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value))

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield self.connection
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    # -- 基础查询 -----------------------------------------------------------

    def get_setting(self, key: str) -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else ""

    def all_settings(self) -> dict[str, str]:
        return {str(r["key"]): str(r["value"]) for r in self.connection.execute("SELECT key, value FROM settings")}

    def set_setting(self, key: str, value: str) -> None:
        self.connection.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_plan(self, plan_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()

    def get_enabled_plan(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM plans WHERE status = ? ORDER BY created_at DESC LIMIT 1", (PlanStatus.ENABLED,)
        ).fetchone()

    def get_latest_plan(self) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM plans ORDER BY created_at DESC LIMIT 1").fetchone()

    def get_draft(self, plan_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM plan_drafts WHERE plan_id = ?", (plan_id,)).fetchone()

    def get_action(self, action_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM next_actions WHERE id = ?", (action_id,)).fetchone()

    def actions_for_plan(self, plan_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM next_actions WHERE plan_id = ? ORDER BY planned_start_at", (plan_id,)
            )
        )

    def get_session(self, session_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM execution_sessions WHERE id = ?", (session_id,)).fetchone()

    def active_session(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM execution_sessions WHERE status = ? ORDER BY started_at DESC LIMIT 1",
            (SessionStatus.ACTIVE,),
        ).fetchone()

    def active_session_for_action(self, action_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM execution_sessions WHERE action_id = ? AND status = ? ORDER BY started_at DESC LIMIT 1",
            (action_id, SessionStatus.ACTIVE),
        ).fetchone()

    def get_checkpoint(self, checkpoint_id: str) -> sqlite3.Row | None:
        return self.connection.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)).fetchone()

    def checkpoints_for_session(self, session_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute("SELECT * FROM checkpoints WHERE session_id = ? ORDER BY seq", (session_id,))
        )

    def latest_checkpoint(self, session_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM checkpoints WHERE session_id = ? ORDER BY seq DESC LIMIT 1", (session_id,)
        ).fetchone()

    def latest_intervention(self, action_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM start_interventions WHERE action_id = ? ORDER BY created_at DESC LIMIT 1",
            (action_id,),
        ).fetchone()

    def get_intervention(self, intervention_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM start_interventions WHERE id = ?", (intervention_id,)
        ).fetchone()

    def pending_recovery(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM recovery_interventions WHERE state = 'pending' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    def latest_recovery(self) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM recovery_interventions ORDER BY created_at DESC LIMIT 1"
        ).fetchone()

    def paused_sessions_with_packet(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM execution_sessions WHERE end_reason = 'paused' AND resume_packet_json IS NOT NULL "
                "ORDER BY ended_at DESC"
            )
        )

    def evidence_for_action(self, action_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM execution_evidence WHERE action_id = ? ORDER BY recorded_at", (action_id,)
            )
        )

    # -- 写入助手（都必须在事务内调用） --------------------------------------

    def insert_plan(self, plan_id: str, source_text: str, now: str) -> None:
        self.connection.execute(
            "INSERT INTO plans(id, status, source_text, source_version, created_at) VALUES (?, ?, ?, 1, ?)",
            (plan_id, PlanStatus.DRAFT, source_text, now),
        )

    def insert_draft(self, plan_id: str, based_on_version: int, now: str) -> None:
        self.connection.execute(
            "INSERT INTO plan_drafts(plan_id, status, based_on_source_version, generated_at) VALUES (?, ?, ?, ?)",
            (plan_id, DraftStatus.GENERATING, based_on_version, now),
        )

    def update_draft_result(self, plan_id: str, status: str, draft_json: str | None, error: str | None, now: str) -> None:
        self.connection.execute(
            "UPDATE plan_drafts SET status = ?, draft_json = ?, error = ?, generated_at = ? WHERE plan_id = ?",
            (status, draft_json, error, now, plan_id),
        )

    def insert_action(
        self,
        action_id: str,
        plan_id: str,
        title: str,
        detail: str,
        planned_start_at: str,
        estimated_minutes: int | None,
        now: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO next_actions(id, plan_id, title, detail, planned_start_at, estimated_minutes, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (action_id, plan_id, title, detail, planned_start_at, estimated_minutes, ActionStatus.SCHEDULED, now, now),
        )

    def insert_session(
        self,
        session_id: str,
        action_id: str,
        kind: str,
        started_at: str,
        estimated_minutes: int,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO execution_sessions(id, action_id, kind, started_at, estimated_minutes, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, action_id, kind, started_at, estimated_minutes, SessionStatus.ACTIVE),
        )

    def insert_checkpoint(self, checkpoint_id: str, session_id: str, seq: int, due_at: str) -> None:
        self.connection.execute(
            "INSERT INTO checkpoints(id, session_id, seq, due_at, state) VALUES (?, ?, ?, ?, ?)",
            (checkpoint_id, session_id, seq, due_at, CheckpointState.SCHEDULED),
        )

    def insert_intervention(
        self,
        intervention_id: str,
        action_id: str,
        planned_start_at: str,
        delivered_at: str,
        grace_deadline: str,
        delivery_mode: str,
        surface_deadline: str,
        now: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO start_interventions(
              id, action_id, planned_start_at, delivered_at, grace_deadline,
              delivery_mode, state, surface_deadline, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                intervention_id,
                action_id,
                planned_start_at,
                delivered_at,
                grace_deadline,
                delivery_mode,
                InterventionState.DELIVERED,
                surface_deadline,
                now,
            ),
        )

    def insert_evidence(
        self,
        evidence_id: str,
        action_id: str,
        session_id: str | None,
        outcome: str,
        actual_minutes: int | None,
        note: str,
        source: str,
        now: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO execution_evidence(id, action_id, session_id, outcome, actual_minutes, note, source, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (evidence_id, action_id, session_id, outcome, actual_minutes, note, source, now),
        )

    def insert_recovery(self, recovery_id: str, basis: dict[str, Any], now: str) -> None:
        self.connection.execute(
            "INSERT INTO recovery_interventions(id, created_at, basis_json, state) VALUES (?, ?, ?, 'pending')",
            (recovery_id, now, json.dumps(basis, ensure_ascii=False)),
        )

    def record_event(self, kind: str, payload: dict[str, Any], now: str) -> None:
        self.connection.execute(
            "INSERT INTO domain_event_log(at, kind, payload_json) VALUES (?, ?, ?)",
            (now, kind, json.dumps(payload, ensure_ascii=False)),
        )
