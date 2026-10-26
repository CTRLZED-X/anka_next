"""Independent Chat 08 adversarial QA tests.

These tests must not patch production code.  They define evidence contracts that a
release verifier must satisfy before its receipts can be treated as environment-
bound proof.
"""
from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import tools.verify_q9 as q9


class TestAgent08VerifierCheckpointProvenance(TestCase):
    """A cached staged PASS must not be relabeled as a different runtime."""

    @staticmethod
    def _runtime(module, label: str) -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(module.sys, "version", f"3.13.{label} QA"))
        stack.enter_context(patch.object(module.sys, "executable", f"/qa/python-{label}"))
        stack.enter_context(
            patch.object(
                module,
                "environment_pairs",
                return_value=(
                    ("implementation", "CPython"),
                    ("machine", "qa"),
                    ("platform", f"QA-{label}"),
                    ("python", f"3.13.{label}"),
                ),
            )
        )
        return stack

    def test_q9_finalize_rejects_stage_checkpoint_from_different_runtime(self):
        """Environment A stage results cannot become an environment B PASS receipt.

        Baseline counterexample:
        1. q9a/q9b/p20 are cached while runtime A is active.
        2. Source/scope files remain byte-identical.
        3. Runtime changes to B.
        4. finalize() must reject the cached stages instead of stamping a fresh
           receipt with B's runtime metadata.

        The M12_006 baseline is expected to fail this QA regression until the
        checkpoint itself is execution-environment bound.
        """
        with TemporaryDirectory() as td:
            root = Path(td)
            checkpoint = root / "q9_checkpoint.json"
            receipt = root / "q9_receipt.json"

            with patch.object(q9, "CHECKPOINT", checkpoint), patch.object(q9, "OUT", receipt):
                with self._runtime(q9, "1"):
                    q9.save("q9a", {"rc": 0, "passed": 4, "subtests": 0, "tail": ""})
                    q9.save("q9b", {"rc": 0, "passed": 5, "subtests": 0, "tail": ""})
                    q9.save("p20", {"rc": 0, "passed": 13, "subtests": 0, "tail": ""})

                with self._runtime(q9, "2"):
                    rc = q9.finalize()

            self.assertNotEqual(
                rc,
                0,
                "Q9 finalized cached PASS stages produced by a different execution runtime",
            )
