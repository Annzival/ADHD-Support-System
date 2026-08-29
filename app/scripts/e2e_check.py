"""端到端验证：真实核心进程 + 真实 HTTP/WS + 脚手架草案，走完整黄金路径。

用法：python scripts/e2e_check.py
退出码 0 = PASS；任何断言失败都会以非 0 退出。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_PACKAGE = ROOT / "agent_core"
PYTHON = str(CORE_PACKAGE / ".venv" / "Scripts" / "python.exe")


class Client:
    def __init__(self, endpoint: str, token: str) -> None:
        self.endpoint = endpoint
        self.token = token

    def request(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
        request = urllib.request.Request(self.endpoint + path, method=method)
        effective_token = self.token if token is None else token
        if effective_token:
            request.add_header("Authorization", f"Bearer {effective_token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def get(self, path: str) -> tuple[int, dict]:
        return self.request("GET", path)

    def post(self, path: str, body: dict | None = None) -> tuple[int, dict]:
        return self.request("POST", path, body or {})


def wait_for(condition, timeout: float, description: str):
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            result = condition()
            if result:
                return result
        except Exception as error:  # noqa: BLE001
            last_error = error
        time.sleep(0.2)
    raise AssertionError(f"等待超时：{description}（最后错误：{last_error}）")


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(name: str, condition: bool) -> None:
        checks.append((name, bool(condition)))
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}")

    with tempfile.TemporaryDirectory(prefix="adhd-e2e-") as temp:
        temp_dir = Path(temp)
        database = temp_dir / "e2e.sqlite3"
        bootstrap = temp_dir / "handoff.json"

        env = dict(os.environ)
        env["ADHD_FAKE_DRAFT"] = "1"
        env["NO_PROXY"] = "127.0.0.1,localhost"
        process = subprocess.Popen(
            [
                str(CORE_PACKAGE / ".venv" / "Scripts" / "python.exe"),
                "-m", "agent_core",
                "--bootstrap-file", str(bootstrap),
                "--database", str(database),
                "--tick-interval", "0.5",
            ],
            cwd=str(CORE_PACKAGE),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        try:
            print("== 启动与交接 ==")
            wait_for(lambda: bootstrap.exists(), 15, "bootstrap 文件生成")
            record = json.loads(bootstrap.read_text(encoding="utf-8"))
            check("bootstrap 仅含动态回环端点", record["portMode"] == "dynamic" and record["endpoint"].startswith("http://127.0.0.1:"))
            client = Client(record["endpoint"], record["token"])

            status, payload = client.get("/api/health")
            check("健康检查", status == 200 and payload.get("status") == "ok")
            status, _ = client.request("GET", "/api/state", token="")
            check("无令牌请求被拒绝", status == 401)
            status, _ = client.request("GET", "/api/state", token="wrong-token")
            check("错误令牌请求被拒绝", status == 401)

            print("== 必要设置切片 ==")
            future = (datetime.now(timezone.utc) + timedelta(seconds=3)).isoformat().replace("+00:00", "Z")
            status, payload = client.post("/api/plans", {"sourceText": "E2E 方案：完成简历初稿"})
            check("导入方案原文", status == 200)
            plan_id = payload["planId"]
            wait_for(
                lambda: client.get("/api/state")[1]["draft"]["status"] == "ready",
                10, "脚手架草案生成",
            )
            state = client.get("/api/state")[1]
            check("草案就绪且含原文要点", len(state["draft"]["draft"]["originalPoints"]) >= 1)

            status, payload = client.post(
                f"/api/plans/{plan_id}/candidates/c1/confirm",
                {
                    "title": "写简历初稿",
                    "plannedStartAt": future,
                    "estimatedMinutes": 1,
                },
            )
            check("逐项确认第一项行动与开始时间", status == 200 and payload.get("userConfirmed") is True)

            status, payload = client.post(f"/api/plans/{plan_id}/enable", {})
            check("原子启用方案", status == 200 and len(payload.get("actionIds", [])) == 1)
            action_id = payload["actionIds"][0]

            print("== 首要执行闭环 ==")
            wait_for(lambda: len(client.get("/api/state")[1]["pendingSurfaces"]) == 1, 15, "开始干预送达")
            surfaces = client.get("/api/state")[1]["pendingSurfaces"]
            check("开始干预在计划时间送达", surfaces[0]["actionId"] == action_id)

            status, payload = client.post(
                f"/api/interventions/{surfaces[0]['interventionId']}/respond",
                {"response": "start_now", "estimatedMinutes": 1},
            )
            check("立即开始：会话与首次检查点原子建立", status == 200 and payload.get("sessionId") and payload.get("checkpointId"))
            session_id = payload["sessionId"]
            checkpoint_id = payload["checkpointId"]

            status, payload = client.post(
                f"/api/checkpoints/{checkpoint_id}/respond", {"response": "completed"}
            )
            check("检查点报告完成", status == 200)

            status, payload = client.post(
                f"/api/actions/{action_id}/closure",
                {"skipped": True},
            )
            check("跳过收尾仍保存最小执行证据", status == 200)

            state = client.get("/api/state")[1]
            action_view = next(item for item in state["actions"] if item["id"] == action_id)
            check("行动结束于完成状态", action_view["status"] == "completed")
            check("无悬空执行状态", state["activeSession"] is None and state["pendingClosure"] is None)

            print("== 用户主动操作（未决记录） ==")
            new_start = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            status, payload = client.post(f"/api/plans", {"sourceText": "E2E 方案二"})
            wait_for(lambda: client.get("/api/state")[1]["draft"]["status"] == "ready", 10, "第二份草案")
            plan2 = client.get("/api/state")[1]["plan"]["id"]
            client.post(f"/api/plans/{plan2}/candidates/c1/confirm", {"title": "第二项", "plannedStartAt": new_start, "estimatedMinutes": 25})
            status, payload = client.post(f"/api/plans/{plan2}/enable", {})
            check("重新导入并启用（旧方案被取代）", status == 200)
            state = client.get("/api/state")[1]
            old_action = next(item for item in state["actions"] if item["id"] == action_id)
            check("旧方案行动明确取消而非抹除", old_action["status"] == "cancelled_superseded")

            action2 = payload["actionIds"][0]
            status, _ = client.post(f"/api/actions/{action2}/skip-today", {})
            check("用户主动放下（今天不做）", status == 200)
            state = client.get("/api/state")[1]
            action_view = next(item for item in state["actions"] if item["id"] == action2)
            check("放下后进入稳定状态", action_view["status"] == "cancelled_today")

        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()

    failed = [name for name, ok in checks if not ok]
    print(f"\n端到端结果：{len(checks) - len(failed)}/{len(checks)} 通过")
    if failed:
        for name in failed:
            print(f"  FAILED: {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
