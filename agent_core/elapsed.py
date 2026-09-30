"""同机明确计时源；墙钟不参与耗时。失败只丢失计时依据。"""
import sys
import time


def read_elapsed():
    try:
        if sys.platform == 'linux':
            return dict(clock='linux_boottime_v1', ticks=time.clock_gettime_ns(time.CLOCK_BOOTTIME), frequency=1_000_000_000)
        if sys.platform == 'win32':
            import ctypes
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            counter, frequency = ctypes.c_longlong(), ctypes.c_longlong()
            for name in ('QueryPerformanceCounter', 'QueryPerformanceFrequency'):
                fn = getattr(api, name)
                fn.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
                fn.restype = ctypes.c_int
            if api.QueryPerformanceFrequency(ctypes.byref(frequency)) and api.QueryPerformanceCounter(ctypes.byref(counter)):
                return dict(clock='windows_qpc_v1', ticks=counter.value, frequency=frequency.value)
    except (OSError, AttributeError, ValueError):
        pass
    return None


def valid(mark):
    return (isinstance(mark, dict) and isinstance(mark.get('clock'), str)
            and type(mark.get('ticks')) is int and mark['ticks'] >= 0
            and type(mark.get('frequency')) is int and mark['frequency'] > 0)


def comparable(*marks):
    return all(valid(m) for m in marks) and len({(m['clock'], m['frequency']) for m in marks}) == 1
