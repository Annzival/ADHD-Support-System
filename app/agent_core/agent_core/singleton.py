"""智能体核心的单实例保护。

智能体核心是 v0.1 唯一的状态权威（ADR-0010）。如果同一台机器上出现第二个核心进程，
两个调度器会各自扫描同一份 SQLite 状态，可能重复送达开始干预、重复生成恢复干预，
直接违反 ADR-0012（错过的干预合并为一次）与 ADR-0016（沉默保持未知）。

因此在打开数据库之前先取得一个排他锁文件。该锁在进程退出时由操作系统释放，
即使进程被强制结束也不会残留为永久阻塞；它只解决"进程仍在运行时"的并发问题。

锁文件路径与数据库同目录，便于宿主和人工排查时一并发现。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

LOCK_FILENAME = "agent-core.lock"
EXIT_CODE_ALREADY_RUNNING = 3

# 只锁第 0 字节。Windows 的字节区间锁会拒绝其他句柄读取被锁定区域，
# 因此持有者信息从第 1 字节开始存放，才能在锁被持有时仍然可读。
_LOCK_LENGTH = 1
_OWNER_OFFSET = 1


class CoreAlreadyRunning(Exception):
    """另一个智能体核心进程已经持有同一份权威状态。"""

    def __init__(self, lock_path: Path, owner: str) -> None:
        super().__init__(f"另一个智能体核心正在运行（{owner}），本次启动已退出以避免重复调度")
        self.lock_path = lock_path
        self.owner = owner


class _InstanceLock:
    def __init__(self, path: Path, handle: Any) -> None:
        self.path = path
        self._handle = handle

    def close(self) -> None:
        if self._handle is None:
            return
        try:
            self._release(self._handle)
        except OSError:
            pass
        try:
            os.close(self._handle)
        except OSError:
            pass
        self._handle = None

    @staticmethod
    def _release(fd: int) -> None:
        if os.name == "nt":  # pragma: no cover - 平台分支
            import msvcrt

            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, _LOCK_LENGTH)
            except OSError:
                pass
        else:  # pragma: no cover - 平台分支
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)

    def __del__(self) -> None:  # pragma: no cover - 尽力而为
        self.close()


def _try_lock(fd: int) -> bool:
    if os.name == "nt":  # pragma: no cover - 平台分支
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, _LOCK_LENGTH)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _read_owner(path: Path) -> str:
    try:
        with open(path, "rb") as handle:
            handle.seek(_OWNER_OFFSET)
            contents = handle.read().decode("utf-8", errors="replace").strip()
    except OSError:
        return "持有者信息不可读"
    return contents or "持有者信息为空"


def acquire_instance_lock(lock_path: Path, owner_info: str) -> _InstanceLock:
    """取得排他锁；失败时抛出 CoreAlreadyRunning，不修改任何已有状态。"""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # Windows 的字节区间锁要求被锁定区域存在；持有者总会写入自身信息，
        # 因此长度为 0 的锁文件意味着没有存活持有者，补一个占位字节是安全的。
        if os.fstat(fd).st_size < _LOCK_LENGTH:
            os.write(fd, b" ")
            os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        if not _try_lock(fd):
            raise CoreAlreadyRunning(lock_path, _read_owner(lock_path))
        # 已取得排他锁，此时才允许改写持有者信息（写在锁字节之后）。
        payload = owner_info.encode("utf-8")
        os.ftruncate(fd, _OWNER_OFFSET + len(payload))
        os.lseek(fd, _OWNER_OFFSET, os.SEEK_SET)
        os.write(fd, payload)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        raise
    return _InstanceLock(lock_path, fd)
