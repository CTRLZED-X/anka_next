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
        client_instance_id="client-cra",
        snapshot_semantic_sha256="a" * 64,
        state_reducer_revision="m7-r1",
        kernel_ruleset_id="kernel-r5",
        game_data_revision="legacy-r5198",
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



class TestAgent05PolicySafety(unittest.TestCase):
    def test_unknown_explicit_policy_profile_faults_before_kernel(self):
        from dataclasses import replace

        kernel = LegalKernel()
        frame = replace(combat_frame(), policy_profile="missing-profile")
        result = DeterministicPlanner(
            kernel,
            policies={"cra": SimpleNamespace(class_id=9)},
        ).plan(frame)

        self.assertEqual(result.disposition, "FAULT")
        self.assertEqual(result.failure_code, "POLICY_PROFILE_UNKNOWN")
        self.assertEqual(kernel.calls, [])



class TestAgent05NearestActorSafety(unittest.TestCase):
    def test_unknown_alive_matching_actor_cannot_be_nearest_enemy(self):
        from anka_game_kernel.domain.ids import ActorId
        from anka_game_kernel.mechanics.fight_queries.service import FightQueryService

        source = SimpleNamespace(
            actor_id=ActorId(41),
            alive=True,
            team_id=1,
            cell_id=CellId(100),
        )
        candidate = SimpleNamespace(
            actor_id=ActorId(42),
            alive=None,
            team_id=2,
            cell_id=CellId(101),
        )
        context = SimpleNamespace(
            actors=(source, candidate),
            actor=lambda actor_id: source if actor_id == source.actor_id else candidate,
        )

        result = FightQueryService().nearest_enemy(context, source.actor_id)

        self.assertIsNone(result.actor_id)
        self.assertIn("actor:42.alive", result.missing_inputs)



class TestAgent05SummonCountSafety(unittest.TestCase):
    def test_unknown_alive_owned_summon_is_not_counted_as_definitely_active(self):
        from anka_game_kernel.domain.ids import ActorId
        from anka_game_kernel.mechanics.actor_queries.service import ActorQueryService

        summoner = SimpleNamespace(actor_id=ActorId(41))
        summon = SimpleNamespace(
            actor_id=ActorId(50),
            alive=None,
            summoned=True,
            summoner_id=ActorId(41),
        )
        context = SimpleNamespace(
            actors=(summoner, summon),
            actor=lambda actor_id: summoner if actor_id == summoner.actor_id else summon,
        )

        result = ActorQueryService.summon_count(context, summoner.actor_id)

        self.assertEqual(result.count, 0)
        self.assertIn("actor:50.alive", result.missing_inputs)



class TestAgent05ActionIdentitySafety(unittest.TestCase):
    def test_action_key_changes_with_kernel_or_game_data_identity(self):
        from dataclasses import replace

        from anka_decision.planner import action_key

        frame = combat_frame()
        target = (("spell_id", "32435"), ("grade", "3"), ("target_cell", "229"))
        baseline = action_key(frame, "CAST", target)

        changed_kernel = action_key(
            replace(frame, kernel_ruleset_id="kernel-ruleset-b"),
            "CAST",
            target,
        )
        changed_data = action_key(
            replace(frame, game_data_revision="game-data-b"),
            "CAST",
            target,
        )

        self.assertNotEqual(baseline, changed_kernel)
        self.assertNotEqual(baseline, changed_data)
        self.assertNotEqual(changed_kernel, changed_data)



class TestAgent05KernelPortFailureSafety(unittest.TestCase):
    def test_kernel_exception_becomes_explicit_fault_without_plan(self):
        class FailingKernel:
            def validate_plan(self, frame, plan):
                raise RuntimeError("boom")

        result = DeterministicPlanner(FailingKernel()).plan(combat_frame())

        self.assertEqual(result.disposition, "FAULT")
        self.assertEqual(result.failure_code, "KERNEL_VALIDATION_FAILED")
        self.assertIsNone(result.plan)

    def test_invalid_kernel_result_becomes_explicit_fault_without_plan(self):
        class InvalidKernel:
            def validate_plan(self, frame, plan):
                return SimpleNamespace(status="LEGAL", reason="")

        result = DeterministicPlanner(InvalidKernel()).plan(combat_frame())

        self.assertEqual(result.disposition, "FAULT")
        self.assertEqual(result.failure_code, "KERNEL_RESULT_INVALID")
        self.assertIsNone(result.plan)



class TestAgent05PolicyClassProofSafety(unittest.TestCase):
    def test_explicit_policy_requires_proven_class_identity(self):
        from dataclasses import replace

        kernel = LegalKernel()
        policy = SimpleNamespace(class_id=9)
        frame = replace(combat_frame(), policy_profile="cra", class_id=None)
        result = DeterministicPlanner(kernel, policies={"cra": policy}).plan(frame)

        self.assertEqual(result.disposition, "FAULT")
        self.assertEqual(result.failure_code, "POLICY_CLASS_UNKNOWN")
        self.assertEqual(kernel.calls, [])



class TestAgent05ReadyProofSafety(unittest.TestCase):
    def test_ready_waits_on_unknown_or_stale_phase_and_cell_truth(self):
        from dataclasses import replace

        for name, status in (
            ("fight_phase", "UNKNOWN"),
            ("fight_phase", "STALE"),
            ("actor_cell", "CONFLICTING"),
            ("actor_cell", "NOT_OBSERVED"),
        ):
            with self.subTest(name=name, status=status):
                frame = replace(combat_frame(), workflow_goal="READY")
                proofs = tuple(
                    (key, status if key == name else value)
                    for key, value in frame.proof_statuses
                )
                result = DeterministicPlanner(LegalKernel()).plan(
                    replace(frame, proof_statuses=proofs)
                )
                self.assertEqual(result.disposition, "WAIT")
                self.assertEqual(result.reason, "DECISION_READY_EVIDENCE_MISSING")
                self.assertIn(name, result.required_evidence)

    def test_ready_requires_actor_identity_even_with_known_proofs(self):
        from dataclasses import replace

        frame = replace(combat_frame(), workflow_goal="READY", actor_id=None)
        result = DeterministicPlanner(LegalKernel()).plan(frame)

        self.assertEqual(result.disposition, "WAIT")
        self.assertEqual(result.reason, "DECISION_READY_ACTOR_UNKNOWN")
        self.assertIn("actor_identity", result.required_evidence)



class TestAgent05NonCombatActorContextSafety(unittest.TestCase):
    def test_noncombat_action_paths_require_actor_identity_and_cell_values(self):
        from dataclasses import replace

        cases = (
            (
                "PLACEMENT",
                (("fight_phase", "KNOWN"), ("actor_cell", "KNOWN")),
                {"candidate_move_cells": (201,), "map_id": 190580738},
                "DECISION_PLACEMENT_ACTOR_UNKNOWN",
            ),
            (
                "WORLD_MOVE",
                (("world_map", "KNOWN"), ("actor_cell", "KNOWN")),
                {"candidate_move_cells": (201,)},
                "DECISION_WORLD_ACTOR_UNKNOWN",
            ),
            (
                "FIGHT_ENTRY",
                (("world_map", "KNOWN"), ("actor_cell", "KNOWN"), ("encounter_target", "KNOWN")),
                {"encounter_id": "encounter-a", "map_id": 190580738},
                "DECISION_FIGHT_ENTRY_ACTOR_UNKNOWN",
            ),
            (
                "JOIN_FIGHT",
                (
                    ("world_map", "KNOWN"),
                    ("actor_cell", "KNOWN"),
                    ("fight_identity", "KNOWN"),
                    ("join_target", "KNOWN"),
                ),
                {"target_fight_id": "fight-a", "target_fight_epoch": 1},
                "DECISION_JOIN_ACTOR_UNKNOWN",
            ),
        )
        for goal, proofs, extra, reason in cases:
            with self.subTest(goal=goal):
                frame = replace(
                    combat_frame(),
                    workflow_goal=goal,
                    proof_statuses=proofs,
                    actor_id=None,
                    actor_cell=None,
                    **extra,
                )
                result = DeterministicPlanner(LegalKernel()).plan(frame)
                self.assertEqual(result.disposition, "WAIT")
                self.assertEqual(result.reason, reason)
                self.assertIn("actor_identity", result.required_evidence)
                self.assertIn("actor_cell", result.required_evidence)



class TestAgent05FrameProvenanceSafety(unittest.TestCase):
    def test_actionable_planning_faults_when_identity_provenance_is_missing(self):
        from dataclasses import replace

        fields = (
            "client_instance_id",
            "snapshot_semantic_sha256",
            "state_reducer_revision",
            "kernel_ruleset_id",
            "game_data_revision",
        )
        for field in fields:
            with self.subTest(field=field):
                kernel = LegalKernel()
                result = DeterministicPlanner(kernel).plan(
                    replace(combat_frame(), **{field: ""})
                )
                self.assertEqual(result.disposition, "FAULT")
                self.assertEqual(result.failure_code, "FRAME_PROVENANCE_MISSING")
                self.assertIsNone(result.plan)
                self.assertEqual(kernel.calls, [])


if __name__ == "__main__":
    unittest.main()
