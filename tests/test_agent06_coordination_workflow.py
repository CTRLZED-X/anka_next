from __future__ import annotations

import unittest
from pathlib import Path

from anka_contracts.coordination import MemberPartyObservation, PartyRosterMember
from anka_contracts.workflow import MissionConfigSpec, WorkflowSignal
from anka_coordination.coordinator import PartyCoordinatorService
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / "assets" / "workflow" / "routes.json"
ROSTER = (
    PartyRosterMember("acct-cra", "client-cra", 41, "leader"),
    PartyRosterMember("acct-enu", "client-enu", 42, "follower"),
)


def mission(*, watchdog: int = 1, recovery: int = 2):
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
    fight_result: str | None = None,
):
    return WorkflowSignal(
        f"wfsig-agent06-{number}",
        kind,
        tick,
        (f"evidence-agent06-{number}",),
        fight_epoch=fight_epoch,
        fight_result=fight_result,
    )


def observation(
    number: int,
    account_id: str,
    *,
    turn_epoch: int = 0,
    owner: int | None = None,
    joined: bool = True,
    placed: bool = True,
    ready: bool = True,
    fight_id: str = "fight-agent06",
):
    is_cra = account_id == "acct-cra"
    return MemberPartyObservation(
        f"coordobs-agent06-{number}",
        account_id,
        "client-cra" if is_cra else "client-enu",
        41 if is_cra else 42,
        number,
        number,
        1,
        turn_epoch,
        fight_id,
        190580738,
        "FIGHT_ACTIVE" if turn_epoch else "PLACEMENT",
        owner,
        joined,
        placed,
        ready,
        "HEALTHY",
        (f"evidence-agent06-coord-{number}",),
        False,
    )


class Agent06CoordinationLifecycleTests(unittest.TestCase):
    def test_follower_join_is_a_real_barrier_not_leader_inference(self):
        coordinator = PartyCoordinatorService("party-agent06", ROSTER)
        coordinator.observe(
            observation(1, "acct-cra", joined=True, placed=False, ready=False)
        )
        coordinator.observe(
            observation(2, "acct-enu", joined=False, placed=False, ready=False)
        )

        snapshot = coordinator.snapshot()
        self.assertTrue(snapshot.same_fight_proven)
        self.assertFalse(snapshot.join_barrier.satisfied)
        self.assertEqual(snapshot.join_barrier.confirmed_accounts, ("acct-cra",))
        follower_join = coordinator.action_permit(
            "party-agent06", "acct-enu", "JOIN"
        )
        self.assertTrue(follower_join.allowed)

        coordinator.observe(
            observation(3, "acct-enu", joined=True, placed=False, ready=False)
        )
        self.assertTrue(coordinator.snapshot().join_barrier.satisfied)
        already_joined = coordinator.action_permit(
            "party-agent06", "acct-enu", "JOIN"
        )
        self.assertFalse(already_joined.allowed)
        self.assertEqual(already_joined.reason, "ALREADY_JOINED")

    def test_ready_first_turn_and_next_owner_require_cross_account_convergence(self):
        coordinator = PartyCoordinatorService("party-agent06", ROSTER)
        coordinator.observe(observation(10, "acct-cra", turn_epoch=0, owner=None))
        coordinator.observe(observation(11, "acct-enu", turn_epoch=0, owner=None))

        ready = coordinator.snapshot()
        self.assertTrue(ready.ready_barrier.satisfied)
        self.assertEqual(ready.phase, "WAIT_TURN_OWNER")
        self.assertFalse(coordinator.turn_permit("party-agent06", "acct-cra").allowed)

        coordinator.observe(observation(12, "acct-cra", turn_epoch=1, owner=41))
        self.assertIsNone(coordinator.snapshot().turn_owner_account_id)
        coordinator.observe(observation(13, "acct-enu", turn_epoch=1, owner=41))
        first = coordinator.turn_permit("party-agent06", "acct-cra")
        self.assertTrue(first.allowed)

        coordinator.observe(observation(14, "acct-cra", turn_epoch=2, owner=42))
        middle = coordinator.snapshot()
        self.assertIsNone(middle.turn_owner_account_id)
        self.assertIn("TURN_OWNER_SKEW", middle.conflicting_evidence)
        self.assertFalse(coordinator.turn_permit("party-agent06", "acct-enu").allowed)

        coordinator.observe(observation(15, "acct-enu", turn_epoch=2, owner=42))
        next_owner = coordinator.turn_permit("party-agent06", "acct-enu")
        self.assertTrue(next_owner.allowed)
        self.assertGreater(next_owner.permit_generation, first.permit_generation)
        self.assertFalse(coordinator.turn_permit("party-agent06", "acct-cra").allowed)


class Agent06WorkflowRecoveryTests(unittest.TestCase):
    def _advance_to(self, workflow: MissionWorkflow, target: str) -> None:
        steps = (
            ("START", 0, None),
            ("PREFLIGHT_OK", 1, None),
            ("ENCOUNTER_SELECTED", 2, None),
            ("FIGHT_ENTRY_PROVEN", 3, 1),
            ("PARTY_JOIN_PROVEN", 4, 1),
            ("PLACEMENT_PROVEN", 5, 1),
            ("READY_PROVEN", 6, 1),
            ("FIRST_TURN_PROVEN", 7, 1),
        )
        for index, (kind, tick, fight_epoch) in enumerate(steps, 1):
            result = workflow.apply(
                signal(index, kind, tick, fight_epoch=fight_epoch)
            )
            self.assertEqual(result.status, "APPLIED", result.reason)
            if result.snapshot.phase == target:
                return
        self.fail(f"target phase was not reached: {target}")

    def test_fight_end_supersedes_recovery_from_every_legal_fight_phase(self):
        for phase in (
            "FIGHT_ENTRY",
            "PARTY_JOIN",
            "PLACEMENT",
            "READY",
            "FIGHT_ACTIVE",
        ):
            with self.subTest(phase=phase):
                workflow = MissionWorkflow(
                    f"run-agent06-{phase.lower().replace('_', '-')}",
                    mission(watchdog=1, recovery=1),
                )
                self._advance_to(workflow, phase)
                deadline = workflow.snapshot().watchdog_deadline_tick
                self.assertIsNotNone(deadline)

                recovering = workflow.apply(
                    signal(50, "WATCHDOG", deadline + 1)
                )
                self.assertEqual(recovering.snapshot.phase, "RECOVERING")
                self.assertEqual(recovering.snapshot.resume_phase, phase)

                ended = workflow.apply(
                    signal(
                        51,
                        "FIGHT_ENDED",
                        recovering.snapshot.phase_started_tick + 1,
                        fight_epoch=1,
                    )
                )
                self.assertEqual(ended.status, "APPLIED", ended.reason)
                self.assertEqual(ended.reason, "FIGHT_END_SUPERSEDES_RECOVERY")
                self.assertEqual(
                    ended.snapshot.phase, "FIGHT_END_RECONCILIATION"
                )

                outcome = workflow.apply(
                    signal(
                        52,
                        "FIGHT_OUTCOME",
                        ended.snapshot.phase_started_tick + 1,
                        fight_epoch=1,
                        fight_result="UNKNOWN",
                    )
                )
                self.assertEqual(outcome.snapshot.phase, "WORLD_REENTRY")
                reentry = workflow.apply(
                    signal(
                        53,
                        "WORLD_REENTRY_PROVEN",
                        outcome.snapshot.phase_started_tick + 1,
                        fight_epoch=1,
                    )
                )
                self.assertEqual(reentry.snapshot.phase, "WORLD")

    def test_delayed_preturn_proof_supersedes_matching_recovery(self):
        cases = (
            ("FIGHT_ENTRY", "PARTY_JOIN_PROVEN", "PARTY_JOIN"),
            ("PARTY_JOIN", "PLACEMENT_PROVEN", "PLACEMENT"),
            ("PLACEMENT", "READY_PROVEN", "READY"),
            ("READY", "FIRST_TURN_PROVEN", "FIGHT_ACTIVE"),
        )
        for resume_phase, proof_kind, expected_phase in cases:
            with self.subTest(resume_phase=resume_phase, proof=proof_kind):
                workflow = MissionWorkflow(
                    f"run-agent06-proof-{resume_phase.lower().replace('_', '-')}",
                    mission(watchdog=1, recovery=1),
                )
                self._advance_to(workflow, resume_phase)
                recovering = workflow.apply(
                    signal(
                        54,
                        "WATCHDOG",
                        workflow.snapshot().watchdog_deadline_tick + 1,
                    )
                )
                self.assertEqual(recovering.snapshot.phase, "RECOVERING")
                proof = workflow.apply(
                    signal(
                        55,
                        proof_kind,
                        recovering.snapshot.phase_started_tick + 1,
                        fight_epoch=1,
                    )
                )
                self.assertEqual(proof.status, "APPLIED", proof.reason)
                self.assertEqual(
                    proof.reason, proof_kind + "_SUPERSEDES_RECOVERY"
                )
                self.assertEqual(proof.snapshot.phase, expected_phase)
                self.assertIsNone(proof.snapshot.resume_phase)

    def test_delayed_preturn_proof_with_wrong_epoch_stays_blocked_in_recovery(self):
        workflow = MissionWorkflow(
            "run-agent06-proof-wrong-epoch",
            mission(watchdog=1, recovery=1),
        )
        self._advance_to(workflow, "READY")
        recovering = workflow.apply(
            signal(
                56,
                "WATCHDOG",
                workflow.snapshot().watchdog_deadline_tick + 1,
            )
        )
        rejected = workflow.apply(
            signal(
                57,
                "FIRST_TURN_PROVEN",
                recovering.snapshot.phase_started_tick + 1,
                fight_epoch=2,
            )
        )
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.reason, "FIGHT_EPOCH_MISMATCH")
        self.assertEqual(rejected.snapshot.phase, "RECOVERING")
        self.assertEqual(rejected.snapshot.resume_phase, "READY")

    def test_repeated_recovery_timeouts_are_bounded(self):
        workflow = MissionWorkflow(
            "run-agent06-recovery-budget",
            mission(watchdog=1, recovery=2),
        )
        self._advance_to(workflow, "READY")

        first = workflow.apply(
            signal(60, "WATCHDOG", workflow.snapshot().watchdog_deadline_tick + 1)
        )
        self.assertEqual(
            (first.snapshot.phase, first.snapshot.recovery_budget_remaining),
            ("RECOVERING", 1),
        )
        second = workflow.apply(
            signal(61, "WATCHDOG", first.snapshot.watchdog_deadline_tick + 1)
        )
        self.assertEqual(
            (second.snapshot.phase, second.snapshot.recovery_budget_remaining),
            ("RECOVERING", 0),
        )
        terminal = workflow.apply(
            signal(62, "WATCHDOG", second.snapshot.watchdog_deadline_tick + 1)
        )
        self.assertEqual(terminal.snapshot.phase, "BLOCKED")
        self.assertEqual(
            terminal.snapshot.terminal_reason, "WORKFLOW_TIMEOUT_RECOVERING"
        )

    def test_terminal_stop_requests_cannot_grow_replay_history(self):
        workflow = MissionWorkflow(
            "run-agent06-terminal-history",
            mission(watchdog=1, recovery=1),
        )
        workflow.apply(signal(70, "START", 0))
        stopped = workflow.apply(signal(71, "STOP_REQUESTED", 1))
        self.assertEqual(stopped.snapshot.phase, "STOPPED")
        history_size = len(stopped.snapshot.processed_signal_ids)
        generation = stopped.snapshot.progress_generation

        for number in range(72, 172):
            duplicate = workflow.apply(
                signal(number, "STOP_REQUESTED", number)
            )
            self.assertEqual(duplicate.status, "DUPLICATE")
            self.assertEqual(duplicate.reason, "ALREADY_TERMINAL")
            self.assertEqual(
                len(duplicate.snapshot.processed_signal_ids), history_size
            )
            self.assertEqual(
                duplicate.snapshot.progress_generation, generation
            )


if __name__ == "__main__":
    unittest.main()
