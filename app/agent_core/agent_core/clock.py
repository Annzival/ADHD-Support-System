"""时钟与本地时区工具。

权威状态中的时间一律以 UTC ISO-8601 字符串保存（``...Z`` 后缀）；
与用户相关的过期边界（执行窗口结束、次日 00:00、安静时段）按宿主本地时区计算。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def utc_now_iso(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must be timezone-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


class Clock:
    """可注入时钟；测试使用 ``FixedClock``，运行时使用 ``SystemClock``。"""

    def now_utc(self) -> datetime:
        raise NotImplementedError

    def local_tz(self) -> ZoneInfo:
        raise NotImplementedError

    def now_iso(self) -> str:
        return utc_now_iso(self.now_utc())

    def local_now(self) -> datetime:
        return self.now_utc().astimezone(self.local_tz())

    def next_local_midnight(self, moment: datetime | None = None) -> datetime:
        """下一个本地 00:00（严格晚于给定时刻）。"""

        local = (moment or self.now_utc()).astimezone(self.local_tz())
        upcoming = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return upcoming

    def local_window_end(self, moment: datetime | None = None, window_end: str = "23:00") -> datetime:
        """今天本地执行窗口结束时刻（已过则取明天同时刻）。"""

        hour, minute = _parse_hhmm(window_end)
        local = (moment or self.now_utc()).astimezone(self.local_tz())
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate

    def in_quiet_hours(self, moment: datetime | None = None, quiet_start: str = "22:00", quiet_end: str = "08:00") -> bool:
        local = (moment or self.now_utc()).astimezone(self.local_tz())
        start_h, start_m = _parse_hhmm(quiet_start)
        end_h, end_m = _parse_hhmm(quiet_end)
        current = time(local.hour, local.minute)
        start = time(start_h, start_m)
        end = time(end_h, end_m)
        if start == end:
            return False
        if start < end:
            return start <= current < end
        return current >= start or current < end


def _parse_hhmm(value: str) -> tuple[int, int]:
    parts = value.strip().split(":")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid HH:MM value: {value!r}")
    return hour, minute


class SystemClock(Clock):
    """使用宿主本地时区；Windows 上没有 IANA 数据库时可回退到系统偏移。"""

    def now_utc(self) -> datetime:
        return datetime.now(timezone.utc)

    def local_tz(self) -> ZoneInfo:
        try:
            local_name = datetime.now().astimezone().tzname()
            if local_name and local_name in ZoneInfo.available_names():
                return ZoneInfo(local_name)
        except Exception:
            pass
        offset = datetime.now().astimezone().utcoffset()
        return timezone(offset) if offset is not None else timezone.utc


class FixedClock(Clock):
    def __init__(self, start: datetime, tz: str = "Asia/Shanghai") -> None:
        self._now = start.astimezone(timezone.utc)
        self._tz = ZoneInfo(tz)

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)

    def advance_from_utc_to(self, target: str) -> None:
        parsed = datetime.fromisoformat(target.replace("Z", "+00:00")).astimezone(timezone.utc)
        if parsed < self._now:
            raise ValueError(f"cannot move clock backwards: {target}")
        self._now = parsed

    def now_utc(self) -> datetime:
        return self._now

    def local_tz(self) -> ZoneInfo:
        return self._tz


def sqlite_utc_iso(value: datetime) -> str:
    return utc_now_iso(value)


def ensure_sqlite_parsing(connection: sqlite3.Connection) -> None:  # pragma: no cover - defensive
    connection.execute("PRAGMA trusted_schema = OFF")
