"""回环 API：令牌认证、CORS 预检、bootstrap 交接与 WebSocket 推送。"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_core.api import ApiContext, CoreApiServer, write_private_bootstrap
from agent_core.clock import FixedClock
from agent_core.store import Store
from agent_core.service import Service


@pytest.fixture()
def api(tmp_path: Path):
    store = Store(tmp_path / "api-test.sqlite3")
    store.initialise()
    service = Service(store, FixedClock(__import__("datetime").datetime(2026, 9, 1, 9, 0, tzinfo=__import__("datetime").timezone.utc)))
    context = ApiContext(service, service.clock, frontend_dir=None)
    server = CoreApiServer(context)
    server.start()
    yield context, server
    server.shutdown()
    store.close()


def _request(endpoint: str, path: str, token: str | None = None, method: str = "GET", body: dict | None = None):
    request = urllib.request.Request(endpoint + path, method=method)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data=data, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers)
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8")), dict(error.headers)


def test_health_is_unauthenticated(api) -> None:
    context, server = api
    status, payload, _ = _request(server.endpoint, "/api/health")
    assert status == 200 and payload["status"] == "ok"


def test_state_requires_bearer_token(api) -> None:
    context, server = api
    status, payload, _ = _request(server.endpoint, "/api/state")
    assert status == 401
    status, payload, _ = _request(server.endpoint, "/api/state", token="wrong-token")
    assert status == 401
    status, payload, _ = _request(server.endpoint, "/api/state", token=context.token)
    assert status == 200 and "now" in payload


def test_cors_preflight(api) -> None:
    context, server = api
    status, _, headers = _request(server.endpoint, "/api/state")
    assert headers.get("Access-Control-Allow-Origin") == "*"


def test_import_plan_roundtrip(api) -> None:
    context, server = api
    status, payload, _ = _request(
        server.endpoint, "/api/plans", token=context.token, method="POST", body={"sourceText": "学习方案"}
    )
    assert status == 200
    plan_id = payload["planId"]
    status, state, _ = _request(server.endpoint, "/api/state", token=context.token)
    assert state["plan"]["id"] == plan_id
    assert state["draft"]["status"] == "generating"


def test_bootstrap_file_atomic_and_secret(api, tmp_path: Path) -> None:
    context, server = api
    path = tmp_path / "handoff.json"
    write_private_bootstrap(path, server.endpoint, context.token)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["endpoint"] == server.endpoint
    assert payload["portMode"] == "dynamic"
    assert payload["token"] == context.token
    with pytest.raises(FileExistsError):
        write_private_bootstrap(path, server.endpoint, context.token)
    path.unlink()
    assert not path.exists()


def test_websocket_push_receives_broadcast(api) -> None:
    context, server = api
    sock = socket.create_connection(("127.0.0.1", int(server.endpoint.rsplit(":", 1)[1])), timeout=5)
    key = "dGhlIHNhbXBsZSBub25jZQ=="
    request = (
        f"GET /api/events?token={context.token} HTTP/1.1\r\n"
        f"Host: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))
    response = b""
    while b"\r\n\r\n" not in response:
        response += sock.recv(4096)
    assert b"101" in response.split(b"\r\n")[0]

    # 无令牌的握手被拒绝
    sock_bad = socket.create_connection(("127.0.0.1", int(server.endpoint.rsplit(":", 1)[1])), timeout=5)
    bad_request = (
        f"GET /api/events?token=wrong HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    sock_bad.sendall(bad_request.encode("ascii"))
    time.sleep(0.3)
    bad_response = sock_bad.recv(4096)
    assert b"401" in bad_response.split(b"\r\n")[0]
    sock_bad.close()

    server.broadcast({"type": "state_changed", "reason": "test"})
    from agent_core.ws import read_client_frame

    opcode, payload = read_client_frame(sock)
    assert opcode == 1
    message = json.loads(payload.decode("utf-8"))
    assert message["type"] == "state_changed"
    sock.close()


def test_host_header_validation(api) -> None:
    context, server = api
    # 直连伪造 Host 的请求被拒绝（防 DNS rebinding 基线）
    port = int(server.endpoint.rsplit(":", 1)[1])
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(f"GET /api/state HTTP/1.1\r\nHost: evil.example.com\r\n\r\n".encode("ascii"))
    time.sleep(0.3)
    data = sock.recv(4096)
    assert b"403" in data.split(b"\r\n")[0]
    sock.close()
