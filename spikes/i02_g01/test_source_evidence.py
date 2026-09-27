"""摘要器最小验证；不启动 Core、宿主或 Go 矩阵。"""
import hashlib
import unittest
from .source_evidence import checked_source


class SourceEvidenceTests(unittest.TestCase):
    def test_crlf_checkout_matches_lf_commit_but_hashes_keep_raw_bytes(self):
        committed = b'first\nsecond\n'
        working = b'first\r\nsecond\r\n'
        result = checked_source(committed, working, 'fixture.py')
        self.assertEqual(result['git_sha256'], hashlib.sha256(committed).hexdigest())
        self.assertEqual(result['worktree_sha256'], hashlib.sha256(working).hexdigest())
        self.assertNotEqual(result['git_sha256'], result['worktree_sha256'])
        self.assertEqual(checked_source(committed, committed, 'fixture.py')['git_sha256'], result['git_sha256'])

    def test_real_changes_are_rejected_even_with_crlf(self):
        for working in (b'first\r\nchanged\r\n', b'first \r\nsecond\r\n',
                        b'first\r\nsecond', b'first\rsecond\r'):
            with self.subTest(working=working):
                with self.assertRaisesRegex(AssertionError, 'uncommitted source: fixture.py'):
                    checked_source(b'first\nsecond\n', working, 'fixture.py')
