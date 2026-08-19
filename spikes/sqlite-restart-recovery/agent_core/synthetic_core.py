"""Loopback-only V-03 SQLite recovery Core test double.

All persisted names and values in this module are explicitly synthetic.  The
module intentionally contains no product-domain behavior: it only makes a
small SQLite transaction/restart experiment reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


SYNTHETIC_TIMEZONE = "UTC"
SYNTHETIC_PREPARE_TIME = "2030-01-01T09:00:00Z"
SYNTHETIC_RECOVERY_TIME = "2030-01-01T10:30:00Z"
SYNTHETIC_DATABASE_ID_PREFIX = "synthetic-v03-database-"
SYNTHETIC_AUTHORITY_ID = "synthetic-authority-state-001"
SYNTHETIC_FUTURE_ID = "synthetic-future-action-001"
SYNTHETIC_EXPIRED_ID = "synthetic-expired-intervention-001"
SYNTHETIC_UNCOMMITTED_ID = "synthetic-uncommitted-write-must-not-survive"
SYNTHETIC_AUTHORITY_VERSION = 7
SYNTHETIC_AUTHORITY_CONTENT = "synthetic-committed-content-v1"
SYNTHETIC_MERGED_RECOVERY_KEY = "synthetic-merged-recovery-signal-001"


def canonical_timestamp(value: str) -> str:
    """Return an explicit UTC timestamp for a test-only injected clock."""

    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("synthetic clock must include an explicit timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65_536), b""):
            digest.update(block)
    return digest.hexdigest()


class SyntheticEventLog:
    """Writes diagnostics while refusing credential-shaped fields."""

    _FORBIDDEN_FIELDS = {"token", "authorization", "credential"}

    def __init__(self, path: str | None) -> None:
        self.path = Path(path) if path else None
        self.lock = threading.Lock()

    def record(self, kind: str, **fields: object) -> None:
        if self._FORBIDDEN_FIELDS.intersection({name.lower() for name in fields}):
            raise ValueError("synthetic event records must not contain credentials")
        if self.path is None:
            return
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        encoded = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded + "\n")


class SyntheticStore:
    """SQLite-only store for the deliberately small synthetic experiment."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            str(database_path), timeout=5, isolation_level=None, check_same_thread=False
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = FULL")

    def close(self) -> None:
        self.connection.close()

    def initialise_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS synthetic_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS synthetic_authority_state (
              stable_id TEXT PRIMARY KEY,
              version INTEGER NOT NULL,
              content TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS synthetic_schedule (
              stable_id TEXT PRIMARY KEY,
              version INTEGER NOT NULL,
              planned_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              status TEXT NOT NULL,
              handled INTEGER NOT NULL CHECK (handled IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS synthetic_observable (
              stable_key TEXT PRIMARY KEY,
              kind TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        else:
            self.connection.execute("COMMIT")

    def has_prepared_checkpoint(self) -> bool:
        row = self.connection.execute(
            "SELECT value FROM synthetic_meta WHERE key = 'synthetic_database_identity'"
        ).fetchone()
        return row is not None and str(row["value"]).startswith(SYNTHETIC_DATABASE_ID_PREFIX)

    def prepare_checkpoint(self) -> None:
        if self.has_prepared_checkpoint():
            raise RuntimeError("synthetic checkpoint already exists; do not overwrite an attempt")
        database_identity = SYNTHETIC_DATABASE_ID_PREFIX + secrets.token_hex(12)
        with self.transaction():
            self.connection.execute(
                "INSERT INTO synthetic_meta(key, value) VALUES (?, ?)",
                ("synthetic_database_identity", database_identity),
            )
            self.connection.execute(
                "INSERT INTO synthetic_authority_state(stable_id, version, content) VALUES (?, ?, ?)",
                (SYNTHETIC_AUTHORITY_ID, SYNTHETIC_AUTHORITY_VERSION, SYNTHETIC_AUTHORITY_CONTENT),
            )
            self.connection.executemany(
                """
                INSERT INTO synthetic_schedule(
                  stable_id, version, planned_at, expires_at, status, handled
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        SYNTHETIC_FUTURE_ID,
                        1,
                        "2030-01-01T10:00:00Z",
                        "2030-01-01T12:00:00Z",
                        "synthetic_pending",
                        0,
                    ),
                    (
                        SYNTHETIC_EXPIRED_ID,
                        1,
                        "2030-01-01T08:00:00Z",
                        "2030-01-01T08:30:00Z",
                        "synthetic_pending",
                        0,
                    ),
                ),
            )

    def authority_snapshot(self) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT stable_id, version, content FROM synthetic_authority_state WHERE stable_id = ?",
            (SYNTHETIC_AUTHORITY_ID,),
        ).fetchone()
        if row is None:
            return {"present": False}
        return {
            "present": True,
            "stableId": row["stable_id"],
            "version": row["version"],
            "content": row["content"],
        }

    def database_identity(self) -> str | None:
        row = self.connection.execute(
            "SELECT value FROM synthetic_meta WHERE key = 'synthetic_database_identity'"
        ).fetchone()
        return None if row is None else str(row["value"])

    def uncommitted_row_is_absent(self) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM synthetic_authority_state WHERE stable_id = ?",
            (SYNTHETIC_UNCOMMITTED_ID,),
        ).fetchone()
        return row is None

    def run_recovery_scan(self, injected_clock: str) -> dict[str, int]:
        """Apply one idempotent recovery pass using only the injected test clock."""

        clock = canonical_timestamp(injected_clock)
        produced_future = 0
        produced_merged_recovery = 0
        expired_rows = 0
        with self.transaction():
            pending = self.connection.execute(
                """
                SELECT stable_id, planned_at, expires_at
                FROM synthetic_schedule
                WHERE handled = 0
                ORDER BY stable_id
                """
            ).fetchall()
            for row in pending:
                stable_id = str(row["stable_id"])
                if str(row["expires_at"]) <= clock:
                    self.connection.execute(
                        """
                        UPDATE synthetic_schedule
                        SET status = 'synthetic_expired', handled = 1
                        WHERE stable_id = ?
                        """,
                        (stable_id,),
                    )
                    expired_rows += 1
                    continue
                if str(row["planned_at"]) <= clock:
                    key = f"synthetic-future-observable:{stable_id}"
                    inserted = self.connection.execute(
                        """
                        INSERT OR IGNORE INTO synthetic_observable(stable_key, kind, created_at)
                        VALUES (?, 'synthetic_future_action', ?)
                        """,
                        (key, clock),
                    ).rowcount
                    self.connection.execute(
                        """
                        UPDATE synthetic_schedule
                        SET status = 'synthetic_observed', handled = 1
                        WHERE stable_id = ?
                        """,
                        (stable_id,),
                    )
                    produced_future += inserted
            if expired_rows:
                produced_merged_recovery = self.connection.execute(
                    """
                    INSERT OR IGNORE INTO synthetic_observable(stable_key, kind, created_at)
                    VALUES (?, 'synthetic_merged_recovery_signal', ?)
                    """,
                    (SYNTHETIC_MERGED_RECOVERY_KEY, clock),
                ).rowcount
        return {
            "futureObservableInserted": produced_future,
            "expiredRecordsHandled": expired_rows,
            "mergedRecoveryInserted": produced_merged_recovery,
        }

    def observable_count(self, kind: str) -> int:
        row = self.connection.execute(
            "SELECT COUNT(*) AS count FROM synthetic_observable WHERE kind = ?", (kind,)
        ).fetchone()
        return int(row["count"])

    def schedule_snapshot(self) -> list[dict[str, object]]:
        rows = self.connection.execute(
            """
            SELECT stable_id, version, planned_at, expires_at, status, handled
            FROM synthetic_schedule
            ORDER BY stable_id
            """
        ).fetchall()
        return [
            {
                "stableId": row["stable_id"],
                "version": row["version"],
                "plannedAt": row["planned_at"],
                "expiresAt": row["expires_at"],
                "status": row["status"],
                "handled": bool(row["handled"]),
            }
            for row in rows
        ]

    def summary_after_recovery(self, injected_clock: str) -> dict[str, object]:
        first_scan = self.run_recovery_scan(injected_clock)
        second_scan = self.run_recovery_scan(injected_clock)
        authority = self.authority_snapshot()
        schedules = {item["stableId"]: item for item in self.schedule_snapshot()}
        future_count = self.observable_count("synthetic_future_action")
        merged_count = self.observable_count("synthetic_merged_recovery_signal")
        future = schedules.get(SYNTHETIC_FUTURE_ID, {})
        expired = schedules.get(SYNTHETIC_EXPIRED_ID, {})
        checks = {
            "synthetic_committed_authority_recovered": "PASS"
            if authority
            == {
                "present": True,
                "stableId": SYNTHETIC_AUTHORITY_ID,
                "version": SYNTHETIC_AUTHORITY_VERSION,
                "content": SYNTHETIC_AUTHORITY_CONTENT,
            }
            else "FAIL",
            "synthetic_interrupted_write_absent": "PASS"
            if self.uncommitted_row_is_absent()
            else "FAIL",
            "synthetic_future_action_once": "PASS"
            if future_count == 1
            and future.get("status") == "synthetic_observed"
            and future.get("handled") is True
            else "FAIL",
            "synthetic_expired_not_replayed": "PASS"
            if expired.get("status") == "synthetic_expired"
            and expired.get("handled") is True
            and self.observable_count("synthetic_expired_intervention") == 0
            else "FAIL",
            "synthetic_merged_recovery_once": "PASS" if merged_count == 1 else "FAIL",
            "synthetic_repeat_scan_no_duplicates": "PASS"
            if second_scan
            == {
                "futureObservableInserted": 0,
                "expiredRecordsHandled": 0,
                "mergedRecoveryInserted": 0,
            }
            else "FAIL",
        }
        status = "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL"
        return {
            "schemaVersion": 1,
            "spike": "V-03",
            "candidateStatus": status,
            "syntheticTimezone": SYNTHETIC_TIMEZONE,
            "injectedClock": canonical_timestamp(injected_clock),
            "databaseIdentity": self.database_identity(),
            "databaseFileSha256": sha256_file(self.database_path),
            "checks": checks,
            "firstRecoveryScan": first_scan,
            "repeatRecoveryScan": second_scan,
            "syntheticAuthority": authority,
            "syntheticSchedules": self.schedule_snapshot(),
            "syntheticObservableCounts": {
                "futureAction": future_count,
                "mergedRecoverySignal": merged_count,
            },
        }


def run_interrupted_write(database_path: Path) -> None:
    """Deliberately leave a transaction open, then exit without cleanup."""

    store = SyntheticStore(database_path)
    try:
        store.initialise_schema()
        store.connection.execute("BEGIN IMMEDIATE")
        store.connection.execute(
            "INSERT INTO synthetic_authority_state(stable_id, version, content) VALUES (?, ?, ?)",
            (SYNTHETIC_UNCOMMITTED_ID, 999, "synthetic-interrupted-content"),
        )
        os._exit(73)
    finally:
        store.close()


def prepare_summary(database_path: Path) -> dict[str, object]:
    store = SyntheticStore(database_path)
    try:
        store.initialise_schema()
        store.prepare_checkpoint()
        before = store.authority_snapshot()
    finally:
        store.close()

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--mode",
            "interrupted-write",
            "--database",
            str(database_path),
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    reopened = SyntheticStore(database_path)
    try:
        reopened.initialise_schema()
        after = reopened.authority_snapshot()
        checks = {
            "synthetic_committed_state_written": "PASS"
            if before
            == {
                "present": True,
                "stableId": SYNTHETIC_AUTHORITY_ID,
                "version": SYNTHETIC_AUTHORITY_VERSION,
                "content": SYNTHETIC_AUTHORITY_CONTENT,
            }
            else "FAIL",
            "synthetic_controlled_abnormal_exit_observed": "PASS"
            if completed.returncode == 73
            else "FAIL",
            "synthetic_uncommitted_write_rolled_back": "PASS"
            if after == before and reopened.uncommitted_row_is_absent()
            else "FAIL",
            "synthetic_database_identity_written": "PASS"
            if reopened.database_identity() is not None
            and reopened.database_identity().startswith(SYNTHETIC_DATABASE_ID_PREFIX)
            else "FAIL",
        }
        return {
            "schemaVersion": 1,
            "spike": "V-03",
            "phase": "synthetic_prepared",
            "candidateStatus": "PASS" if all(value == "PASS" for value in checks.values()) else "FAIL",
            "syntheticTimezone": SYNTHETIC_TIMEZONE,
            "prepareClock": SYNTHETIC_PREPARE_TIME,
            "databaseIdentity": reopened.database_identity(),
            "databaseFileSha256": sha256_file(database_path),
            "checks": checks,
            "syntheticAuthority": after,
            "syntheticSchedules": reopened.schedule_snapshot(),
        }
    finally:
        reopened.close()


def write_private_bootstrap(path: Path, endpoint: str, token: str) -> None:
    """Atomically publish the only record that contains the temporary token."""

    if path.exists():
        raise FileExistsError("bootstrap path must not already exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    payload = {
        "schemaVersion": 1,
        "endpoint": endpoint,
        "portMode": "dynamic",
        "token": token,
    }
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


@dataclass
class CoreRuntime:
    token: str
    summary: dict[str, object]
    events: SyntheticEventLog
    shutdown: Any | None = None


def make_handler(runtime: CoreRuntime) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: object) -> None:
            return

        def write_json(self, status: HTTPStatus, payload: object) -> None:
            encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def authorised(self) -> bool:
            header = self.headers.get("Authorization")
            prefix = "Bearer "
            if header is None or not header.startswith(prefix):
                runtime.events.record("authentication_rejected", reason="missing_or_invalid")
                self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return False
            if not secrets.compare_digest(header[len(prefix) :], runtime.token):
                runtime.events.record("authentication_rejected", reason="incorrect")
                self.write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return False
            return True

        def do_GET(self) -> None:  # noqa: N802
            if not self.authorised():
                return
            if self.path == "/spike/health":
                self.write_json(HTTPStatus.OK, {"status": "ok", "kind": "v03_synthetic_core"})
                return
            if self.path == "/spike/summary":
                runtime.events.record("synthetic_summary_read")
                self.write_json(HTTPStatus.OK, runtime.summary)
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self.authorised():
                return
            if self.path != "/spike/control/normal-exit":
                self.write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            self.write_json(HTTPStatus.ACCEPTED, {"accepted": True})
            self.wfile.flush()
            runtime.events.record("normal_exit_requested")
            if runtime.shutdown is not None:
                threading.Thread(target=runtime.shutdown, daemon=True).start()

    return Handler


def serve(database_path: Path, bootstrap_path: Path, injected_clock: str, event_path: str | None) -> None:
    events = SyntheticEventLog(event_path)
    store = SyntheticStore(database_path)
    server: ThreadingHTTPServer | None = None
    try:
        store.initialise_schema()
        if not store.has_prepared_checkpoint():
            raise RuntimeError("synthetic checkpoint is missing")
        summary = store.summary_after_recovery(injected_clock)
        runtime = CoreRuntime(token=secrets.token_urlsafe(32), summary=summary, events=events)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(runtime))
        runtime.shutdown = server.shutdown
        endpoint = f"http://127.0.0.1:{server.server_address[1]}"
        write_private_bootstrap(bootstrap_path, endpoint, runtime.token)
        events.record(
            "core_bound_loopback",
            endpointFamily="127.0.0.1",
            portMode="dynamic",
            candidateStatus=summary["candidateStatus"],
        )
        server.serve_forever(poll_interval=0.05)
    finally:
        if server is not None:
            server.server_close()
        store.close()
        events.record("core_stopped")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("prepare", "serve", "interrupted-write"), required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path)
    parser.add_argument("--bootstrap-file", type=Path)
    parser.add_argument("--clock", default=SYNTHETIC_RECOVERY_TIME)
    parser.add_argument("--event-log")
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.mode == "interrupted-write":
        run_interrupted_write(arguments.database)
        return
    if arguments.mode == "prepare":
        if arguments.summary_file is None:
            raise ValueError("--summary-file is required for prepare mode")
        summary = prepare_summary(arguments.database)
        arguments.summary_file.parent.mkdir(parents=True, exist_ok=True)
        arguments.summary_file.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if summary["candidateStatus"] != "PASS":
            raise SystemExit(1)
        return
    if arguments.bootstrap_file is None:
        raise ValueError("--bootstrap-file is required for serve mode")
    serve(arguments.database, arguments.bootstrap_file, arguments.clock, arguments.event_log)


if __name__ == "__main__":
    main()
