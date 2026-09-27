"""只允许 Git checkout 的 CRLF/LF 转换，保留两套原始字节哈希。"""
import hashlib


def checked_source(committed, working, path):
    if committed.replace(b'\r\n', b'\n') != working.replace(b'\r\n', b'\n'):
        raise AssertionError(f'uncommitted source: {path}')
    return {
        'git_sha256': hashlib.sha256(committed).hexdigest(),
        'worktree_sha256': hashlib.sha256(working).hexdigest(),
    }
