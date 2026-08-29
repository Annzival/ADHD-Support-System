"""回环 HTTP/WebSocket API：令牌认证、CORS、一次性 bootstrap 交接。

安全边界与 V-02 spike 一致：仅绑定 127.0.0.1 动态端口；令牌只在宿主与核心内存中；
原始令牌不进入日志、数据库或前端持久化。该边界不防御已拥有同一用户权限的本地进程。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .clock import Clock
from .domain import DomainError
from .service import Service
from .ws import ConnectionRegistry, accept_key, read_client_frame


def write_private_bootstrap(path: Path, endpoint: str, token: str) -> None:
    """原子发布唯一包含临时令牌的记录，沿用 V-02/V-03 验证过的机制。"""

    if path.exists():
        raise FileExistsError(f"bootstrap path must not already exist: {path}")
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


class ApiContext:
    def __init__(self, service: Service, clock: Clock, frontend_dir: Path | None) -> None:
        self.service = service
        self.clock = clock
        self.frontend_dir = frontend_dir
        self.token = secrets.token_urlsafe(32)
        self.registry = ConnectionRegistry()


_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def make_handler(context: ApiContext) -> type[BaseHTTPRequestHandler]:
    service = context.service

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "AgentCore/0.1"

        def log_message(self, *_args: object) -> None:
            return  # 访问日志可能携带路径参数，统一禁用

        # -- 基础设施 -------------------------------------------------------

        def _write_json(self, status: HTTPStatus, payload: Any) -> None:
            encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self._cors_headers()
            self.end_headers()
            self.wfile.write(encoded)

        def _cors_headers(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, PUT, OPTIONS")

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            if header.startswith("Bearer ") and secrets.compare_digest(header[7:], context.token):
                return True
            self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
            return False

        def _read_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            if length > 2_000_000:
                raise DomainError("payload_too_large", "请求体过大")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            parsed = json.loads(raw.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise DomainError("invalid_body", "请求体必须是 JSON 对象")
            return parsed

        def _dispatch(self, method: str) -> None:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in {"127.0.0.1", "localhost"}:
                self._write_json(HTTPStatus.FORBIDDEN, {"error": "invalid_host"})
                return
            try:
                self._route(method)
            except DomainError as error:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": error.code, "message": str(error)})
            except Exception as error:  # noqa: BLE001 - 单一入口的确定性错误响应
                self._write_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": "internal_error", "message": f"{type(error).__name__}"},
                )

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Content-Length", "0")
            self._cors_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch("POST")

        def do_PATCH(self) -> None:  # noqa: N802
            self._dispatch("PATCH")

        def do_PUT(self) -> None:  # noqa: N802
            self._dispatch("PUT")

        # -- 路由 -----------------------------------------------------------

        def _route(self, method: str) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if method == "GET" and path == "/api/health":
                self._write_json(HTTPStatus.OK, {"status": "ok"})
                return
            if method == "GET" and path == "/api/events":
                self._handle_websocket(parse_qs(parsed.query))
                return
            if context.frontend_dir is not None and method == "GET" and not path.startswith("/api/"):
                self._serve_static(path)
                return
            if not self._authorized():
                return
            body: dict[str, Any] = {}
            if method in {"POST", "PATCH", "PUT"}:
                body = self._read_body()

            if method == "GET" and path == "/api/state":
                self._write_json(HTTPStatus.OK, service.build_state())
                return
            if method == "GET" and path == "/api/settings":
                self._write_json(HTTPStatus.OK, service.store.all_settings())
                return
            if method == "PUT" and path == "/api/settings":
                self._write_json(HTTPStatus.OK, service.update_settings(body))
                return
            if method == "POST" and path == "/api/plans":
                plan_id = service.import_plan(str(body.get("sourceText", "")))
                self._write_json(HTTPStatus.OK, {"planId": plan_id})
                return
            self._plan_routes(method, path, body)
            self._execution_routes(method, path, body)
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def _plan_routes(self, method: str, path: str, body: dict[str, Any]) -> None:
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "api" and parts[1] == "plans":
                plan_id = parts[2]
                rest = parts[3:]
                if rest == ["source"] and method == "POST":
                    service.update_source(plan_id, str(body.get("sourceText", "")))
                    self._write_json(HTTPStatus.OK, {"updated": True})
                    return
                if rest == ["draft", "regenerate"] and method == "POST":
                    service.regenerate_draft(plan_id)
                    self._write_json(HTTPStatus.OK, {"regenerating": True})
                    return
                if rest == ["draft"] and method == "PATCH":
                    draft = service.patch_draft(plan_id, body)
                    self._write_json(HTTPStatus.OK, draft.to_json())
                    return
                if rest == ["enable"] and method == "POST":
                    self._write_json(HTTPStatus.OK, service.enable_plan(plan_id))
                    return
                if len(rest) == 3 and rest[0] == "candidates" and method == "POST":
                    local_id = rest[1]
                    if rest[2] == "confirm":
                        self._write_json(HTTPStatus.OK, service.confirm_candidate_action(plan_id, local_id, body))
                        return
                    if rest[2] == "unconfirm":
                        service.unconfirm_candidate_action(plan_id, local_id)
                        self._write_json(HTTPStatus.OK, {"unconfirmed": True})
                        return

        def _execution_routes(self, method: str, path: str, body: dict[str, Any]) -> None:
            parts = path.strip("/").split("/")
            if method != "POST" or len(parts) != 4 or parts[0] != "api":
                return
            scope, item_id, action = parts[1], parts[2], parts[3]
            if scope == "interventions" and action == "respond":
                self._write_json(HTTPStatus.OK, service.respond_start(item_id, str(body.get("response", "")), body))
                return
            if scope == "checkpoints" and action == "respond":
                self._write_json(HTTPStatus.OK, service.respond_checkpoint(item_id, str(body.get("response", "")), body))
                return
            if scope == "sessions" and action == "pause":
                self._write_json(HTTPStatus.OK, service.pause_session(item_id, body))
                return
            if scope == "actions" and action == "closure":
                self._write_json(HTTPStatus.OK, service.submit_closure(item_id, body))
                return
            if scope == "actions" and action == "resume":
                self._write_json(HTTPStatus.OK, service.resume_action(item_id, body))
                return
            if scope == "recovery" and action == "decide":
                self._write_json(HTTPStatus.OK, service.decide_recovery(item_id, str(body.get("choice", ""))))
                return

        # -- 静态前端（仅开发模式；正式运行由 Wails 宿主提供资源） ------------

        def _serve_static(self, path: str) -> None:
            assert context.frontend_dir is not None
            relative = path.lstrip("/") or "index.html"
            candidate = (context.frontend_dir / relative).resolve()
            if not str(candidate).startswith(str(context.frontend_dir.resolve())) or not candidate.is_file():
                candidate = context.frontend_dir / "index.html"
            if not candidate.is_file():
                self._write_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return
            payload = candidate.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", _MIME.get(candidate.suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        # -- WebSocket -------------------------------------------------------

        def _handle_websocket(self, query: dict[str, list[str]]) -> None:
            if (self.headers.get("Upgrade") or "").lower() != "websocket":
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "websocket_upgrade_required"})
                return
            token_values = query.get("token", [])
            if not token_values or not secrets.compare_digest(token_values[0], context.token):
                self._write_json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return
            key = self.headers.get("Sec-WebSocket-Key")
            if not key:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": "websocket_key_required"})
                return
            self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept_key(key))
            self.end_headers()
            self.wfile.flush()
            handle = context.registry.register(self.connection)
            try:
                # 单向推送：读取并丢弃客户端帧（处理 ping/close），断开时清理。
                while True:
                    opcode, _payload = read_client_frame(self.connection)
                    if opcode == 0x8:  # close
                        break
            except (ConnectionError, OSError, ValueError):
                pass
            finally:
                context.registry.unregister(handle)

    return Handler


class CoreApiServer:
    def __init__(self, context: ApiContext) -> None:
        self.context = context
        handler = make_handler(context)
        self.http_server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.http_server.daemon_threads = True
        port = self.http_server.server_address[1]
        self.endpoint = f"http://127.0.0.1:{port}"
        self._thread: threading.Thread | None = None

    def broadcast(self, event: dict[str, Any]) -> None:
        self.context.registry.broadcast_json(event)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self.http_server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )
        self._thread.start()

    def shutdown(self) -> None:
        self.http_server.shutdown()
        self.http_server.server_close()
