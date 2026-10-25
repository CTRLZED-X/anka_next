from __future__ import annotations

import unittest
from types import SimpleNamespace

from anka_contracts.decision import DecisionFrame
from anka_contracts.mechanics import MechanicsResult
from anka_decision.planner import DeterministicPlanner
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.targeting.model import TargetCellContext, TargetCellSpec
from anka_game_kernel.mechanics.targeting.service import TargetingService


class LegalKernel:
    def __init__(self):
        self.calls = []

    def validate_plan(self, frame, plan):
        self.calls.append((frame, plan))
        return MechanicsResult("LEGAL")


def combat_frame(*, target_proof: str = "KNOWN") -> DecisionFrame:
    return DecisionFrame(
        frame_id="frame-agent05",
        run_id="run-agent05",
        account_id="acct-cra",
        fight_epoch=1,
        turn_epoch=1,
        snapshot_id="snap-agent05",
        canonical_cursor=10,
        workflow_goal="FIGHT_TURN",
        actor_id=41,
        turn_owner_id=41,
        actor_cell=200,
        map_id=190580738,
        ap=11,
        mp=6,
        proof_statuses=(
            ("fight_phase", "KNOWN"),
            ("turn_owner", "KNOWN"),
            ("actor_cell", "KNOWN"),
            ("ap", "KNOWN"),
            ("mp", "KNOWN"),
            ("loadout", "KNOWN"),
            ("targets", target_proof),
        ),
        available_spells=((32435, 3),),
        target_cells=(229,),
        budget_steps=16,
    )


class TestAgent05DecisionSafety(unittest.TestCase):
    def test_unproven_target_truth_waits_before_kernel_validation(self):
        for proof in ("UNKNOWN", "STALE", "CONFLICTING", "NOT_OBSERVED"):
            with self.subTest(proof=proof):
                kernel = LegalKernel()
                result = DeterministicPlanner(kernel).plan(combat_frame(target_proof=proof))
                self.assertEqual(result.disposition, "WAIT")
                self.assertEqual(result.reason, "DECISION_REQUIRED_FIGHT_EVIDENCE_MISSING")
                self.assertIn("targets", result.required_evidence)
                self.assertEqual(kernel.calls, [])


class TestAgent05KernelTargetCellSafety(unittest.TestCase):
    def test_missing_map_cell_never_becomes_legal_without_occupancy_constraint(self):
        map_definition = SimpleNamespace(cells=())
        result = TargetingService().evaluate_cell(
            map_definition,
            CellId(229),
            TargetCellSpec(),
            TargetCellContext(caster_cell=CellId(200), occupied_cells=frozenset()),
        )
        self.assertIsNone(result.legal)
        self.assertIn("map_cell:229", result.missing_inputs)

    def test_occupied_taken_target_still_requires_static_map_membership(self):
        map_definition = SimpleNamespace(cells=())
        target = CellId(229)
        result = TargetingService().evaluate_cell(
            map_definition,
            target,
            TargetCellSpec(need_taken_cell=True),
            TargetCellContext(caster_cell=CellId(200), occupied_cells=frozenset({target})),
        )
        self.assertIsNone(result.legal)
        self.assertIn("map_cell:229", result.missing_inputs)


if __name__ == "__main__":
    unittest.main()
