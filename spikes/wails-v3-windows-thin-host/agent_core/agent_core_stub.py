"""Minimal loopback-only Agent Core test double for V-01.

It has no database, scheduler, domain state, LLM, or product behavior.  Its
only purpose is to let the Wails host exercise health checks, context handoff,
controlled crashes, and graceful shutdown on a real Windows desktop.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class StubState:
    def __init__(self, event_log: str | None) -> None:
        self.event_log = event_log
        self.last_notification_context: dict[str, str] | None = None
        self.lock = threading.Lock()

    def event(self, kind: str, **fields: object) -> None:
        record = {"time": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
        line = json.dumps(record, ensure_ascii=False)
        print(line, flush=True)
        if not self.event_log:
            return
        os.makedirs(os.path.dirname(self.event_log), exist_ok=True)
        with open(self.event_log, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def make_handler(state: StubState, server: ThreadingHTTPServer):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            return

        def write_json(self, status: HTTPStatus, payload: object) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def read_json(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError("JSON body must be an object")
            return value

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self.write_json(HTTPStatus.OK, {"status": "ok", "kind": "v01-test-double"})
                return
            if self.path == "/demo/last-context":
                with state.lock:
                    value = state.last_notification_context
                self.write_json(HTTPStatus.OK, {"lastNotificationContext": value})
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self.read_json()
            except (ValueError, json.JSONDecodeError) as error:
                self.write_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return

            if self.path == "/demo/notification-context":
                context_id = payload.get("contextID")
                action = payload.get("action")
                if not isinstance(context_id, str) or not isinstance(action, str):
                    self.write_json(HTTPStatus.BAD_REQUEST, {"error": "contextID and action must be strings"})
                    return
                value = {"contextID": context_id, "action": action}
                with state.lock:
                    state.last_notification_context = value
                state.event("notification_context_received", **value)
                self.write_json(HTTPStatus.ACCEPTED, {"accepted": True})
                return

            if self.path == "/control/crash":
                scenario = payload.get("scenario", "unspecified")
                state.event("controlled_crash_requested", scenario=scenario)
                self.write_json(HTTPStatus.ACCEPTED, {"accepted": True})
                threading.Timer(0.15, lambda: os._exit(71)).start()
                return

            if self.path == "/control/exit":
                reason = payload.get("reason", "unspecified")
                state.event("graceful_exit_requested", reason=reason)
                self.write_json(HTTPStatus.ACCEPTED, {"accepted": True})
                threading.Thread(target=server.shutdown, daemon=True).start()
                return

            self.write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    state = StubState(os.environ.get("SPIKE_CORE_EVENT_LOG"))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(state, None))
    # Handler needs the actual server for the graceful shutdown callback.
    server.RequestHandlerClass = make_handler(state, server)
    state.event("agent_core_started", port=args.port, pid=os.getpid())
    try:
        server.serve_forever(poll_interval=0.1)
    finally:
        server.server_close()
        state.event("agent_core_stopped", port=args.port, pid=os.getpid())


if __name__ == "__main__":
    main()
