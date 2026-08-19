from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
CORE = ROOT / "agent_core_stub.py"
FAKE_CONTEXT_ID = "v02-fake-context-0001"
FAKE_CONTEXT_KIND = "v02_fake_context"


def read_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("websocket peer closed")
        data.extend(chunk)
    return bytes(data)


def read_headers(connection: socket.socket) -> bytes:
    data = bytearray()
    while not data.endswith(b"\r\n\r\n"):
        data.extend(read_exact(connection, 1))
        if len(data) > 16_384:
            raise ValueError("oversized websocket response headers")
    return bytes(data)


def send_text_frame(connection: socket.socket, payload: bytes) -> None:
    if len(payload) >= 126:
        raise ValueError("test payload should stay small")
    mask = os.urandom(4)
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    connection.sendall(bytes((0x81, 0x80 | len(payload))) + mask + masked)


def read_text_frame(connection: socket.socket) -> bytes:
    first, second = read_exact(connection, 2)
    if (first & 0x0F) != 0x1:
        raise ConnectionError("websocket response was not text")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(connection, 2))[0]
    if second & 0x80:
        raise ValueError("server websocket frame must not be masked")
    return read_exact(connection, length)


class RunningCore:
    def __init__(self, temp: tempfile.TemporaryDirectory[str], delay: float = 0.0) -> None:
        self.root = Path(temp.name)
        self.bootstrap = self.root / "handoff.json"
        self.events = self.root / "events.jsonl"
        command = [sys.executable, str(CORE), "--bootstrap-file", str(self.bootstrap)]
        if delay:
            command.extend(["--bootstrap-delay-seconds", str(delay)])
        environment = {**os.environ, "SPIKE_CORE_EVENT_LOG": str(self.events)}
        self.process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        self.data = self.wait_for_bootstrap()
        endpoint = urlsplit(str(self.data["endpoint"]))
        self.host = endpoint.hostname
        self.port = endpoint.port
        self.credential = str(self.data["token"])

    def wait_for_bootstrap(self) -> dict[str, object]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.bootstrap.exists():
                return json.loads(self.bootstrap.read_text(encoding="utf-8"))
            if self.process.poll() is not None:
                raise AssertionError("Core exited before publishing its bootstrap record")
            time.sleep(0.02)
        raise AssertionError("Core did not publish its bootstrap record")

    def request(
        self,
        method: str,
        path: str,
        credential: str | None,
    ) -> tuple[int, dict[str, object]]:
        connection = HTTPConnection(self.host, self.port, timeout=2)
        headers = {}
        if credential is not None:
            headers["Authorization"] = f"Bearer {credential}"
        connection.request(method, path, headers=headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, payload

    def websocket(self, credential: str | None) -> tuple[socket.socket, int]:
        connection = socket.create_connection((self.host, self.port), timeout=2)
        connection.settimeout(2)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        headers = [
            "GET /spike/ws HTTP/1.1",
            f"Host: {self.host}:{self.port}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if credential is not None:
            headers.append(f"Authorization: Bearer {credential}")
        connection.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("ascii"))
        response = read_headers(connection).decode("ascii")
        return connection, int(response.splitlines()[0].split()[1])

    def restart(self) -> None:
        status, body = self.request("POST", "/spike/control/restart", self.credential)
        if status != 202 or body != {"accepted": True}:
            raise AssertionError("Core did not accept the controlled restart")
        self.process.wait(timeout=5)

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)


class AgentCoreStubTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.core = RunningCore(self.temp)

    def tearDown(self) -> None:
        self.core.close()
        self.temp.cleanup()

    def assert_websocket_echo(self, core: RunningCore, credential: str) -> socket.socket:
        connection, status = core.websocket(credential)
        self.assertEqual(101, status)
        message = json.dumps(
            {"kind": FAKE_CONTEXT_KIND, "context_id": FAKE_CONTEXT_ID},
            separators=(",", ":"),
        ).encode("utf-8")
        send_text_frame(connection, message)
        response = json.loads(read_text_frame(connection).decode("utf-8"))
        self.assertEqual(
            {"kind": f"{FAKE_CONTEXT_KIND}_echo", "context_id": FAKE_CONTEXT_ID},
            response,
        )
        return connection

    def test_loopback_dynamic_handshake_and_authentication_rejections(self) -> None:
        self.assertEqual("127.0.0.1", self.core.host)
        self.assertGreater(self.core.port, 0)
        self.assertEqual("dynamic", self.core.data["port_mode"])
        self.assertEqual(
            {"kind": f"{FAKE_CONTEXT_KIND}_echo", "context_id": FAKE_CONTEXT_ID},
            self.core.request(
                "GET",
                f"/spike/http?context_id={FAKE_CONTEXT_ID}",
                self.core.credential,
            )[1],
        )
        websocket = self.assert_websocket_echo(self.core, self.core.credential)
        websocket.close()

        for credential in (None, "intentionally-wrong-v02-credential"):
            with self.subTest(protocol="http", credential_present=credential is not None):
                status, body = self.core.request(
                    "GET",
                    f"/spike/http?context_id={FAKE_CONTEXT_ID}",
                    credential,
                )
                self.assertEqual(401, status)
                self.assertEqual({"error": "unauthorized"}, body)
            with self.subTest(protocol="websocket", credential_present=credential is not None):
                websocket, status = self.core.websocket(credential)
                self.assertEqual(401, status)
                websocket.close()

        event_text = self.core.events.read_text(encoding="utf-8")
        self.assertFalse(
            self.core.credential in event_text,
            "event log unexpectedly contains the run credential",
        )
        self.assertNotRegex(event_text, r'"(?:token|authorization|credential)"\s*:')

    def test_restart_invalidates_old_connection_and_credential(self) -> None:
        old_credential = self.core.credential
        old_websocket = self.assert_websocket_echo(self.core, old_credential)
        self.core.restart()
        try:
            # A terminated peer can report its reset on the next write (Windows)
            # or on the following read (Linux).  Both prove the old socket is invalid.
            with self.assertRaises((ConnectionError, OSError, socket.timeout)):
                send_text_frame(
                    old_websocket,
                    json.dumps(
                        {"kind": FAKE_CONTEXT_KIND, "context_id": FAKE_CONTEXT_ID},
                        separators=(",", ":"),
                    ).encode("utf-8"),
                )
                read_text_frame(old_websocket)
        finally:
            old_websocket.close()

        replacement_temp = tempfile.TemporaryDirectory()
        replacement = RunningCore(replacement_temp)
        try:
            self.assertNotEqual(old_credential, replacement.credential)
            status, body = replacement.request(
                "GET",
                f"/spike/http?context_id={FAKE_CONTEXT_ID}",
                old_credential,
            )
            self.assertEqual(401, status)
            self.assertEqual({"error": "unauthorized"}, body)
            stale_websocket, stale_status = replacement.websocket(old_credential)
            self.assertEqual(401, stale_status)
            stale_websocket.close()
            fresh_websocket = self.assert_websocket_echo(replacement, replacement.credential)
            fresh_websocket.close()
        finally:
            replacement.close()
            replacement_temp.cleanup()

    def test_delayed_bootstrap_is_not_published_before_delay(self) -> None:
        self.core.close()
        delayed_temp = tempfile.TemporaryDirectory()
        root = Path(delayed_temp.name)
        bootstrap = root / "handoff.json"
        process = subprocess.Popen(
            [
                sys.executable,
                str(CORE),
                "--bootstrap-file",
                str(bootstrap),
                "--bootstrap-delay-seconds",
                "1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(0.15)
            self.assertFalse(bootstrap.exists())
        finally:
            process.terminate()
            process.wait(timeout=5)
            delayed_temp.cleanup()


if __name__ == "__main__":
    unittest.main()
