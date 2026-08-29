"""智能体核心进程入口。

    python -m agent_core --bootstrap-file <path> [--database <path>] [--frontend-dir <path>]

仅绑定 127.0.0.1 动态端口，把端点与一次性临时令牌写入 bootstrap 文件后由宿主消费。
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from .app import AgentCoreApp
from .singleton import EXIT_CODE_ALREADY_RUNNING, CoreAlreadyRunning, acquire_instance_lock


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADHD 执行支持系统 智能体核心")
    parser.add_argument("--bootstrap-file", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument("--frontend-dir", type=Path, default=None)
    parser.add_argument("--tick-interval", type=float, default=2.0)
    return parser.parse_args(argv)


def default_database_path() -> Path:
    home = Path.home()
    for base in (home / "AppData" / "Roaming" / "ADHDSupportSystem", home / ".adhd-support-system"):
        try:
            base.mkdir(parents=True, exist_ok=True)
            return base / "agent_core.sqlite3"
        except OSError:
            continue
    return Path("agent_core.sqlite3")


def main(argv: list[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    database = arguments.database or default_database_path()

    # 单实例保护必须在打开数据库之前完成：第二个核心会重复扫描同一份权威状态，
    # 可能重复送达开始干预或重复生成恢复干预（违反 ADR-0012、ADR-0016）。
    lock_path = database.parent / "agent-core.lock"
    try:
        instance_lock = acquire_instance_lock(lock_path, f"pid={os.getpid()} database={database}")
    except CoreAlreadyRunning as error:
        print(f"agent-core 已退出：{error}", flush=True)
        return EXIT_CODE_ALREADY_RUNNING

    app = AgentCoreApp(
        database_path=database,
        frontend_dir=arguments.frontend_dir if arguments.frontend_dir else None,
        tick_interval_seconds=arguments.tick_interval,
    )
    endpoint = app.start(arguments.bootstrap_file)
    print(f"agent-core ready at {endpoint}", flush=True)

    stop_requested = False

    def _handle_signal(*_args: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    for signame in ("SIGINT", "SIGTERM"):
        handler = getattr(signal, signame, None)
        if handler is not None:
            try:
                signal.signal(handler, _handle_signal)
            except (ValueError, OSError):  # pragma: no cover
                pass
    try:
        import time

        while not stop_requested:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        instance_lock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
