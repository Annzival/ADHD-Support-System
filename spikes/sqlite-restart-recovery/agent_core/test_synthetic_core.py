from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit

from synthetic_core import (
    SYNTHETIC_DATABASE_ID_PREFIX,
    SYNTHETIC_RECOVERY_TIME,
    SyntheticStore,
    prepare_summary,
)


ROOT = Path(__file__).resolve().parent
CORE = ROOT / "synthetic_core.py"


class RunningSyntheticCore:
    def __init__(self, root: Path, database: Path) -> None:
        self.bootstrap = root / "handoff.json"
        self.events = root / "events.jsonl"
        self.process = subprocess.Popen(
            [
                sys.executable,
                str(CORE),
                "--mode",
                "serve",
                "--database",
                str(database),
                "--bootstrap-file",
                str(self.bootstrap),
                "--clock",
                SYNTHETIC_RECOVERY_TIME,
                "--event-log",
                str(self.events),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.material = self.wait_for_bootstrap()
        endpoint = urlsplit(str(self.material["endpoint"]))
        self.host = endpoint.hostname
        self.port = endpoint.port
        self.token = str(self.material["token"])

    def wait_for_bootstrap(self) -> dict[str, object]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.bootstrap.exists():
                payload = json.loads(self.bootstrap.read_text(encoding="utf-8"))
                self.bootstrap.unlink()
                return payload
            if self.process.poll() is not None:
                raise AssertionError("Core exited before bootstrap publication")
            time.sleep(0.02)
        raise AssertionError("Core did not publish bootstrap material")

    def request(self, method: str, path: str, token: str | None) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection(self.host, self.port, timeout=2)
        headers: dict[str, str] = {}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, body

    def close_normally(self) -> None:
        status, body = self.request("POST", "/spike/control/normal-exit", self.token)
        if status != 202 or body != {"accepted": True}:
            raise AssertionError("Core did not accept normal exit")
        self.process.wait(timeout=5)
        if self.process.returncode != 0:
            raise AssertionError(f"Core exited with {self.process.returncode}")

    def terminate(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


class SyntheticCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "synthetic-recovery.sqlite"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_preserves_committed_data_and_rolls_back_interrupted_write(self) -> None:
        summary = prepare_summary(self.database)

        self.assertEqual("PASS", summary["candidateStatus"])
        self.assertTrue(summary["databaseIdentity"].startswith(SYNTHETIC_DATABASE_ID_PREFIX))
        self.assertEqual(
            {
                "synthetic_committed_state_written": "PASS",
                "synthetic_controlled_abnormal_exit_observed": "PASS",
                "synthetic_uncommitted_write_rolled_back": "PASS",
                "synthetic_database_identity_written": "PASS",
            },
            summary["checks"],
        )

        reopened = SyntheticStore(self.database)
        try:
            reopened.initialise_schema()
            self.assertTrue(reopened.uncommitted_row_is_absent())
            self.assertEqual(summary["databaseIdentity"], reopened.database_identity())
        finally:
            reopened.close()

    def test_prepare_cli_writes_a_sanitized_summary(self) -> None:
        summary_path = self.root / "prepare-summary.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(CORE),
                "--mode",
                "prepare",
                "--database",
                str(self.database),
                "--summary-file",
                str(summary_path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        self.assertEqual(0, completed.returncode)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual("PASS", summary["candidateStatus"])
        serialized = json.dumps(summary, sort_keys=True)
        self.assertNotIn(str(self.database), serialized)
        self.assertNotRegex(serialized, r'"(?:token|authorization|credential)"\s*:')

    def test_recovery_scan_is_idempotent_for_the_synthetic_records(self) -> None:
        self.assertEqual("PASS", prepare_summary(self.database)["candidateStatus"])
        store = SyntheticStore(self.database)
        try:
            store.initialise_schema()
            first = store.run_recovery_scan(SYNTHETIC_RECOVERY_TIME)
            second = store.run_recovery_scan(SYNTHETIC_RECOVERY_TIME)
            self.assertEqual(
                {
                    "futureObservableInserted": 1,
                    "expiredRecordsHandled": 1,
                    "mergedRecoveryInserted": 1,
                },
                first,
            )
            self.assertEqual(
                {
                    "futureObservableInserted": 0,
                    "expiredRecordsHandled": 0,
                    "mergedRecoveryInserted": 0,
                },
                second,
            )
            summary = store.summary_after_recovery(SYNTHETIC_RECOVERY_TIME)
            self.assertEqual("PASS", summary["candidateStatus"])
            self.assertEqual(1, summary["syntheticObservableCounts"]["futureAction"])
            self.assertEqual(1, summary["syntheticObservableCounts"]["mergedRecoverySignal"])
        finally:
            store.close()

    def test_loopback_bootstrap_and_core_restart_keep_one_time_recovery_results(self) -> None:
        self.assertEqual("PASS", prepare_summary(self.database)["candidateStatus"])
        first = RunningSyntheticCore(self.root / "first", self.database)
        try:
            self.assertEqual("127.0.0.1", first.host)
            self.assertGreater(int(first.port or 0), 0)
            self.assertEqual("dynamic", first.material["portMode"])
            status, first_summary = first.request("GET", "/spike/summary", first.token)
            self.assertEqual(200, status)
            self.assertEqual("PASS", first_summary["candidateStatus"])
            old_token = first.token
            first.close_normally()
        finally:
            first.terminate()

        second = RunningSyntheticCore(self.root / "second", self.database)
        try:
            self.assertNotEqual(old_token, second.token)
            rejected_status, rejected = second.request("GET", "/spike/summary", old_token)
            self.assertEqual(401, rejected_status)
            self.assertEqual({"error": "unauthorized"}, rejected)
            status, second_summary = second.request("GET", "/spike/summary", second.token)
            self.assertEqual(200, status)
            self.assertEqual("PASS", second_summary["candidateStatus"])
            self.assertEqual(1, second_summary["syntheticObservableCounts"]["futureAction"])
            self.assertEqual(1, second_summary["syntheticObservableCounts"]["mergedRecoverySignal"])
            events = second.events.read_text(encoding="utf-8")
            self.assertNotIn(second.token, events)
            self.assertNotRegex(events, r'"(?:token|authorization|credential)"\s*:')
        finally:
            second.terminate()

    def test_interrupted_mode_exits_with_the_controlled_code(self) -> None:
        self.assertEqual("PASS", prepare_summary(self.database)["candidateStatus"])
        completed = subprocess.run(
            [
                sys.executable,
                str(CORE),
                "--mode",
                "interrupted-write",
                "--database",
                str(self.database),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        self.assertEqual(73, completed.returncode)
        reopened = SyntheticStore(self.database)
        try:
            reopened.initialise_schema()
            self.assertTrue(reopened.uncommitted_row_is_absent())
        finally:
            reopened.close()


if __name__ == "__main__":
    unittest.main()
