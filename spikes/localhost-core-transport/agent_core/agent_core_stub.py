"""Loopback-only V-02 Agent Core test double.

It deliberately has no product-domain behavior.  It binds a dynamic IPv4
loopback port, writes one transient bootstrap record for its launching host,
and exposes only fake-context echo endpoints needed by this transport spike.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


FAKE_CONTEXT_ID = "v02-fake-context-0001"
FAKE_CONTEXT_KIND = "v02_fake_context"
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class EventLog:
    """Writes diagnostic events while rejecting credential-shaped fields."""

    def __init__(self, path: str | None) -> None:
        self.path = Path(path) if path else None
        self.lock = threading.Lock()

    def record(self, kind: str, **fields: object) -> None:
        forbidden = {"token", "authorization", "credential"}
        if forbidden.intersection(fields):
            raise ValueError("event records must not contain credentials")
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        if self.path is None:
            return
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")


@dataclass(frozen=True)
class CoreState:
    token: str
    events: EventLog


def _write_private_bootstrap(path: Path, endpoint: str, token: str) -> None:
    """Atomically publish the only record that contains the run credential."""

    if path.exists():
        raise FileExistsError(f"bootstrap path must not already exist: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "endpoint": endpoint,
        "port_mode": "dynamic",
        "token": token,
    }
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            temporary.unlink(missing_ok=True)
        finally:
            raise


def _read_exact(connection: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = connection.recv(size - len(data))
        if not chunk:
            raise ConnectionError("websocket peer closed")
        data.extend(chunk)
    return bytes(data)


def _read_client_frame(connection: socket.socket) -> tuple[int, bytes]:
    first, second = _read_exact(connection, 2)
    opcode = first & 0x0F
    masked = (second & 0x80) != 0
    payload_length = second & 0x7F
    if payload_length == 126:
        payload_length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif payload_length == 127:
        payload_length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    if payload_length > 16_384:
        raise ValueError("websocket test frame is too large")
    if not masked:
        raise ValueError("client websocket frame must be masked")
    mask = _read_exact(connection, 4)
    payload = bytearray(_read_exact(connection, payload_length))
    for index in range(len(payload)):
        payload[index] ^= mask[index % 4]
    return opcode, bytes(payload)


def _server_text_frame(payload: bytes) -> bytes:
    length = len(payload)
    if length < 126:
        header = bytes((0x81, length))
    elif length <= 65_535:
        header = bytes((0x81, 126)) + struct.pack("!H", length)
    else:
        raise ValueError("websocket test response is too large")
    return header + payload


def make_handler(state: CoreState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_: object) -> None:
            return

        def _write_json(self, status: HTTPStatus, payload: object) -> None:
            encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode(
                "utf-8"
            )
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def _auth_reason(self) -> str | None:
            header = self.headers.get("Authorization")
            if header is None:
                return "missing"
            prefix = "Bearer "
            if not header.startswith(prefix):
                return "invalid_scheme"
            if not secrets.compare_digest(header[len(prefix) :], state.token):
                return "invalid"
            return None

        def _require_auth(self, route: str) -> bool:
            reason = self._auth_reason()
            if reason is None:
                return True
            state.events.record("authentication_rejected", route=route, reason=reason)
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False

        def _handle_websocket(self) -> None:
            if self.headers.get("Upgrade", "").lower() != "websocket":
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "websocket_upgrade_required"})
                return
            if not self._require_auth("websocket"):
                return
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "websocket_key_required"})
                return
            accept = base64.b64encode(
                hashlib.sha1((key + WEBSOCKET_GUID).encode("ascii")).digest()
            ).decode("ascii")
            self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.flush()
            try:
                while True:
                    opcode, raw_message = _read_client_frame(self.connection)
                    if opcode != 0x1:
                        raise ValueError("expected a text websocket frame")
                    message = json.loads(raw_message.decode("utf-8"))
                    if (
                        not isinstance(message, dict)
                        or message.get("kind") != FAKE_CONTEXT_KIND
                        or message.get("context_id") != FAKE_CONTEXT_ID
                    ):
                        raise ValueError("unexpected fake-context websocket payload")
                    response = {
                        "kind": f"{FAKE_CONTEXT_KIND}_echo",
                        "context_id": FAKE_CONTEXT_ID,
                    }
                    self.connection.sendall(
                        _server_text_frame(
                            json.dumps(response, ensure_ascii=True, separators=(",", ":")).encode(
                                "utf-8"
                            )
                        )
                    )
                    state.events.record("websocket_round_trip", context_id=FAKE_CONTEXT_ID)
            except (ConnectionError, OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as error:
                state.events.record(
                    "websocket_closed_or_rejected",
                    diagnostic=type(error).__name__,
                )

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path == "/spike/ws":
                self._handle_websocket()
                return
            if parsed.path == "/spike/http":
                if not self._require_auth("http"):
                    return
                context_id = parse_qs(parsed.query).get("context_id", [""])[0]
                if context_id != FAKE_CONTEXT_ID:
                    self._write_json(HTTPStatus.BAD_REQUEST, {"error": "unexpected_fake_context"})
                    return
                state.events.record("http_round_trip", context_id=FAKE_CONTEXT_ID)
                self._write_json(
                    HTTPStatus.OK,
                    {"kind": f"{FAKE_CONTEXT_KIND}_echo", "context_id": FAKE_CONTEXT_ID},
                )
                return
            if parsed.path == "/spike/health":
                if not self._require_auth("health"):
                    return
                self._write_json(HTTPStatus.OK, {"status": "ok", "kind": "v02_test_double"})
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlsplit(self.path)
            if parsed.path != "/spike/control/restart":
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            if not self._require_auth("restart"):
                return
            self._write_json(HTTPStatus.ACCEPTED, {"accepted": True})
            self.wfile.flush()
            state.events.record("controlled_restart_requested")
            threading.Timer(0.08, lambda: os._exit(0)).start()

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap-file", required=True)
    parser.add_argument("--bootstrap-delay-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.bootstrap_delay_seconds < 0:
        raise ValueError("--bootstrap-delay-seconds must be non-negative")

    events = EventLog(os.environ.get("SPIKE_CORE_EVENT_LOG"))
    state = CoreState(token=secrets.token_urlsafe(32), events=events)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    events.record("core_bound_loopback", port=server.server_address[1], port_mode="dynamic")
    if args.bootstrap_delay_seconds:
        time.sleep(args.bootstrap_delay_seconds)
    _write_private_bootstrap(Path(args.bootstrap_file), endpoint, state.token)
    events.record("bootstrap_published", endpoint_host="127.0.0.1")
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()
        events.record("core_stopped")


if __name__ == "__main__":
    main()
