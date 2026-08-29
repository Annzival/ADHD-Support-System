"""组合根：把存储、服务、API、调度线程和草案任务装配成可运行的核心进程。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from .api import ApiContext, CoreApiServer, write_private_bootstrap
from .clock import Clock, SystemClock
from .draft import run_draft_job
from .service import Service
from .store import Store


class AgentCoreApp:
    def __init__(
        self,
        database_path: Path,
        frontend_dir: Path | None = None,
        clock: Clock | None = None,
        tick_interval_seconds: float = 2.0,
    ) -> None:
        self.clock = clock or SystemClock()
        self.store = Store(database_path)
        self.store.initialise()
        self.tick_interval = tick_interval_seconds
        self.service = Service(self.store, self.clock, broadcast=self._broadcast)
        self.service.on_plan_imported = self._on_plan_imported
        self.api_context = ApiContext(self.service, self.clock, frontend_dir)
        self.api_context.on_shutdown = self._request_stop
        self.server = CoreApiServer(self.api_context)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # -- 生命周期 -----------------------------------------------------------

    def start(self, bootstrap_path: Path) -> str:
        self.server.start()
        write_private_bootstrap(bootstrap_path, self.server.endpoint, self.api_context.token)
        self._start_background("scheduler", self._scheduler_loop)
        self._start_background("pinger", self._ping_loop)
        # 启动即执行一次确定性恢复扫描（Core/PC 重启后的恢复路径）。
        self._start_background("recovery", self._initial_recovery_scan)
        return self.server.endpoint

    def stop(self) -> None:
        self._stop.set()
        self.server.shutdown()
        self.store.close()

    def _request_stop(self) -> None:
        # 从 HTTP 线程触发；shutdown 自带独立逻辑且幂等。
        threading.Thread(target=self.stop, daemon=True).start()

    def _start_background(self, name: str, target) -> None:
        thread = threading.Thread(target=target, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)

    # -- 后台任务 -----------------------------------------------------------

    def _scheduler_loop(self) -> None:
        while not self._stop.wait(self.tick_interval):
            try:
                self.service.tick()
            except Exception:  # noqa: BLE001 - 调度循环不得因单次失败退出
                continue

    def _ping_loop(self) -> None:
        while not self._stop.wait(20.0):
            try:
                self.api_context.registry.ping_all()
            except Exception:  # noqa: BLE001
                continue

    def _initial_recovery_scan(self) -> None:
        # 等首次 tick 完成离线过期整理后再生成恢复干预。
        if not self._stop.wait(self.tick_interval + 0.5):
            try:
                self.service.run_recovery_scan()
            except Exception:  # noqa: BLE001
                pass

    # -- 装配回调 ------------------------------------------------------------

    def _broadcast(self, event: dict[str, Any]) -> None:
        self.server.broadcast(event)

    def _on_plan_imported(self, plan_id: str, source_text: str, source_version: int) -> None:
        run_draft_job(self.service, plan_id, source_text, source_version)
