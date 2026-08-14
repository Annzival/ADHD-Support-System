from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
STUB = ROOT / "agent_core_stub.py"


def unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class AgentCoreStubTest(unittest.TestCase):
    def setUp(self) -> None:
        self.port = unused_port()
        self.process = subprocess.Popen(
            [sys.executable, str(STUB), "--port", str(self.port)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                if self.get("/health")["status"] == "ok":
                    return
            except URLError:
                time.sleep(0.05)
        self.fail("test double did not pass its health check")

    def tearDown(self) -> None:
        if self.process.poll() is None:
            self.post("/control/exit", {"reason": "test_teardown"})
            self.process.wait(timeout=5)
        if self.process.stdout is not None:
            self.process.stdout.close()
        if self.process.stderr is not None:
            self.process.stderr.close()

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path: str) -> dict[str, object]:
        with urlopen(self.url(path), timeout=2) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, data: dict[str, object]) -> dict[str, object]:
        request = Request(
            self.url(path),
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=2) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    def test_notification_context_is_transferred_to_test_double(self) -> None:
        result = self.post("/demo/notification-context", {"contextID": "context-42", "action": "OPEN_CONTEXT"})
        self.assertEqual({"accepted": True}, result)
        self.assertEqual(
            {"contextID": "context-42", "action": "OPEN_CONTEXT"},
            self.get("/demo/last-context")["lastNotificationContext"],
        )

    def test_controlled_crash_returns_documented_exit_code(self) -> None:
        self.assertEqual({"accepted": True}, self.post("/control/crash", {"scenario": "unit-test"}))
        self.assertEqual(71, self.process.wait(timeout=5))


if __name__ == "__main__":
    unittest.main()
