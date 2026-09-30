"""原宿主进程对象及首次绑定；仅持有运行期材料，不保存设备事实。"""
import secrets
import threading
import uuid

from .process_identity import ProcessIdentity


class HostIdentity:
    def __init__(self, opener=ProcessIdentity):
        self.core_run = str(uuid.uuid4())
        self.opener = opener
        self.lock = threading.RLock()
        self.pending = {}
        self.bound = {}

    def challenge(self, host_run, pid):
        if not isinstance(host_run, str) or not 32 <= len(host_run) <= 128:
            raise ValueError('invalid_host_run')
        with self.lock:
            old = self.pending.pop(host_run, None)
            if old:
                old[1].close()
            identity = self.opener(pid)
            try:
                if not identity.alive():
                    raise OSError('host_exited')
                challenge = dict(core_run=self.core_run, host_run=host_run, pid=pid,
                                 instance=identity.instance, nonce=secrets.token_hex(32))
                self.pending[host_run] = (challenge, identity)
                return challenge
            except BaseException:
                identity.close()
                raise

    def confirm(self, challenge):
        with self.lock:
            candidate = self.pending.get(challenge.get('host_run'))
            if candidate is None or candidate[0] != challenge:
                raise ValueError('invalid_host_challenge')
            _, identity = candidate
            if not identity.alive():
                raise OSError('host_exited')
            del self.pending[challenge['host_run']]
            self.bound[identity.instance] = (challenge['host_run'], identity)
            return {key: challenge[key] for key in ('core_run', 'host_run', 'instance')}

    def check(self, binding):
        with self.lock:
            if binding.get('core_run') != self.core_run:
                raise OSError('previous_core_run')
            candidate = self.bound.get(binding.get('instance'))
            if candidate is None or candidate[0] != binding.get('host_run'):
                raise OSError('unknown_host_instance')
            if not candidate[1].alive():
                raise OSError('host_exited')

    def close(self):
        with self.lock:
            for _, identity in (*self.pending.values(), *self.bound.values()):
                identity.close()
            self.pending.clear()
            self.bound.clear()
