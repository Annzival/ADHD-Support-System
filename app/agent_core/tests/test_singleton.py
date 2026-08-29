"""单实例保护测试：第二个核心必须被拒绝，否则会出现重复调度。

这些测试保护 ADR-0010（智能体核心是唯一状态权威）与 ADR-0012（错过的干预
合并为一次）：同一份权威状态若被两个调度器扫描，开始干预与恢复干预都会被重复送达。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_core.singleton import (
    EXIT_CODE_ALREADY_RUNNING,
    CoreAlreadyRunning,
    acquire_instance_lock,
)


def test_second_core_is_rejected(tmp_path: Path) -> None:
    lock_path = tmp_path / "agent-core.lock"

    first = acquire_instance_lock(lock_path, "pid=111 database=one.sqlite3")
    try:
        with pytest.raises(CoreAlreadyRunning) as error:
            acquire_instance_lock(lock_path, "pid=222")
        # 错误信息必须能指出持有者，否则人工排查时无从下手。
        assert "pid=111" in error.value.owner
    finally:
        first.close()


def test_lock_is_released_after_close(tmp_path: Path) -> None:
    lock_path = tmp_path / "agent-core.lock"

    first = acquire_instance_lock(lock_path, "pid=111")
    first.close()

    second = acquire_instance_lock(lock_path, "pid=222")
    try:
        # 第 0 字节是锁，Windows 会拒绝读取；持有者信息从偏移 1 开始。
        with open(lock_path, "rb") as handle:
            handle.seek(1)
            assert handle.read() == b"pid=222"
    finally:
        second.close()


def test_owner_info_readable_while_lock_held(tmp_path: Path) -> None:
    """持有者信息必须写在锁字节之后，才能在锁被持有时仍然可读。"""

    lock_path = tmp_path / "agent-core.lock"
    holder = acquire_instance_lock(lock_path, "pid=999 endpoint=http://127.0.0.1:1")
    try:
        with open(lock_path, "rb") as handle:
            handle.seek(1)
            assert handle.read().decode("utf-8") == "pid=999 endpoint=http://127.0.0.1:1"
    finally:
        holder.close()


def test_exit_code_contract() -> None:
    """宿主依赖这个退出码区分"已在运行"与"启动失败"。"""

    assert EXIT_CODE_ALREADY_RUNNING == 3
