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



class TestAgent05MapResearchIdentity(unittest.TestCase):
    def test_complete_map_order_cannot_change_origin_identity(self):
        from unittest.mock import patch

        from anka_contracts.decision import CastProbe
        from anka_contracts.map_research import MapResearchRequest
        from anka_decision import map_research as module
        from anka_game_kernel.domain.ids import ActorId, CellId, MapId

        class Cell:
            def __init__(self, cell_id, *, walkable=True):
                self.cell_id = CellId(cell_id)
                self.walkable = walkable
                self.non_walkable_during_fight = False

        # Full canonical coverage, deliberately reversed.  Cell 10 is legal,
        # while tuple index 10 is cell 549 and illegal.  Index-based lookup
        # therefore reproduces the old false block.
        cells = [Cell(i) for i in reversed(range(560))]
        next(cell for cell in cells if int(cell.cell_id) == 549).walkable = False

        class FakeMap:
            map_id = MapId(190580738)
            cells = tuple(cells)

        actor = SimpleNamespace(
            actor_id=ActorId(41),
            cell_id=CellId(10),
            current_ap=11,
            current_mp=6,
            current_hp=100,
            max_hp=100,
            cooldowns_complete=True,
            cooldowns=(),
        )

        class FakeFight:
            geometry_live_walkable_cells = frozenset()
            active_actor_id = ActorId(41)
            occupied_cells = frozenset({CellId(10)})

            def require_map(self, map_id):
                return map_id == FakeMap.map_id

            def actor(self, actor_id):
                return actor if actor_id == actor.actor_id else None

        class FakeSpellDecisions:
            @staticmethod
            def evaluate_cast_cell(**kwargs):
                return SimpleNamespace(legal=True, failed_stages=(), missing_inputs=())

        class FakeFightQueries:
            @staticmethod
            def reachable_cells(*args, **kwargs):
                return SimpleNamespace(reachable=(), missing_inputs=())

        kernel = SimpleNamespace(
            spell_decisions=FakeSpellDecisions(),
            fight_queries=FakeFightQueries(),
        )
        snapshot = {
            "actors": {
                "41": {
                    "cell_id": 10,
                    "AP": 11,
                    "MP": 6,
                    "hp": 100,
                    "max_hp": 100,
                    "cooldowns": [],
                }
            }
        }
        request = MapResearchRequest(
            CastProbe("session-a", "acct-cra", 1, "fight-a", 1, 41, 32435, 3, 10),
            190580738,
            (10,),
        )
        gate = SimpleNamespace(
            status="RESEARCH_ONLY",
            reasons=(),
            missing_kernel_inputs=(),
        )

        with patch.object(module, "MapDefinition", FakeMap), \
             patch.object(module, "FightContext", FakeFight), \
             patch.object(module, "inspect_cast_probe", return_value=gate):
            result = module.inspect_map_research(
                snapshot,
                request,
                map_definition=FakeMap(),
                fight_context=FakeFight(),
                kernel=kernel,
            )

        self.assertEqual(result.status, "RESEARCH_ONLY")
        self.assertNotIn("ACTOR_ORIGIN_GEOMETRY_CONFLICT", result.reasons)



class TestAgent05EffectConditionSafety(unittest.TestCase):
    def test_unknown_alive_adjacent_actor_cannot_satisfy_condition(self):
        from anka_game_kernel.domain.effect_conditions import (
            AdjacentActorCondition,
            ConditionSubject,
            EffectConditionSpec,
        )
        from anka_game_kernel.domain.ids import ActorId
        from anka_game_kernel.mechanics.effect_conditions.service import EffectConditionService
        from anka_game_kernel.mechanics.geometry.grid import (
            adjacent_cells,
            cell_to_coordinate,
            coordinate_to_cell,
        )

        caster_cell = CellId(100)
        adjacent_cell = coordinate_to_cell(adjacent_cells(cell_to_coordinate(caster_cell))[0])
        caster = SimpleNamespace(
            actor_id=ActorId(41),
            cell_id=caster_cell,
        )
        candidate = SimpleNamespace(
            actor_id=ActorId(42),
            alive=None,
            cell_id=adjacent_cell,
            team_id=None,
            summoned=None,
            summoner_id=None,
        )
        context = SimpleNamespace(
            actors=(caster, candidate),
            actor=lambda actor_id: None,
        )
        spec = EffectConditionSpec(
            (AdjacentActorCondition(ConditionSubject.CASTER),)
        )

        result = EffectConditionService().evaluate(
            spec,
            caster=caster,
            target=caster,
            fight_context=context,
        )

        self.assertIsNone(result.matches)
        self.assertIn("fight_context.adjacent_actor_semantics", result.missing_inputs)


if __name__ == "__main__":
    unittest.main()
