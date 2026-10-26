"""Independent Chat 08 regression for stale recovery acknowledgements.

This test is intentionally red on the baseline.  A recovery acknowledgement that
cannot prove which recovery attempt produced it must not complete a later recovery
attempt merely because its signal id and monotonic tick are fresh.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from anka_contracts.workflow import MissionConfigSpec, WorkflowSignal
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow


ROOT = Path(__file__).resolve().parents[1]


def _mission():
    config = MissionConfigSpec(
        "sufokia_direction_cycle",
        1,
        8,
        2,
        3,
        False,
        False,
        "a" * 64,
    )
    return compile_mission(
        config,
        ROOT / "assets" / "workflow" / "routes.json",
        watchdog_budget_ticks=1,
        recovery_budget=2,
    )


def _signal(number: int, kind: str, tick: int, *, fight_epoch: int | None = None):
    return WorkflowSignal(
        f"wfsig-agent08-recovery-{number}",
        kind,
        tick,
        (f"evidence-agent08-recovery-{number}",),
        fight_epoch=fight_epoch,
    )


class TestAgent08RecoveryCorrelation(unittest.TestCase):
    def test_uncorrelated_old_recovery_success_cannot_clear_newer_recovery_attempt(self):
        workflow = MissionWorkflow("run-agent08-recovery-correlation", _mission())

        steps = (
            ("START", 0, None),
            ("PREFLIGHT_OK", 1, None),
            ("ENCOUNTER_SELECTED", 2, None),
            ("FIGHT_ENTRY_PROVEN", 3, 1),
            ("PARTY_JOIN_PROVEN", 4, 1),
            ("PLACEMENT_PROVEN", 5, 1),
            ("READY_PROVEN", 6, 1),
        )
        for number, (kind, tick, fight_epoch) in enumerate(steps, 1):
            result = workflow.apply(
                _signal(number, kind, tick, fight_epoch=fight_epoch)
            )
            self.assertEqual(result.status, "APPLIED", result.reason)

        first_deadline = workflow.snapshot().watchdog_deadline_tick
        first_recovery = workflow.apply(
            _signal(20, "WATCHDOG", first_deadline + 1)
        )
        self.assertEqual(first_recovery.snapshot.phase, "RECOVERING")

        second_deadline = first_recovery.snapshot.watchdog_deadline_tick
        second_recovery = workflow.apply(
            _signal(21, "WATCHDOG", second_deadline + 1)
        )
        self.assertEqual(second_recovery.snapshot.phase, "RECOVERING")
        self.assertLess(
            second_recovery.snapshot.recovery_budget_remaining,
            first_recovery.snapshot.recovery_budget_remaining,
        )

        # This acknowledgement carries no recovery-attempt identity.  It could
        # have been emitted by attempt A after attempt B was already started.
        stale_success = workflow.apply(
            _signal(
                22,
                "RECOVERY_SUCCEEDED",
                second_recovery.snapshot.phase_started_tick + 1,
            )
        )

        self.assertEqual(
            stale_success.status,
            "REJECTED",
            "An uncorrelated recovery result from an older attempt can currently "
            "complete the newest RECOVERING state.",
        )
        self.assertEqual(stale_success.snapshot.phase, "RECOVERING")


if __name__ == "__main__":
    unittest.main()
