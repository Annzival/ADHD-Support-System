"""实验用进程实例句柄；观测退出，不锁住进程生命期或 SQLite 提交。"""
import os
import sys
import uuid


class ProcessIdentity:
    def __init__(self, pid):
        if type(pid) is not int or pid <= 0:
            raise OSError('missing_process_identity')
        self.pid = pid
        self.instance = str(uuid.uuid4())  # Core's label for the retained OS object.
        self.closed = False
        if sys.platform == 'linux':
            import select
            self.handle = os.pidfd_open(pid, 0)
            self.poll = select.poll()
            self.poll.register(self.handle, select.POLLIN | select.POLLHUP | select.POLLERR)
        elif sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            self.api = ctypes.WinDLL('kernel32', use_last_error=True)
            self.api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self.api.OpenProcess.restype = wintypes.HANDLE
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.WaitForSingleObject.restype = wintypes.DWORD
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]
            self.api.CloseHandle.restype = wintypes.BOOL
            self.handle = self.api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE only
            if not self.handle:
                raise OSError('process_handle_unavailable')
        else:
            raise OSError('unsupported_process_identity_platform')

    def alive(self):
        if self.closed:
            raise OSError('process_handle_unavailable')
        if sys.platform == 'linux':
            events = self.poll.poll(0)
            if not events:
                return True
            import select
            if any(flags & (select.POLLERR | select.POLLNVAL) for _, flags in events):
                raise OSError('process_handle_unavailable')
            return False
        status = self.api.WaitForSingleObject(self.handle, 0)
        if status == 258:  # WAIT_TIMEOUT: process object not signaled at this observation.
            return True
        if status == 0:  # WAIT_OBJECT_0
            return False
        raise OSError('process_wait_failed')

    def close(self):
        if not self.closed:
            self.closed = True
            if sys.platform == 'linux':
                os.close(self.handle)
            else:
                self.api.CloseHandle(self.handle)
