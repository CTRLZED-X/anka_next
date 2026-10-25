from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from anka_contracts.workflow import (
    MissionConfigSpec,
    WorkflowSignal,
    initial_workflow_progress_token,
)
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow, WorkflowRejected


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "assets" / "workflow" / "routes.json"


def mission(*, watchdog: int = 1, recovery: int = 3):
    config = MissionConfigSpec(
        "sufokia_direction_cycle",
        1,
        8,
        2,
        3,
        False,
        False,
        "b" * 64,
    )
    return compile_mission(
        config,
        ROUTES,
        watchdog_budget_ticks=watchdog,
        recovery_budget=recovery,
    )


def signal(
    number: int,
    kind: str,
    tick: int,
    *,
    fight_epoch: int | None = None,
    recovery_generation: int | None = None,
):
    return WorkflowSignal(
        f"wfsig-agent06-phaseb-{number}",
        kind,
        tick,
        (f"evidence-agent06-phaseb-{number}",),
        fight_epoch=fight_epoch,
        recovery_generation=recovery_generation,
    )


def advance_to_ready(workflow: MissionWorkflow) -> None:
    sequence = (
        signal(1, "START", 0),
        signal(2, "PREFLIGHT_OK", 1),
        signal(3, "ENCOUNTER_SELECTED", 2),
        signal(4, "FIGHT_ENTRY_PROVEN", 3, fight_epoch=1),
        signal(5, "PARTY_JOIN_PROVEN", 4, fight_epoch=1),
        signal(6, "PLACEMENT_PROVEN", 5, fight_epoch=1),
        signal(7, "READY_PROVEN", 6, fight_epoch=1),
    )
    for item in sequence:
        result = workflow.apply(item)
        if result.status != "APPLIED":
            raise AssertionError((item.kind, result.status, result.reason))
    if workflow.snapshot().phase != "READY":
        raise AssertionError(workflow.snapshot().phase)


def start_recovery(workflow: MissionWorkflow, number: int):
    snap = workflow.snapshot()
    return workflow.apply(
        signal(number, "WATCHDOG", snap.watchdog_deadline_tick + 1)
    )


class Agent06Issue32PhaseBTests(unittest.TestCase):
    def test_initial_snapshot_uses_phase_a_authority(self):
        workflow = MissionWorkflow("run-agent06-phaseb-initial", mission())
        snapshot = workflow.snapshot()

        self.assertEqual(snapshot.recovery_generation, 0)
        self.assertIsNone(snapshot.active_recovery_generation)
        self.assertEqual(snapshot.last_processed_tick, 0)
        self.assertEqual(
            snapshot.progress_token,
            initial_workflow_progress_token(snapshot.run_id),
        )

    def test_recovery_attempt_a_to_b_mints_fresh_generation_and_keeps_target(self):
        workflow = MissionWorkflow("run-agent06-phaseb-a-b", mission())
        advance_to_ready(workflow)

        attempt_a = start_recovery(workflow, 20)
        self.assertEqual(attempt_a.snapshot.phase, "RECOVERING")
        self.assertEqual(attempt_a.snapshot.recovery_generation, 1)
        self.assertEqual(attempt_a.snapshot.active_recovery_generation, 1)
        self.assertEqual(attempt_a.snapshot.resume_phase, "READY")

        attempt_b = start_recovery(workflow, 21)
        self.assertEqual(attempt_b.snapshot.phase, "RECOVERING")
        self.assertEqual(attempt_b.snapshot.recovery_generation, 2)
        self.assertEqual(attempt_b.snapshot.active_recovery_generation, 2)
        self.assertEqual(attempt_b.snapshot.resume_phase, "READY")
        self.assertLess(
            attempt_b.snapshot.last_processed_tick,
            attempt_b.snapshot.watchdog_deadline_tick,
        )

    def test_stale_a_success_and_failure_cannot_settle_b(self):
        workflow = MissionWorkflow("run-agent06-phaseb-stale-a", mission())
        advance_to_ready(workflow)
        start_recovery(workflow, 30)
        attempt_b = start_recovery(workflow, 31)
        watermark = attempt_b.snapshot.last_processed_tick

        for number, kind in (
            (32, "RECOVERY_SUCCEEDED"),
            (33, "RECOVERY_FAILED"),
        ):
            with self.subTest(kind=kind):
                result = workflow.apply(
                    signal(
                        number,
                        kind,
                        watermark + 1,
                        recovery_generation=1,
                    )
                )
                self.assertEqual(result.status, "REJECTED")
                self.assertEqual(
                    result.reason,
                    "RECOVERY_OUTCOME_STALE_GENERATION",
                )
                self.assertEqual(result.snapshot.phase, "RECOVERING")
                self.assertEqual(result.snapshot.active_recovery_generation, 2)
                self.assertEqual(result.snapshot.last_processed_tick, watermark)

    def test_missing_and_future_recovery_generation_fail_closed(self):
        workflow = MissionWorkflow("run-agent06-phaseb-bad-generation", mission())
        advance_to_ready(workflow)
        start_recovery(workflow, 40)
        attempt_b = start_recovery(workflow, 41)
        tick = attempt_b.snapshot.last_processed_tick + 1

        missing = workflow.apply(signal(42, "RECOVERY_SUCCEEDED", tick))
        self.assertEqual(missing.status, "REJECTED")
        self.assertEqual(missing.reason, "RECOVERY_IDENTITY_MISSING")

        future = workflow.apply(
            signal(
                43,
                "RECOVERY_FAILED",
                tick,
                recovery_generation=3,
            )
        )
        self.assertEqual(future.status, "REJECTED")
        self.assertEqual(
            future.reason,
            "RECOVERY_OUTCOME_FUTURE_GENERATION",
        )
        self.assertEqual(
            future.snapshot.last_processed_tick,
            attempt_b.snapshot.last_processed_tick,
        )

    def test_matching_success_b_settles_and_duplicate_is_non_authoritative(self):
        workflow = MissionWorkflow("run-agent06-phaseb-success-b", mission())
        advance_to_ready(workflow)
        start_recovery(workflow, 50)
        attempt_b = start_recovery(workflow, 51)

        settled = workflow.apply(
            signal(
                52,
                "RECOVERY_SUCCEEDED",
                attempt_b.snapshot.last_processed_tick + 1,
                recovery_generation=2,
            )
        )
        self.assertEqual(settled.status, "APPLIED")
        self.assertEqual(settled.snapshot.phase, "READY")
        self.assertEqual(settled.snapshot.recovery_generation, 2)
        self.assertIsNone(settled.snapshot.active_recovery_generation)
        settled_watermark = settled.snapshot.last_processed_tick
        settled_history = settled.snapshot.processed_signal_ids

        duplicate = workflow.apply(
            signal(
                53,
                "RECOVERY_SUCCEEDED",
                settled_watermark + 20,
                recovery_generation=2,
            )
        )
        self.assertEqual(duplicate.status, "DUPLICATE")
        self.assertEqual(
            duplicate.reason,
            "RECOVERY_OUTCOME_ALREADY_NONCURRENT",
        )
        self.assertEqual(duplicate.snapshot.last_processed_tick, settled_watermark)
        self.assertEqual(duplicate.snapshot.processed_signal_ids, settled_history)

    def test_matching_failure_b_blocks_and_clears_active_generation(self):
        workflow = MissionWorkflow("run-agent06-phaseb-failure-b", mission())
        advance_to_ready(workflow)
        start_recovery(workflow, 60)
        attempt_b = start_recovery(workflow, 61)

        failed = workflow.apply(
            signal(
                62,
                "RECOVERY_FAILED",
                attempt_b.snapshot.last_processed_tick + 1,
                recovery_generation=2,
            )
        )
        self.assertEqual(failed.status, "APPLIED")
        self.assertEqual(failed.snapshot.phase, "BLOCKED")
        self.assertEqual(failed.snapshot.terminal_reason, "RECOVERY_FAILED")
        self.assertEqual(failed.snapshot.recovery_generation, 2)
        self.assertIsNone(failed.snapshot.active_recovery_generation)

        duplicate = workflow.apply(
            signal(
                63,
                "RECOVERY_FAILED",
                failed.snapshot.last_processed_tick + 10,
                recovery_generation=2,
            )
        )
        self.assertEqual(duplicate.status, "DUPLICATE")
        self.assertEqual(
            duplicate.reason,
            "RECOVERY_OUTCOME_ALREADY_NONCURRENT",
        )

    def test_semantic_and_nonprogress_signals_advance_watermark(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-watermark",
            mission(watchdog=5),
        )

        started = workflow.apply(signal(70, "START", 4))
        self.assertEqual(started.snapshot.last_processed_tick, 4)

        world = workflow.apply(signal(71, "PREFLIGHT_OK", 5))
        self.assertEqual(world.snapshot.phase, "WORLD")
        self.assertEqual(world.snapshot.last_processed_tick, 5)

        observed = workflow.apply(signal(72, "WORLD_OBSERVED", 20))
        self.assertEqual(observed.status, "APPLIED")
        self.assertFalse(observed.semantic_progress)
        self.assertEqual(observed.snapshot.last_processed_tick, 20)

        heartbeat = workflow.apply(signal(73, "HEARTBEAT", 30))
        self.assertEqual(heartbeat.status, "APPLIED")
        self.assertFalse(heartbeat.semantic_progress)
        self.assertEqual(heartbeat.snapshot.last_processed_tick, 30)

    def test_rejected_stale_signal_does_not_advance_watermark(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-stale-tick",
            mission(watchdog=5),
        )
        workflow.apply(signal(80, "START", 0))
        workflow.apply(signal(81, "PREFLIGHT_OK", 1))
        heartbeat = workflow.apply(signal(82, "HEARTBEAT", 100))
        watermark = heartbeat.snapshot.last_processed_tick
        history = heartbeat.snapshot.processed_signal_ids

        rejected = workflow.apply(signal(83, "ENCOUNTER_SELECTED", 60))
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.reason, "MONOTONIC_TICK_REGRESSION")
        self.assertEqual(rejected.snapshot.last_processed_tick, watermark)
        self.assertEqual(rejected.snapshot.processed_signal_ids, history)

    def test_same_tick_is_deterministic_and_watermark_never_decreases(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-same-tick",
            mission(watchdog=5),
        )
        workflow.apply(signal(90, "START", 0))
        workflow.apply(signal(91, "PREFLIGHT_OK", 1))
        first = workflow.apply(signal(92, "HEARTBEAT", 100))
        second = workflow.apply(signal(93, "WORLD_OBSERVED", 100))
        third = workflow.apply(signal(94, "HEARTBEAT", 100))

        self.assertEqual(first.snapshot.last_processed_tick, 100)
        self.assertEqual(second.snapshot.last_processed_tick, 100)
        self.assertEqual(third.snapshot.last_processed_tick, 100)
        self.assertEqual(third.status, "APPLIED")

        stale = workflow.apply(signal(95, "HEARTBEAT", 99))
        self.assertEqual(stale.status, "REJECTED")
        self.assertEqual(stale.snapshot.last_processed_tick, 100)

    def test_nonprogress_watermark_does_not_refresh_semantic_watchdog(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-watchdog-separation",
            mission(watchdog=5),
        )
        workflow.apply(signal(100, "START", 0))
        world = workflow.apply(signal(101, "PREFLIGHT_OK", 1))
        before = world.snapshot

        heartbeat = workflow.apply(signal(102, "HEARTBEAT", 100))
        after = heartbeat.snapshot

        self.assertEqual(after.last_processed_tick, 100)
        self.assertEqual(after.phase_started_tick, before.phase_started_tick)
        self.assertEqual(
            after.watchdog_deadline_tick,
            before.watchdog_deadline_tick,
        )
        self.assertEqual(
            after.progress_generation,
            before.progress_generation,
        )

    def test_resume_below_persisted_watermark_rejects_and_current_succeeds(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-resume-watermark",
            mission(watchdog=5),
        )
        workflow.apply(signal(110, "START", 0))
        workflow.apply(signal(111, "PREFLIGHT_OK", 1))
        workflow.apply(signal(112, "WORLD_OBSERVED", 100))
        snapshot = workflow.snapshot()

        with self.assertRaisesRegex(WorkflowRejected, "RESUME_TICK_REGRESSION"):
            MissionWorkflow.resume(
                workflow.plan,
                snapshot,
                resume_tick=50,
            )

        resumed = MissionWorkflow.resume(
            workflow.plan,
            snapshot,
            resume_tick=100,
        )
        self.assertEqual(resumed.snapshot().last_processed_tick, 100)
        self.assertEqual(resumed.snapshot().phase_started_tick, 100)
        self.assertEqual(resumed.snapshot().watchdog_deadline_tick, 105)

        stale = resumed.apply(signal(113, "ENCOUNTER_SELECTED", 99))
        self.assertEqual(stale.status, "REJECTED")
        self.assertEqual(stale.snapshot.last_processed_tick, 100)

        current = resumed.apply(signal(114, "WORLD_OBSERVED", 100))
        self.assertEqual(current.status, "APPLIED")
        self.assertEqual(current.snapshot.last_processed_tick, 100)

    def test_resume_rejects_missing_phase_b_authority(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-resume-missing",
            mission(watchdog=5),
        )
        workflow.apply(signal(120, "START", 0))
        snapshot = workflow.snapshot()

        no_generation = replace(snapshot, recovery_generation=None)
        with self.assertRaisesRegex(
            WorkflowRejected,
            "RECOVERY_GENERATION_UNPROVEN",
        ):
            MissionWorkflow.resume(
                workflow.plan,
                no_generation,
                resume_tick=1,
            )

        no_watermark = replace(snapshot, last_processed_tick=None)
        with self.assertRaisesRegex(WorkflowRejected, "WATERMARK_UNPROVEN"):
            MissionWorkflow.resume(
                workflow.plan,
                no_watermark,
                resume_tick=1,
            )

    def test_recovering_resume_preserves_active_generation_and_target(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-recovery-resume",
            mission(watchdog=2),
        )
        advance_to_ready(workflow)
        attempt_a = start_recovery(workflow, 130)
        before = attempt_a.snapshot

        resumed = MissionWorkflow.resume(
            workflow.plan,
            before,
            resume_tick=before.last_processed_tick,
        )
        after = resumed.snapshot()
        self.assertEqual(after.phase, "RECOVERING")
        self.assertEqual(after.resume_phase, "READY")
        self.assertEqual(after.recovery_generation, 1)
        self.assertEqual(after.active_recovery_generation, 1)
        self.assertEqual(after.last_processed_tick, before.last_processed_tick)

        attempt_b = start_recovery(resumed, 131)
        self.assertEqual(attempt_b.snapshot.recovery_generation, 2)
        self.assertEqual(attempt_b.snapshot.active_recovery_generation, 2)
        self.assertEqual(attempt_b.snapshot.resume_phase, "READY")

        stale_a = resumed.apply(
            signal(
                132,
                "RECOVERY_SUCCEEDED",
                attempt_b.snapshot.last_processed_tick + 1,
                recovery_generation=1,
            )
        )
        self.assertEqual(stale_a.status, "REJECTED")
        self.assertEqual(stale_a.snapshot.active_recovery_generation, 2)

    def test_recovery_resume_requires_active_generation(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-recovery-missing-active",
            mission(watchdog=2),
        )
        advance_to_ready(workflow)
        recovering = start_recovery(workflow, 140).snapshot
        malformed = replace(recovering, active_recovery_generation=None)

        with self.assertRaisesRegex(
            WorkflowRejected,
            "ACTIVE_RECOVERY_GENERATION_UNPROVEN",
        ):
            MissionWorkflow.resume(
                workflow.plan,
                malformed,
                resume_tick=recovering.last_processed_tick,
            )

    def test_authoritative_progress_supersedes_recovery_and_retires_attempt(self):
        workflow = MissionWorkflow(
            "run-agent06-phaseb-proof-supersedes",
            mission(watchdog=1),
        )
        advance_to_ready(workflow)
        recovering = start_recovery(workflow, 150)

        proof = workflow.apply(
            signal(
                151,
                "FIRST_TURN_PROVEN",
                recovering.snapshot.last_processed_tick + 1,
                fight_epoch=1,
            )
        )
        self.assertEqual(proof.status, "APPLIED")
        self.assertEqual(proof.snapshot.phase, "FIGHT_ACTIVE")
        self.assertEqual(proof.snapshot.recovery_generation, 1)
        self.assertIsNone(proof.snapshot.active_recovery_generation)

        late = workflow.apply(
            signal(
                152,
                "RECOVERY_SUCCEEDED",
                proof.snapshot.last_processed_tick + 1,
                recovery_generation=1,
            )
        )
        self.assertEqual(late.status, "DUPLICATE")
        self.assertEqual(
            late.reason,
            "RECOVERY_OUTCOME_ALREADY_NONCURRENT",
        )


if __name__ == "__main__":
    unittest.main()
