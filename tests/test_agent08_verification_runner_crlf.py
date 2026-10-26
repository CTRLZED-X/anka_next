"""Independent Chat 08 regression for Windows CRLF verifier output.

The project is Windows-targeted. unittest output written through a Windows text
stream uses CRLF; the isolated verifier must recognize a successful completion
marker without requiring POSIX-only LF bytes.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import unittest

from anka_app.verification_runner import verify_isolated


class TestAgent08VerificationRunnerCRLF(unittest.TestCase):
    def test_windows_crlf_ok_marker_is_a_success_not_false_failure(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "tests").mkdir()
            (root / "src").mkdir()
            (root / "tests" / "test_case.py").write_text(
                "import unittest\n"
                "class Unit(unittest.TestCase):\n"
                "    def test_truth(self): self.assertTrue(True)\n",
                encoding="utf8",
            )

            def windows_style_success(argv, **_kwargs):
                return subprocess.CompletedProcess(
                    argv,
                    0,
                    "test_truth (test_case.Unit.test_truth) ... ok\r\n"
                    "\r\nRan 1 test in 0.001s\r\n"
                    "\r\nOK\r\n",
                    "",
                )

            result = verify_isolated(
                root,
                shards=1,
                per_shard_timeout=20,
                run=windows_style_success,
            )
            self.assertEqual(result.status, "PASS")
            self.assertEqual(result.tests_passed, 1)


if __name__ == "__main__":
    unittest.main()
