from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.actor_taxonomy import ActorKind
from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.effect_conditions import (
    ActorKindCondition,
    AdjacentActorCondition,
    ConditionOperator,
    ConditionSubject,
    EffectConditionPredicate,
    EffectConditionSpec,
    PreviousTurnEnemyAttackCountCondition,
    SelectedTargetDistanceCondition,
    SpellTargetSequenceCondition,
    SpellTargetSequenceRelation,
    SelectedTargetTeamRelation,
    SelectedTargetTeamRelationCondition,
    ShieldPresenceCondition,
    StateCondition,
    SummonCondition,
)
from anka_game_kernel.mechanics.geometry.grid import cell_to_coordinate
from anka_game_kernel.domain.ids import SpellId
from anka_game_kernel.results.effect_conditions import EffectConditionResult


@dataclass(frozen=True, slots=True)
class _PredicateEvaluation:
    matches: bool | None
    missing_input: str | None = None


@dataclass(frozen=True, slots=True)
class EffectConditionService:
    def evaluate(
        self,
        spec: EffectConditionSpec,
        *,
        caster: ActorState,
        target: ActorState,
        selected_target: ActorState | None = None,
        fight_context: FightContext | None = None,
        spell_id: SpellId | None = None,
    ) -> EffectConditionResult:
        if not isinstance(spec, EffectConditionSpec):
            raise TypeError("spec must be an EffectConditionSpec")
        evaluations = tuple(
            self._evaluate_predicate(
                predicate,
                caster=caster,
                target=target,
                selected_target=selected_target,
                fight_context=fight_context,
                spell_id=spell_id,
            )
            for predicate in spec.predicates
        )

        known = tuple(item.matches for item in evaluations if item.matches is not None)
        if spec.operator is ConditionOperator.ALL:
            if any(value is False for value in known):
                return EffectConditionResult(
                    certainty=Certainty.DETERMINISTIC,
                    matches=False,
                    explanation="At least one required effect condition is proven false.",
                )
            if len(known) == len(evaluations):
                return EffectConditionResult(
                    certainty=Certainty.DETERMINISTIC,
                    matches=True,
                    explanation="All required effect conditions are proven true.",
                )
        else:
            if any(value is True for value in known):
                return EffectConditionResult(
                    certainty=Certainty.DETERMINISTIC,
                    matches=True,
                    explanation="At least one alternative effect condition is proven true.",
                )
            if len(known) == len(evaluations):
                return EffectConditionResult(
                    certainty=Certainty.DETERMINISTIC,
                    matches=False,
                    explanation="All alternative effect conditions are proven false.",
                )

        missing = tuple(
            dict.fromkeys(
                item.missing_input
                for item in evaluations
                if item.missing_input is not None
            )
        )
        return EffectConditionResult(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing,
            matches=None,
            explanation="Effect condition truth depends on missing caller-owned actor semantics.",
        )

    def _evaluate_predicate(
        self,
        predicate: EffectConditionPredicate,
        *,
        caster: ActorState,
        target: ActorState,
        selected_target: ActorState | None,
        fight_context: FightContext | None,
        spell_id: SpellId | None,
    ) -> _PredicateEvaluation:
        actor = caster if predicate.subject is ConditionSubject.CASTER else target
        prefix = predicate.subject.value
        if isinstance(predicate, StateCondition):
            if actor.active_state_ids is None:
                return _PredicateEvaluation(None, f"{prefix}.active_state_ids")
            contains = predicate.state_id in actor.active_state_ids
            return _PredicateEvaluation(contains if predicate.present else not contains)
        if isinstance(predicate, ActorKindCondition):
            if actor.actor_kind is ActorKind.UNKNOWN:
                return _PredicateEvaluation(None, f"{prefix}.actor_kind")
            return _PredicateEvaluation(actor.actor_kind in predicate.allowed_kinds)
        if isinstance(predicate, SummonCondition):
            if actor.summoned is None:
                return _PredicateEvaluation(None, f"{prefix}.summoned")
            return _PredicateEvaluation(actor.summoned is predicate.summoned)
        if isinstance(predicate, ShieldPresenceCondition):
            if actor.combat_stats is None or actor.combat_stats.shield_hp is None:
                return _PredicateEvaluation(None, f"{prefix}.combat_stats.shield_hp")
            has_shield = actor.combat_stats.shield_hp > 0
            return _PredicateEvaluation(has_shield if predicate.present else not has_shield)
        if isinstance(predicate, SelectedTargetDistanceCondition):
            if actor.cell_id is None:
                return _PredicateEvaluation(None, f"{prefix}.cell")
            if selected_target is None:
                return _PredicateEvaluation(None, "selected_target")
            if selected_target.cell_id is None:
                return _PredicateEvaluation(None, "selected_target.cell")
            actor_coord = cell_to_coordinate(actor.cell_id)
            target_coord = cell_to_coordinate(selected_target.cell_id)
            distance = abs(actor_coord.x - target_coord.x) + abs(actor_coord.y - target_coord.y)
            if predicate.minimum is not None and distance < predicate.minimum:
                return _PredicateEvaluation(False)
            if predicate.maximum is not None and distance > predicate.maximum:
                return _PredicateEvaluation(False)
            return _PredicateEvaluation(True)
        if isinstance(predicate, SelectedTargetTeamRelationCondition):
            if actor.team_id is None:
                return _PredicateEvaluation(None, f"{prefix}.team_id")
            if selected_target is None:
                return _PredicateEvaluation(None, "selected_target")
            if selected_target.team_id is None:
                return _PredicateEvaluation(None, "selected_target.team_id")
            same_team = actor.team_id == selected_target.team_id
            if predicate.relation is SelectedTargetTeamRelation.ALLY:
                return _PredicateEvaluation(same_team)
            return _PredicateEvaluation(not same_team)
        if isinstance(predicate, AdjacentActorCondition):
            if actor.cell_id is None:
                return _PredicateEvaluation(None, f"{prefix}.cell")
            if fight_context is None:
                return _PredicateEvaluation(None, "fight_context")
            actor_coord = cell_to_coordinate(actor.cell_id)
            unresolved = False
            for candidate in fight_context.actors:
                if candidate.actor_id == actor.actor_id or candidate.alive is False:
                    continue
                if candidate.cell_id is None:
                    unresolved = True
                    continue
                candidate_coord = cell_to_coordinate(candidate.cell_id)
                distance = abs(actor_coord.x - candidate_coord.x) + abs(actor_coord.y - candidate_coord.y)
                if distance != 1:
                    continue
                if predicate.relation is not None:
                    if actor.team_id is None or candidate.team_id is None:
                        unresolved = True
                        continue
                    same_team = actor.team_id == candidate.team_id
                    if predicate.relation is SelectedTargetTeamRelation.ALLY and not same_team:
                        continue
                    if predicate.relation is SelectedTargetTeamRelation.ENEMY and same_team:
                        continue
                if predicate.summoned is not None:
                    if candidate.summoned is None:
                        unresolved = True
                        continue
                    if candidate.summoned is not predicate.summoned:
                        continue
                if predicate.summoner_class_id is not None:
                    if candidate.summoner_id is None:
                        unresolved = True
                        continue
                    summoner = fight_context.actor(candidate.summoner_id)
                    if summoner is None or summoner.class_id is None:
                        unresolved = True
                        continue
                    if summoner.class_id != predicate.summoner_class_id:
                        continue
                return _PredicateEvaluation(True)
            if unresolved:
                return _PredicateEvaluation(None, "fight_context.adjacent_actor_semantics")
            return _PredicateEvaluation(False)
        if isinstance(predicate, PreviousTurnEnemyAttackCountCondition):
            count = actor.previous_turn_enemy_attacks_received
            if count is None:
                return _PredicateEvaluation(None, f"{prefix}.previous_turn_enemy_attacks_received")
            if predicate.minimum is not None and count < predicate.minimum:
                return _PredicateEvaluation(False)
            if predicate.maximum is not None and count > predicate.maximum:
                return _PredicateEvaluation(False)
            return _PredicateEvaluation(True)
        if isinstance(predicate, SpellTargetSequenceCondition):
            if fight_context is None or spell_id is None:
                return _PredicateEvaluation(None, "spell_target_sequences")
            if fight_context.spell_target_sequences is None:
                return _PredicateEvaluation(None, "spell_target_sequences")
            sequence = fight_context.spell_target_sequence(caster.actor_id, spell_id)
            if sequence is None:
                if predicate.relation is SpellTargetSequenceRelation.ABSENT:
                    return _PredicateEvaluation(True)
                return _PredicateEvaluation(False)
            if predicate.minimum_stacks is not None and sequence.stacks < predicate.minimum_stacks:
                return _PredicateEvaluation(False)
            if predicate.maximum_stacks is not None and sequence.stacks > predicate.maximum_stacks:
                return _PredicateEvaluation(False)
            if predicate.relation is SpellTargetSequenceRelation.ABSENT:
                return _PredicateEvaluation(False)
            if predicate.relation is SpellTargetSequenceRelation.PRESENT:
                return _PredicateEvaluation(True)
            if selected_target is None:
                return _PredicateEvaluation(None, "selected_target")
            same = sequence.target_actor_id == selected_target.actor_id
            if predicate.relation is SpellTargetSequenceRelation.SAME_SELECTED_TARGET:
                return _PredicateEvaluation(same)
            return _PredicateEvaluation(not same)
        raise TypeError(f"unsupported effect condition predicate {type(predicate).__name__}")
