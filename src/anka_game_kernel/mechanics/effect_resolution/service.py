from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.contexts.spell_sequences import SpellTargetSequenceState
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.contexts.projection import FightProjection
from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId
from anka_game_kernel.domain.live_requirements import LiveObservationRequirement, LiveRequirementKind
from anka_game_kernel.domain.effect_conditions import EffectTriggerKind
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.domain.spell_modifiers import ProjectedSpellRangeModifier
from anka_game_kernel.domain.spell_effects import (
    APChangeEffectSpec,
    ApplyStateEffectSpec,
    CharacteristicChangeEffectSpec,
    CharacteristicGainPerAffectedActorEffectSpec,
    CombatStatChangeEffectSpec,
    DamageEffectSpec,
    DamageSourceHealEffectSpec,
    DamageInterceptEffectSpec,
    EffectDurationChangeEffectSpec,
    DisplacementOrigin,
    EffectTargetScope,
    LifeStealEffectSpec,
    HealEffectSpec,
    MPChangeEffectSpec,
    MPStealEffectSpec,
    PerMPUsedModifierEffectSpec,
    EffectAreaAnchor,
    PullEffectSpec,
    PushEffectSpec,
    RecoilEffectSpec,
    RemoveStateEffectSpec,
    RangeChangeEffectSpec,
    RevealInvisibleEffectSpec,
    SpellRangeChangeEffectSpec,
    ShieldEffectSpec,
    SpellBaseDamageChangeEffectSpec,
    TeleportEffectSpec,
    SummonEffectSpec,
    TargetSequenceChargeEffectSpec,
    SpellEffectOccurrence,
)
from anka_game_kernel.mechanics.aoe.model import AreaShape
from anka_game_kernel.mechanics.aoe.service import AoEService
from anka_game_kernel.mechanics.displacement.service import DisplacementService
from anka_game_kernel.mechanics.geometry.grid import direction8_between, transition_side_cells
from anka_game_kernel.mechanics.effect_conditions.service import EffectConditionService
from anka_game_kernel.mechanics.projection.service import FightProjectionService
from anka_game_kernel.mechanics.relocation.model import TeleportSpec
from anka_game_kernel.mechanics.relocation.service import TeleportService
from anka_game_kernel.mechanics.registry import MechanicRegistry
from anka_game_kernel.mechanics.states.model import StateTransitionSpec
from anka_game_kernel.mechanics.states.service import StateService
from anka_game_kernel.mechanics.targeting.service import TargetingService
from anka_game_kernel.results.base import MechanicResult
from anka_game_kernel.results.effect_resolution import EffectResolutionResult, EffectStepResult


_CERTAINTY_PRIORITY = {
    Certainty.DETERMINISTIC: 0,
    Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE: 1,
    Certainty.LIVE_REQUIRED: 2,
    Certainty.UNKNOWN: 3,
    Certainty.UNSUPPORTED: 4,
}


def _combine_certainty(results: tuple[MechanicResult, ...]) -> Certainty:
    if not results:
        return Certainty.DETERMINISTIC
    return max((item.certainty for item in results), key=_CERTAINTY_PRIORITY.__getitem__)


def _merge_missing(results: tuple[MechanicResult, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for result in results:
        for item in result.missing_inputs:
            if item not in seen:
                seen.add(item)
                merged.append(item)
    return tuple(merged)


def _merge_live_requirements(
    *groups: tuple[LiveObservationRequirement, ...],
) -> tuple[LiveObservationRequirement, ...]:
    """Stable semantic union of typed live-observation requirements."""
    seen: set[tuple[LiveRequirementKind, ActorId | None, SpellId | None, int | None]] = set()
    merged: list[LiveObservationRequirement] = []
    for group in groups:
        for requirement in group:
            identity = (
                requirement.kind,
                requirement.actor_id,
                requirement.source_spell_id,
                requirement.effect_order,
            )
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(requirement)
    return tuple(merged)


@dataclass(frozen=True, slots=True)
class EffectResolutionService:
    aoe: AoEService
    targeting: TargetingService
    projection_service: FightProjectionService
    mechanics: MechanicRegistry
    conditions: EffectConditionService

    @property
    def supported_mechanic_keys(self) -> frozenset[MechanicKey]:
        return frozenset(
            {
                MechanicKey.PUSH,
                MechanicKey.PULL,
                MechanicKey.RECOIL,
                MechanicKey.TELEPORT,
                MechanicKey.APPLY_STATE,
                MechanicKey.REMOVE_STATE,
                MechanicKey.AP_CHANGE,
                MechanicKey.MP_CHANGE,
                MechanicKey.RANGE_CHANGE,
                MechanicKey.SPELL_RANGE_CHANGE,
                MechanicKey.COMBAT_STAT_CHANGE,
                MechanicKey.CHARACTERISTIC_CHANGE,
                MechanicKey.CHARACTERISTIC_GAIN_PER_AFFECTED_ACTOR,
                MechanicKey.TARGET_SEQUENCE_CHARGE,
                MechanicKey.PER_MP_USED_MODIFIER,
                MechanicKey.SUMMON,
            }
        )

    @property
    def live_authoritative_mechanic_keys(self) -> frozenset[MechanicKey]:
        return frozenset(
            {
                MechanicKey.DAMAGE,
                MechanicKey.LIFESTEAL,
                MechanicKey.HEAL,
                MechanicKey.DAMAGE_SOURCE_HEAL,
                MechanicKey.DAMAGE_INTERCEPT,
                MechanicKey.SHIELD,
                MechanicKey.AP_CHANGE,
                MechanicKey.MP_CHANGE,
                MechanicKey.REVEAL_INVISIBLE,
                MechanicKey.EFFECT_DURATION_CHANGE,
            }
        )

    def resolve(
        self,
        *,
        effects: tuple[SpellEffectOccurrence, ...],
        caster_id: ActorId,
        target_cell: CellId,
        map_definition: MapDefinition,
        context: FightContext,
    ) -> EffectResolutionResult:
        self._validate_effect_sequence(effects)
        projection = FightProjection.from_context(context)
        steps: list[EffectStepResult] = []
        for occurrence in effects:
            step, projection = self._resolve_step(
                occurrence=occurrence,
                caster_id=caster_id,
                target_cell=target_cell,
                map_definition=map_definition,
                projection=projection,
            )
            steps.append(step)
        step_tuple = tuple(steps)
        certainty = _combine_certainty(step_tuple)
        live_requirements = _merge_live_requirements(
            *(step.live_requirements for step in step_tuple)
        )
        return EffectResolutionResult(
            certainty=certainty,
            missing_inputs=_merge_missing(step_tuple),
            explanation=(
                "Ordered canonical spell effects were evaluated as a pure hypothetical projection; "
                "live-authoritative outcomes are declared without mutating caller-owned numeric truth."
            ),
            steps=step_tuple,
            projection=projection,
            live_requirements=live_requirements,
        )

    @staticmethod
    def _validate_effect_sequence(effects: tuple[SpellEffectOccurrence, ...]) -> None:
        if any(not isinstance(item, SpellEffectOccurrence) for item in effects):
            raise TypeError("effects must contain SpellEffectOccurrence values")
        orders = tuple(item.order for item in effects)
        if orders != tuple(range(len(effects))):
            raise ValueError("effect resolution requires contiguous effect order from zero")
        if effects:
            identity = (effects[0].spell_id, effects[0].grade, effects[0].branch)
            if any((item.spell_id, item.grade, item.branch) != identity for item in effects):
                raise ValueError("all resolved effects must belong to one spell/grade/branch")

    def _resolve_step(
        self,
        *,
        occurrence: SpellEffectOccurrence,
        caster_id: ActorId,
        target_cell: CellId,
        map_definition: MapDefinition,
        projection: FightProjection,
    ) -> tuple[EffectStepResult, FightProjection]:
        probability_requirements: tuple[LiveObservationRequirement, ...] = ()
        probability_result: MechanicResult | None = None
        if occurrence.probability is not None:
            basis_points = occurrence.probability.basis_points
            if basis_points == 0:
                return (
                    EffectStepResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation="A zero-probability effect is deterministically skipped.",
                        occurrence=occurrence,
                    ),
                    projection,
                )
            if basis_points < 10000:
                probability_requirements = (
                    LiveObservationRequirement(
                        kind=LiveRequirementKind.RANDOM_OUTCOME,
                        source_spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        reason="Effect activation depends on a server-side random outcome.",
                    ),
                )
                probability_result = MechanicResult(
                    certainty=Certainty.LIVE_REQUIRED,
                    explanation=(
                        "The effect has a non-deterministic activation probability; "
                        "the Kernel does not invent the server-side roll or apply the wrapped "
                        "mechanic deterministically."
                    ),
                )

        def early_step(
            base: MechanicResult,
            *,
            affected_cells: tuple[CellId, ...] = (),
            effective_area=None,
        ) -> tuple[EffectStepResult, FightProjection]:
            diagnostic_results = (base,) if probability_result is None else (base, probability_result)
            return (
                EffectStepResult(
                    certainty=_combine_certainty(diagnostic_results),
                    missing_inputs=_merge_missing(diagnostic_results),
                    explanation=base.explanation,
                    occurrence=occurrence,
                    effective_area=effective_area,
                    affected_cells=affected_cells,
                    mechanic_results=() if probability_result is None else (probability_result,),
                    live_requirements=probability_requirements,
                ),
                projection,
            )

        lifecycle_is_live = (
            LiveRequirementKind.STATUS_LIFECYCLE
            in self.live_requirement_kinds_for_occurrence(occurrence)
        )
        if occurrence.trigger is not EffectTriggerKind.IMMEDIATE and not lifecycle_is_live:
            return early_step(
                MechanicResult(
                    certainty=Certainty.UNSUPPORTED,
                    explanation=(
                        f"Trigger {occurrence.trigger.value} is representable but has no verified "
                        "deterministic projection or typed live-authority contract."
                    ),
                )
            )
        if occurrence.delay_turns not in (None, 0) and not lifecycle_is_live:
            return early_step(
                MechanicResult(
                    certainty=Certainty.UNSUPPORTED,
                    explanation=(
                        "Delayed effect scheduling is represented canonically but has no verified "
                        "deterministic projection or typed live-authority contract."
                    ),
                )
            )
        if occurrence.area is None:
            return early_step(
                MechanicResult(
                    certainty=Certainty.UNKNOWN,
                    missing_inputs=("effect_area",),
                    explanation="Effect area is unresolved; the Kernel does not assume POINT.",
                )
            )
        effective_area = occurrence.area
        if occurrence.area_progression is not None:
            current_turn = projection.context.current_turn
            if current_turn is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("current_turn",),
                        explanation=(
                            "Per-turn effect-area progression requires the active turn history."
                        ),
                    ),
                    effective_area=effective_area,
                )
            if current_turn.actor_id != caster_id:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("current_turn.actor_id",),
                        explanation=(
                            "Per-turn effect-area progression requires the caster to own the active turn history."
                        ),
                    ),
                    effective_area=effective_area,
                )
            cast_count = current_turn.cast_count(occurrence.spell_id)
            if cast_count < 1:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("current_turn.cast_history",),
                        explanation=(
                            "Per-turn effect-area progression requires the current hypothetical cast "
                            "to be present in turn history."
                        ),
                    ),
                    effective_area=effective_area,
                )
            stage_index = min(cast_count - 1, len(occurrence.area_progression.stages) - 1)
            effective_area = occurrence.area_progression.stages[stage_index]
        geometry_missing: list[str] = []
        area_center = target_cell
        if occurrence.area_anchor is EffectAreaAnchor.CASTER_CELL:
            caster_for_area = projection.context.actor(caster_id)
            if caster_for_area is None or caster_for_area.cell_id is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}:cell",),
                        explanation="Caster-anchored effect geometry requires the caster cell.",
                    )
                )
            area_center = caster_for_area.cell_id
        elif occurrence.area_anchor is EffectAreaAnchor.PRIOR_SEQUENCE_TARGET_CELL:
            if projection.context.spell_target_sequences is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("spell_target_sequences",),
                        explanation=(
                            "Prior-sequence-target effect geometry requires caller-owned spell target-sequence state."
                        ),
                    ),
                    effective_area=effective_area,
                )
            sequence = projection.context.spell_target_sequence(caster_id, occurrence.spell_id)
            if sequence is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation="No prior spell target sequence exists, so this anchored effect is skipped.",
                    ),
                    effective_area=effective_area,
                )
            sequence_target = projection.context.actor(sequence.target_actor_id)
            if sequence_target is None or sequence_target.cell_id is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(sequence.target_actor_id)}:cell",),
                        explanation="Prior spell target sequence references a target whose current cell is unknown.",
                    ),
                    effective_area=effective_area,
                )
            area_center = sequence_target.cell_id
        area_origin = None
        if effective_area.shape in {AreaShape.FORK, AreaShape.CONE, AreaShape.LINE}:
            caster_for_direction = projection.context.actor(caster_id)
            if caster_for_direction is None or caster_for_direction.cell_id is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}:cell",),
                        explanation="Directional effect geometry requires the caster cell.",
                    )
                )
            area_origin = caster_for_direction.cell_id
        area_result = self.aoe.cells(area_center, effective_area, origin=area_origin)
        affected_cell_set = set(area_result.cells)
        if occurrence.additional_area_origins is not None:
            for actor in projection.context.actors:
                if actor.summoner_id != caster_id:
                    continue
                if actor.creature_id is None:
                    geometry_missing.append(f"actor:{int(actor.actor_id)}:creature_id")
                    continue
                if actor.creature_id not in occurrence.additional_area_origins.owned_creature_ids:
                    continue
                if actor.cell_id is None:
                    geometry_missing.append(f"actor:{int(actor.actor_id)}:cell")
                    continue
                extra = self.aoe.cells(actor.cell_id, effective_area, origin=area_origin)
                affected_cell_set.update(extra.cells)
        affected_cells = tuple(sorted(affected_cell_set, key=int))
        if occurrence.mechanic_key is MechanicKey.SUMMON:
            parameters = occurrence.parameters
            assert isinstance(parameters, SummonEffectSpec)
            caster = projection.context.actor(caster_id)
            if caster is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}",),
                        explanation="Summon creation requires the summoner snapshot.",
                    ),
                    affected_cells=affected_cells,
                    effective_area=effective_area,
                )
            if caster.team_id is None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}:team_id",),
                        explanation="Summon creation requires the summoner team.",
                    ),
                    affected_cells=affected_cells,
                    effective_area=effective_area,
                )
            if projection.context.actor_at(target_cell) is not None:
                return early_step(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation="Summon creation is skipped because the selected cell is occupied.",
                    ),
                    affected_cells=affected_cells,
                    effective_area=effective_area,
                )
            initial_change_count = len(projection.changes)
            projection = self.projection_service.create_summon(
                projection,
                summoner_id=caster_id,
                cell_id=target_cell,
                creature_id=parameters.creature_id,
                summon_kind=parameters.summon_kind,
            )
            live_requirements = (
                LiveObservationRequirement(
                    kind=LiveRequirementKind.SUMMON_ACTOR_IDENTITY,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="Server assigns the authoritative runtime actor identity after summon creation.",
                ),
                LiveObservationRequirement(
                    kind=LiveRequirementKind.SUMMON_RUNTIME_STATS,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="Summon runtime HP/AP/MP and derived stats remain live-authoritative.",
                ),
                *(
                    (LiveObservationRequirement(
                        kind=LiveRequirementKind.STATUS_LIFECYCLE,
                        source_spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        reason="Fixed summon lifetime is known; authoritative summon death/expiry remains live-observed.",
                    ),)
                    if occurrence.duration_turns not in (None, 0) else ()
                ),
            )
            mechanic_result = MechanicResult(
                certainty=Certainty.LIVE_REQUIRED,
                explanation=(
                    "Summon placement, ownership and creature template were projected; "
                    "runtime actor identity and numeric stats remain live-authoritative."
                ),
            )
            return (
                EffectStepResult(
                    certainty=Certainty.LIVE_REQUIRED,
                    explanation="A generic summon actor was projected on the selected free CellId.",
                    occurrence=occurrence,
                    effective_area=effective_area,
                    affected_cells=affected_cells,
                    eligible_actor_ids=(),
                    mechanic_results=(mechanic_result,),
                    projection_changes=projection.changes[initial_change_count:],
                    live_requirements=live_requirements,
                ),
                projection,
            )

        if occurrence.target is None:
            return early_step(
                MechanicResult(
                    certainty=Certainty.UNKNOWN,
                    missing_inputs=("effect_target",),
                    explanation=(
                        "Effect target semantics are unresolved; the Kernel does not assume all actors."
                    ),
                ),
                affected_cells=affected_cells,
                effective_area=effective_area,
            )

        caster = projection.context.actor(caster_id)
        if caster is None:
            return early_step(
                MechanicResult(
                    certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                    missing_inputs=(f"actor:{int(caster_id)}",),
                    explanation="The caster is missing from the caller-owned fight snapshot.",
                ),
                affected_cells=affected_cells,
                effective_area=effective_area,
            )

        eligible: list[ActorId] = []
        missing: list[str] = list(geometry_missing)
        scope_results: list[MechanicResult] = []
        for actor in sorted(projection.context.actors, key=lambda item: int(item.actor_id)):
            if actor.alive is False:
                continue
            if actor.alive is None:
                missing.append(f"actor:{int(actor.actor_id)}:alive")
                continue
            if actor.cell_id is None:
                missing.append(f"actor:{int(actor.actor_id)}:cell")
                continue

            target_result = self.targeting.evaluate_effect_actors(
                occurrence.target,
                caster,
                actor,
            )
            if target_result.affects is None:
                missing.extend(
                    f"actor:{int(actor.actor_id)}:{name}"
                    for name in target_result.missing_inputs
                )
                continue
            if target_result.affects is not True:
                continue

            if occurrence.target_scope is EffectTargetScope.AREA:
                if actor.cell_id not in affected_cells:
                    continue
            elif occurrence.target_scope is EffectTargetScope.CASTER_LINE_OF_SIGHT:
                if caster.cell_id is None:
                    missing.append(f"actor:{int(caster_id)}:cell")
                    continue
                los_service = self.mechanics.require(MechanicKey.LINE_OF_SIGHT)
                los_result = los_service.evaluate(
                    map_definition,
                    caster.cell_id,
                    actor.cell_id,
                    occupied_cells=projection.context.occupied_cells,
                )
                if los_result.visible is not True:
                    if los_result.certainty is Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE:
                        missing.extend(los_result.missing_inputs)
                    elif los_result.certainty is Certainty.UNSUPPORTED:
                        scope_results.append(los_result)
                    continue
            elif occurrence.target_scope is EffectTargetScope.FIGHT:
                # Fight-wide effects select from the caller-owned live actor roster rather
                # than from a synthetic oversized map geometry. Target rules still decide
                # which living actors are eligible.
                pass
            else:
                scope_results.append(
                    MechanicResult(
                        certainty=Certainty.UNSUPPORTED,
                        explanation=(
                            f"Effect target scope {occurrence.target_scope.value} is not implemented."
                        ),
                    )
                )
                continue

            scheduled_lifecycle = (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            )
            if occurrence.condition is None or scheduled_lifecycle:
                # Future-trigger conditions must be evaluated against the authoritative
                # snapshot at trigger time, never against the cast-time positions.
                eligible.append(actor.actor_id)
            else:
                condition_result = self.conditions.evaluate(
                    occurrence.condition,
                    caster=caster,
                    target=actor,
                    selected_target=projection.context.actor_at(target_cell),
                    fight_context=projection.context,
                    spell_id=occurrence.spell_id,
                )
                if condition_result.matches is True:
                    eligible.append(actor.actor_id)
                elif condition_result.matches is None:
                    missing.extend(
                        f"actor:{int(actor.actor_id)}:{name}"
                        for name in condition_result.missing_inputs
                    )

        if isinstance(occurrence.parameters, DamageInterceptEffectSpec):
            interceptor = projection.context.actor_at(area_center)
            if interceptor is not None and interceptor.actor_id in eligible:
                eligible.remove(interceptor.actor_id)

        if occurrence.target_scope in {EffectTargetScope.CASTER_LINE_OF_SIGHT, EffectTargetScope.FIGHT}:
            affected_cells = tuple(
                sorted(
                    (
                        actor.cell_id
                        for actor in projection.context.actors
                        if actor.actor_id in eligible and actor.cell_id is not None
                    ),
                    key=int,
                )
            )

        initial_change_count = len(projection.changes)
        mechanic_results: list[MechanicResult] = []
        live_requirements: tuple[LiveObservationRequirement, ...] = probability_requirements
        if probability_result is not None:
            mechanic_results.append(probability_result)

        if eligible:
            eligible_actor_ids = tuple(eligible)
            if probability_result is not None:
                # Evaluate against a candidate projection to preserve wrapped mechanic diagnostics
                # and live requirements. Discard every conditional change because activation is
                # still governed by an unresolved server-side random outcome.
                conditional_results, _, conditional_live_requirements = self._dispatch(
                    occurrence=occurrence,
                    caster_id=caster_id,
                    eligible_actor_ids=eligible_actor_ids,
                    map_definition=map_definition,
                    projection=projection,
                    target_cell=target_cell,
                )
                mechanic_results.extend(conditional_results)
                live_requirements = _merge_live_requirements(
                    probability_requirements, conditional_live_requirements
                )
            else:
                dispatched, projection, live_requirements = self._dispatch(
                    occurrence=occurrence,
                    caster_id=caster_id,
                    eligible_actor_ids=eligible_actor_ids,
                    map_definition=map_definition,
                    projection=projection,
                    target_cell=target_cell,
                )
                mechanic_results.extend(dispatched)

        context_result = MechanicResult(
            certainty=(
                Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE
                if missing
                else Certainty.DETERMINISTIC
            ),
            missing_inputs=tuple(dict.fromkeys(missing)),
            explanation=(
                "Some actors cannot be classified against this effect from the current snapshot."
                if missing
                else "Affected actors were classified from the current projected snapshot."
            ),
        )
        if scope_results:
            mechanic_results = [*scope_results, *mechanic_results]
        all_results = (context_result, *mechanic_results)
        step = EffectStepResult(
            certainty=_combine_certainty(all_results),
            missing_inputs=_merge_missing(all_results),
            explanation="Effect geometry, targeting, and supported mechanic projection were evaluated in order.",
            occurrence=occurrence,
            effective_area=effective_area,
            affected_cells=affected_cells,
            eligible_actor_ids=tuple(eligible),
            mechanic_results=tuple(mechanic_results),
            projection_changes=projection.changes[initial_change_count:],
            live_requirements=live_requirements,
        )
        return step, projection

    @staticmethod
    def live_requirement_kinds_for_occurrence(
        occurrence: SpellEffectOccurrence,
    ) -> tuple[LiveRequirementKind, ...]:
        parameters = occurrence.parameters
        kinds: list[LiveRequirementKind] = []
        if isinstance(parameters, DamageEffectSpec):
            kinds.extend((LiveRequirementKind.DAMAGE_AMOUNT, LiveRequirementKind.HP_AFTER_DAMAGE))
        elif isinstance(parameters, LifeStealEffectSpec):
            kinds.extend(
                (
                    LiveRequirementKind.DAMAGE_AMOUNT,
                    LiveRequirementKind.HP_AFTER_DAMAGE,
                    LiveRequirementKind.HEAL_AMOUNT,
                    LiveRequirementKind.HP_AFTER_HEAL,
                )
            )
        elif isinstance(parameters, HealEffectSpec):
            kinds.extend((LiveRequirementKind.HEAL_AMOUNT, LiveRequirementKind.HP_AFTER_HEAL))
        elif isinstance(parameters, DamageSourceHealEffectSpec):
            kinds.extend(
                (
                    LiveRequirementKind.TRIGGER_DAMAGE_EVENT,
                    LiveRequirementKind.HEAL_AMOUNT,
                    LiveRequirementKind.HP_AFTER_HEAL,
                    LiveRequirementKind.STATUS_LIFECYCLE,
                )
            )
        elif isinstance(parameters, DamageInterceptEffectSpec):
            kinds.extend(
                (
                    LiveRequirementKind.TRIGGER_DAMAGE_EVENT,
                    LiveRequirementKind.HP_AFTER_DAMAGE,
                    LiveRequirementKind.STATUS_LIFECYCLE,
                )
            )
        elif isinstance(parameters, ShieldEffectSpec):
            kinds.extend((LiveRequirementKind.SHIELD_AMOUNT, LiveRequirementKind.SHIELD_REMAINING))
        elif isinstance(parameters, APChangeEffectSpec) and parameters.dodgeable is True:
            kinds.append(LiveRequirementKind.AP_CHANGE_RESULT)
        elif isinstance(parameters, MPChangeEffectSpec) and parameters.dodgeable is True:
            kinds.append(LiveRequirementKind.MP_CHANGE_RESULT)
        elif isinstance(parameters, RevealInvisibleEffectSpec):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)
        elif isinstance(parameters, EffectDurationChangeEffectSpec):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)
        elif isinstance(parameters, MPStealEffectSpec):
            # MP theft is a coupled target-loss/caster-gain server outcome. Even when
            # non-dodgeable, authoritative runtime MP values are preferred over a shadow
            # resource mutation because caps/state interactions may affect the gain.
            kinds.append(LiveRequirementKind.MP_CHANGE_RESULT)
        elif isinstance(parameters, PerMPUsedModifierEffectSpec):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)
        elif isinstance(parameters, SummonEffectSpec):
            kinds.extend(
                (
                    LiveRequirementKind.SUMMON_ACTOR_IDENTITY,
                    LiveRequirementKind.SUMMON_RUNTIME_STATS,
                )
            )
            if occurrence.duration_turns not in (None, 0):
                kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)

        # Temporary characteristic/base-damage modifiers affect live-authoritative runtime
        # damage outcomes. The Kernel retains their verified structural metadata but does not
        # create a shadow mutable buff store merely to reproduce those server outcomes.
        if isinstance(
            parameters,
            (CharacteristicChangeEffectSpec, CharacteristicGainPerAffectedActorEffectSpec, CombatStatChangeEffectSpec, SpellBaseDamageChangeEffectSpec),
        ):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)
        if isinstance(parameters, TargetSequenceChargeEffectSpec):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)

        # Fixed range modifiers can be projected immediately for same-plan reasoning, while
        # their temporary server-authoritative lifetime still has to be observed after execution.
        if (
            occurrence.duration_turns not in (None, 0)
            and occurrence.mechanic_key in {
                MechanicKey.MP_CHANGE,
                MechanicKey.RANGE_CHANGE,
                MechanicKey.SPELL_RANGE_CHANGE,
                MechanicKey.APPLY_STATE,
                MechanicKey.REMOVE_STATE,
            }
            and LiveRequirementKind.STATUS_LIFECYCLE not in kinds
        ):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)

        # Fixed, non-dodgeable AP changes can be projected immediately. Their temporary
        # lifetime is still live-authoritative; dodgeable AP changes already expose the
        # authoritative AP_CHANGE_RESULT contract and retain historical requirement ordering.
        if (
            occurrence.duration_turns not in (None, 0)
            and isinstance(parameters, APChangeEffectSpec)
            and parameters.dodgeable is not True
            and LiveRequirementKind.STATUS_LIFECYCLE not in kinds
        ):
            kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)

        # The immediate resolver never schedules future-turn resource/status application.
        # For non-positional lifecycle effects whose trigger/delay is fully represented, the
        # future runtime observes the resulting authoritative state instead. Delayed relocation
        # remains unsupported because STATUS_LIFECYCLE would be too weak a position contract.
        if (
            occurrence.trigger is not EffectTriggerKind.IMMEDIATE
            or occurrence.delay_turns not in (None, 0)
        ) and occurrence.mechanic_key in {
            MechanicKey.AP_CHANGE,
            MechanicKey.MP_CHANGE,
            MechanicKey.RANGE_CHANGE,
            MechanicKey.SPELL_RANGE_CHANGE,
            MechanicKey.CHARACTERISTIC_CHANGE,
            MechanicKey.CHARACTERISTIC_GAIN_PER_AFFECTED_ACTOR,
            MechanicKey.SPELL_BASE_DAMAGE_CHANGE,
            MechanicKey.HEAL,
            MechanicKey.APPLY_STATE,
            MechanicKey.REMOVE_STATE,
        }:
            if LiveRequirementKind.STATUS_LIFECYCLE not in kinds:
                kinds.append(LiveRequirementKind.STATUS_LIFECYCLE)
        return tuple(kinds)

    @classmethod
    def _live_requirements(
        cls,
        occurrence: SpellEffectOccurrence,
        caster_id: ActorId,
        eligible_actor_ids: tuple[ActorId, ...],
    ) -> tuple[LiveObservationRequirement, ...] | None:
        kinds = cls.live_requirement_kinds_for_occurrence(occurrence)
        if not kinds:
            return None
        if isinstance(occurrence.parameters, DamageSourceHealEffectSpec):
            # The effect holder is known now, but the damage source (the eventual heal
            # recipient) only exists in the authoritative trigger event. Keep that actor
            # unbound rather than attaching heal observations to the holder incorrectly.
            holder_requirements = tuple(
                LiveObservationRequirement(
                    kind=kind,
                    actor_id=actor_id,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="damage-trigger holder lifecycle/event is live-authoritative.",
                )
                for actor_id in eligible_actor_ids
                for kind in (
                    LiveRequirementKind.TRIGGER_DAMAGE_EVENT,
                    LiveRequirementKind.STATUS_LIFECYCLE,
                )
            )
            source_requirements = tuple(
                LiveObservationRequirement(
                    kind=kind,
                    actor_id=None,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="damage-source actor is resolved from the authoritative trigger event.",
                )
                for kind in (LiveRequirementKind.HEAL_AMOUNT, LiveRequirementKind.HP_AFTER_HEAL)
            )
            return (*holder_requirements, *source_requirements)
        if isinstance(occurrence.parameters, LifeStealEffectSpec):
            target_kinds = (LiveRequirementKind.DAMAGE_AMOUNT, LiveRequirementKind.HP_AFTER_DAMAGE)
            caster_kinds = (LiveRequirementKind.HEAL_AMOUNT, LiveRequirementKind.HP_AFTER_HEAL)
            target_requirements = tuple(
                LiveObservationRequirement(
                    kind=kind,
                    actor_id=actor_id,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="lifesteal target damage result is live-authoritative.",
                )
                for actor_id in eligible_actor_ids
                for kind in target_kinds
            )
            caster_requirements = tuple(
                LiveObservationRequirement(
                    kind=kind,
                    actor_id=caster_id,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="lifesteal caster healing result is live-authoritative.",
                )
                for kind in caster_kinds
            )
            return (*target_requirements, *caster_requirements)
        if isinstance(occurrence.parameters, MPStealEffectSpec):
            target_requirements = tuple(
                LiveObservationRequirement(
                    kind=LiveRequirementKind.MP_CHANGE_RESULT,
                    actor_id=actor_id,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="MP-steal target loss is live-authoritative.",
                )
                for actor_id in eligible_actor_ids
            )
            caster_requirement = (
                LiveObservationRequirement(
                    kind=LiveRequirementKind.MP_CHANGE_RESULT,
                    actor_id=caster_id,
                    source_spell_id=occurrence.spell_id,
                    effect_order=occurrence.order,
                    reason="MP-steal caster gain is live-authoritative.",
                ),
            )
            return (*target_requirements, *caster_requirement)
        return tuple(
            LiveObservationRequirement(
                kind=kind,
                actor_id=actor_id,
                source_spell_id=occurrence.spell_id,
                effect_order=occurrence.order,
                reason=(
                    f"{occurrence.mechanic_key.value} final runtime result is live-authoritative."
                ),
            )
            for actor_id in eligible_actor_ids
            for kind in kinds
        )

    def _dispatch(
        self,
        *,
        occurrence: SpellEffectOccurrence,
        caster_id: ActorId,
        eligible_actor_ids: tuple[ActorId, ...],
        map_definition: MapDefinition,
        projection: FightProjection,
        target_cell: CellId,
    ) -> tuple[list[MechanicResult], FightProjection, tuple[LiveObservationRequirement, ...]]:
        live_requirements = self._live_requirements(occurrence, caster_id, eligible_actor_ids)

        if occurrence.mechanic_key is MechanicKey.PER_MP_USED_MODIFIER:
            parameters = occurrence.parameters
            assert isinstance(parameters, PerMPUsedModifierEffectSpec)
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                projection = self.projection_service.upsert_per_mp_used_modifier(
                    projection,
                    PerMPUsedModifierState(
                        actor_id=actor_id,
                        source_spell_id=occurrence.spell_id,
                        characteristic=parameters.characteristic,
                        characteristic_delta_per_mp=parameters.characteristic_delta_per_mp,
                        range_delta_per_mp=parameters.range_delta_per_mp,
                        max_triggers=parameters.max_triggers,
                        triggers_applied=0,
                        duration_turns=occurrence.duration_turns,
                    ),
                )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=(
                            f"Registered per-MP modifier with {parameters.max_triggers} "
                            "maximum triggers for hypothetical movement planning."
                        ),
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The per-MP rule is projected for same-plan movement; its "
                            "cross-turn status lifecycle remains live-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.TARGET_SEQUENCE_CHARGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, TargetSequenceChargeEffectSpec)
            if projection.context.spell_target_sequences is None:
                return [
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("spell_target_sequences",),
                        explanation=(
                            "Target-sequence projection requires caller-owned sequence state; the Kernel will not assume an empty sequence."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            selected_target = projection.context.actor_at(target_cell)
            if selected_target is None:
                return [
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=("selected_target",),
                        explanation="Target-sequence charge requires the selected occupied target actor.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            prior = projection.context.spell_target_sequence(caster_id, occurrence.spell_id)
            stacks = (
                min(prior.stacks + 1, parameters.max_stacks)
                if prior is not None and prior.target_actor_id == selected_target.actor_id
                else 1
            )
            state = SpellTargetSequenceState(
                caster_id=caster_id,
                spell_id=occurrence.spell_id,
                target_actor_id=selected_target.actor_id,
                stacks=stacks,
                turns_remaining=parameters.timeout_turns,
            )
            projection = self.projection_service.set_spell_target_sequence(projection, state)
            results = [
                MechanicResult(
                    certainty=Certainty.DETERMINISTIC,
                    explanation=(
                        f"Projected target-sequence state now tracks actor {int(selected_target.actor_id)} at stack {stacks}/{parameters.max_stacks}."
                    ),
                )
            ]
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate target/stack sequence is useful to the planner; cross-turn expiry and timeout discharge remain live-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        # Fixed, non-dodgeable immediate AP changes are deterministic and useful to the
        # planner in the same hypothetical turn. Temporary expiry remains live-authoritative.
        if occurrence.mechanic_key is MechanicKey.AP_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, APChangeEffectSpec)
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate AP change is represented structurally and "
                            "settled by the authoritative runtime when its trigger occurs."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.dodgeable is True:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Dodgeable AP change requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable AP-change amount requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            amount = parameters.amount.minimum
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                actor = projection.context.actor(actor_id)
                assert actor is not None
                if actor.current_ap is None:
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                            missing_inputs=(f"actor:{int(actor_id)}.current_ap",),
                            explanation="Projected fixed AP change requires the actor's current canonical AP.",
                        )
                    )
                    continue
                before = actor.current_ap
                after = max(0, before + amount)
                projection = self.projection_service.adjust_ap(
                    projection, actor_id, after - before
                )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=f"Projected caller-owned current AP changed by {after - before}.",
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed AP delta was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        # Fixed, non-dodgeable immediate MP changes are deterministic and useful to the
        # planner in the same hypothetical turn. A temporary duration still carries a
        # STATUS_LIFECYCLE requirement so expiry remains server/live-authoritative.
        if occurrence.mechanic_key is MechanicKey.MP_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, MPChangeEffectSpec)
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate MP change is represented structurally and "
                            "settled by the authoritative runtime when its trigger occurs."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.dodgeable is True:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Dodgeable MP change requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable MP-change amount requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            amount = parameters.amount.minimum
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                actor = projection.context.actor(actor_id)
                assert actor is not None
                if actor.current_mp is None:
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                            missing_inputs=(f"actor:{int(actor_id)}.current_mp",),
                            explanation="Projected fixed MP change requires the actor's current canonical MP.",
                        )
                    )
                    continue
                before = actor.current_mp
                after = max(0, before + amount)
                delta = after - before
                projection = self.projection_service.adjust_mp(projection, actor_id, delta)
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=f"Projected caller-owned current MP changed by {delta} (clamped at zero).",
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed MP delta was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.DAMAGE_SOURCE_HEAL:
            parameters = occurrence.parameters
            assert isinstance(parameters, DamageSourceHealEffectSpec)
            return [
                MechanicResult(
                    certainty=Certainty.LIVE_REQUIRED,
                    explanation=(
                        "Damage-source heal trigger semantics are represented canonically; "
                        "trigger source, triggering damage and final healed HP remain authoritative runtime outcomes."
                    ),
                )
            ], projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.HEAL:
            parameters = occurrence.parameters
            assert isinstance(parameters, HealEffectSpec)
            return [
                MechanicResult(
                    certainty=Certainty.LIVE_REQUIRED,
                    explanation=(
                        "Heal amount semantics are represented canonically; final HP and any "
                        "server-side healing modifiers remain authoritative runtime outcomes."
                    ),
                )
            ], projection, (() if live_requirements is None else live_requirements)

        # Range modifiers are special: a fixed immediate amount is deterministic and useful
        # to the planner right now, but a temporary modifier's lifetime remains live-authoritative.
        # Therefore project the known immediate delta and carry STATUS_LIFECYCLE alongside it
        # instead of discarding the useful projection merely because later expiry is live.
        if occurrence.mechanic_key is MechanicKey.RANGE_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, RangeChangeEffectSpec)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable range-change amount requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            amount = parameters.amount.minimum
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                prior_stack = projection.context.effect_stack(
                    actor_id, occurrence.spell_id, occurrence.order
                )
                if (
                    occurrence.max_stacks is not None
                    and prior_stack is not None
                    and prior_stack.stacks >= occurrence.max_stacks
                ):
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC,
                            explanation=(
                                f"Fixed range modifier max_stacks={occurrence.max_stacks} is already "
                                "represented for this affected actor; the numeric PO delta is not stacked again."
                            ),
                        )
                    )
                    continue
                actor = projection.context.actor(actor_id)
                assert actor is not None
                if actor.combat_stats is None or actor.combat_stats.range_bonus is None:
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                            missing_inputs=(f"actor:{int(actor_id)}.combat_stats.range_bonus",),
                            explanation="Projected range change requires the actor's current canonical PO.",
                        )
                    )
                    continue
                projection = self.projection_service.adjust_range_bonus(projection, actor_id, amount)
                if occurrence.max_stacks is not None:
                    projection = self.projection_service.increment_effect_stack(
                        projection,
                        actor_id=actor_id,
                        spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        max_stacks=occurrence.max_stacks,
                    )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=f"Projected caller-owned range bonus changed by {amount}.",
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed range delta was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.CHARACTERISTIC_GAIN_PER_AFFECTED_ACTOR:
            parameters = occurrence.parameters
            assert isinstance(parameters, CharacteristicGainPerAffectedActorEffectSpec)
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate per-affected-actor characteristic gain is represented "
                            "structurally and settled by the authoritative runtime when triggered."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.amount_per_actor.minimum != parameters.amount_per_actor.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable per-affected-actor gain requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            caster = projection.context.actor(caster_id)
            if caster is None or caster.semantic_characteristics is None:
                return [
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}.semantic_characteristics",),
                        explanation="Caster semantic characteristics are required for deterministic aggregate gain projection.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            count = min(len(eligible_actor_ids), parameters.max_affected_actors)
            amount = parameters.amount_per_actor.minimum * count
            projection = self.projection_service.adjust_semantic_characteristic(
                projection, caster_id, parameters.characteristic, amount
            )
            results = [
                MechanicResult(
                    certainty=Certainty.DETERMINISTIC,
                    explanation=(
                        f"Projected caster {parameters.characteristic.value} gain of {amount} from "
                        f"{count} affected actor(s), capped at {parameters.max_affected_actors}."
                    ),
                )
            ]
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate aggregate characteristic gain was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.CHARACTERISTIC_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, CharacteristicChangeEffectSpec)
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate characteristic change is represented structurally "
                            "and settled by the authoritative runtime when its trigger occurs."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable characteristic-change amount requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if any(
                (projection.context.actor(actor_id) is None or projection.context.actor(actor_id).semantic_characteristics is None)
                for actor_id in eligible_actor_ids
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Characteristic-change semantics are structurally known, but immediate "
                            "projection is skipped until caller-owned semantic characteristics are available."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            amount = parameters.amount.minimum
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                prior_stack = projection.context.effect_stack(
                    actor_id, occurrence.spell_id, occurrence.order
                )
                if (
                    occurrence.max_stacks is not None
                    and prior_stack is not None
                    and prior_stack.stacks >= occurrence.max_stacks
                ):
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC,
                            explanation=(
                                f"Fixed characteristic modifier max_stacks={occurrence.max_stacks} is already "
                                "represented for this affected actor; the numeric characteristic delta is not stacked again."
                            ),
                        )
                    )
                    continue
                projection = self.projection_service.adjust_semantic_characteristic(
                    projection,
                    actor_id,
                    parameters.characteristic,
                    amount,
                )
                if occurrence.max_stacks is not None:
                    projection = self.projection_service.increment_effect_stack(
                        projection,
                        actor_id=actor_id,
                        spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        max_stacks=occurrence.max_stacks,
                    )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=(
                            f"Projected caller-owned semantic characteristic {parameters.characteristic.value} "
                            f"changed by {amount}."
                        ),
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed characteristic modifier was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.COMBAT_STAT_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, CombatStatChangeEffectSpec)
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate combat-stat change is represented structurally "
                            "and settled by the authoritative runtime when its trigger occurs."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable combat-stat change requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            if any(
                (
                    projection.context.actor(actor_id) is None
                    or projection.context.actor(actor_id).combat_stats is None
                    or getattr(projection.context.actor(actor_id).combat_stats, parameters.stat.value) is None
                )
                for actor_id in eligible_actor_ids
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Combat-stat change semantics are structurally known, but immediate "
                            "projection is skipped until caller-owned canonical combat stats are available."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            amount = parameters.amount.minimum
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                prior_stack = projection.context.effect_stack(
                    actor_id, occurrence.spell_id, occurrence.order
                )
                if (
                    occurrence.max_stacks is not None
                    and prior_stack is not None
                    and prior_stack.stacks >= occurrence.max_stacks
                ):
                    results.append(
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC,
                            explanation=(
                                f"Fixed combat-stat modifier max_stacks={occurrence.max_stacks} is already "
                                "represented for this affected actor; the numeric delta is not stacked again."
                            ),
                        )
                    )
                    continue
                projection = self.projection_service.adjust_combat_stat(
                    projection, actor_id, parameters.stat, amount
                )
                if occurrence.max_stacks is not None:
                    projection = self.projection_service.increment_effect_stack(
                        projection,
                        actor_id=actor_id,
                        spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        max_stacks=occurrence.max_stacks,
                    )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=(
                            f"Projected caller-owned combat stat {parameters.stat.value} changed by {amount}."
                        ),
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed combat-stat modifier was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key is MechanicKey.SPELL_RANGE_CHANGE:
            parameters = occurrence.parameters
            assert isinstance(parameters, SpellRangeChangeEffectSpec)
            if parameters.amount.minimum != parameters.amount.maximum:
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation="Variable spell-range modifier amount requires the authoritative server outcome.",
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            modifier = ProjectedSpellRangeModifier(
                source_spell_id=occurrence.spell_id,
                bound=parameters.bound,
                amount=parameters.amount.minimum,
                affected_class_id=parameters.affected_class_id,
                required_tags=parameters.required_tags,
                duration_turns=occurrence.duration_turns,
                max_stacks=occurrence.max_stacks,
                dispellable=occurrence.dispellable,
            )
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                projection = self.projection_service.add_spell_range_modifier(
                    projection, actor_id, modifier
                )
                results.append(
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC,
                        explanation=(
                            f"Projected {parameters.bound.value} spell-range modifier "
                            f"changed by {parameters.amount.minimum}."
                        ),
                    )
                )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate fixed spell-range modifier was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if occurrence.mechanic_key in (MechanicKey.APPLY_STATE, MechanicKey.REMOVE_STATE):
            if (
                occurrence.trigger is not EffectTriggerKind.IMMEDIATE
                or occurrence.delay_turns not in (None, 0)
            ):
                return [
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "Delayed/non-immediate state transition is represented structurally and "
                            "settled by the authoritative runtime when its trigger occurs."
                        ),
                    )
                ], projection, (() if live_requirements is None else live_requirements)
            mechanic = self.mechanics.get(occurrence.mechanic_key)
            if not isinstance(mechanic, StateService):
                raise TypeError("state mechanic registry entry must be StateService")
            results: list[MechanicResult] = []
            for actor_id in eligible_actor_ids:
                actor = projection.context.actor(actor_id)
                assert actor is not None
                if occurrence.mechanic_key is MechanicKey.APPLY_STATE:
                    parameters = occurrence.parameters
                    assert isinstance(parameters, ApplyStateEffectSpec)
                    spec = StateTransitionSpec(apply=frozenset({parameters.state_id}))
                else:
                    parameters = occurrence.parameters
                    assert isinstance(parameters, RemoveStateEffectSpec)
                    spec = StateTransitionSpec(remove=frozenset({parameters.state_id}))
                result = mechanic.evaluate(actor, spec)
                results.append(result)
                if result.certainty is Certainty.DETERMINISTIC and result.after is not None:
                    projection = self.projection_service.replace_states(
                        projection, actor_id, result.after
                    )
            if live_requirements is not None:
                results.append(
                    MechanicResult(
                        certainty=Certainty.LIVE_REQUIRED,
                        explanation=(
                            "The immediate state transition was projected deterministically; "
                            "its temporary lifecycle remains server-authoritative."
                        ),
                    )
                )
            return results, projection, (() if live_requirements is None else live_requirements)

        if live_requirements is not None:
            return [
                MechanicResult(
                    certainty=Certainty.LIVE_REQUIRED,
                    explanation=(
                        f"Mechanic {occurrence.mechanic_key.value} is structurally known; "
                        "its final numerical runtime outcome is intentionally live-authoritative."
                    ),
                )
            ], projection, live_requirements

        mechanic = self.mechanics.get(occurrence.mechanic_key)
        if mechanic is None:
            return [
                MechanicResult(
                    certainty=Certainty.UNSUPPORTED,
                    explanation=(
                        f"Semantic mechanic {occurrence.mechanic_key.value} is not registered "
                        "in this Kernel build."
                    ),
                )
            ], projection, ()

        if occurrence.mechanic_key is MechanicKey.RECOIL:
            if tuple(eligible_actor_ids) != (caster_id,):
                return [
                    MechanicResult(
                        certainty=Certainty.UNSUPPORTED,
                        explanation=(
                            "Recoil is a caster-relative displacement and requires the caster "
                            "to be the single eligible actor."
                        ),
                    )
                ], projection, ()
            if not isinstance(mechanic, DisplacementService):
                raise TypeError("RECOIL mechanic registry entry must be DisplacementService")
            caster = projection.context.actor(caster_id)
            if caster is None or caster.cell_id is None:
                return [
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}:cell",),
                        explanation="Recoil requires the caster cell.",
                    )
                ], projection, ()
            parameters = occurrence.parameters
            assert isinstance(parameters, RecoilEffectSpec)
            result = mechanic.resolve_push(
                map_definition,
                source_cell=target_cell,
                target_cell=caster.cell_id,
                distance=parameters.distance,
                occupied_cells=projection.context.occupied_cells,
            )
            if result.certainty is Certainty.DETERMINISTIC and result.traversed_cells:
                final_cell = result.traversed_cells[-1]
                if final_cell != caster.cell_id:
                    projection = self.projection_service.move_actor(
                        projection, caster.actor_id, final_cell
                    )
            collision_requirements = ()
            if result.certainty is Certainty.DETERMINISTIC and result.completed is False:
                collision_requirements = (
                    LiveObservationRequirement(
                        kind=LiveRequirementKind.COLLISION_DAMAGE,
                        actor_id=caster.actor_id,
                        source_spell_id=occurrence.spell_id,
                        effect_order=occurrence.order,
                        reason="Pushback collision damage is live-authoritative.",
                    ),
                )
            return [result], projection, collision_requirements

        if occurrence.mechanic_key is MechanicKey.TELEPORT:
            if len(eligible_actor_ids) != 1:
                return [
                    MechanicResult(
                        certainty=Certainty.UNSUPPORTED,
                        explanation=(
                            "Teleport projection requires exactly one eligible actor; "
                            "multi-target relocation sequencing is not verified."
                        ),
                    )
                ], projection, ()
            if not isinstance(mechanic, TeleportService):
                raise TypeError("TELEPORT mechanic registry entry must be TeleportService")
            parameters = occurrence.parameters
            assert isinstance(parameters, TeleportEffectSpec)
            actor_id = eligible_actor_ids[0]
            actor = projection.context.actor(actor_id)
            assert actor is not None
            result = mechanic.evaluate(
                map_definition,
                actor,
                target_cell,
                TeleportSpec(),
                fight_context=projection.context,
            )
            if result.certainty is Certainty.DETERMINISTIC and result.legal is True:
                projection = self.projection_service.move_actor(
                    projection, actor_id, target_cell
                )
            return [result], projection, ()

        if occurrence.mechanic_key in (MechanicKey.PUSH, MechanicKey.PULL):
            if not isinstance(mechanic, DisplacementService):
                raise TypeError("PUSH/PULL mechanic registry entry must be DisplacementService")
            caster = projection.context.actor(caster_id)
            if caster is None or caster.cell_id is None:
                return [
                    MechanicResult(
                        certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                        missing_inputs=(f"actor:{int(caster_id)}:cell",),
                        explanation="Displacement requires the caster cell.",
                    )
                ], projection, ()

            targets = []
            for actor_id in eligible_actor_ids:
                actor = projection.context.actor(actor_id)
                if actor is None or actor.cell_id is None:
                    return [
                        MechanicResult(
                            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
                            missing_inputs=(f"actor:{int(actor_id)}:cell",),
                            explanation="Displacement requires every affected actor cell.",
                        )
                    ], projection, ()
                targets.append(actor)

            parameters = occurrence.parameters
            distance = parameters.distance
            source_for = lambda actor: (
                target_cell
                if occurrence.displacement_origin is DisplacementOrigin.SELECTED_TARGET_CELL
                or actor.actor_id == caster_id
                else caster.cell_id
            )

            directional_line_sequence = (
                occurrence.area is not None
                and occurrence.area.shape is AreaShape.LINE
                and occurrence.displacement_origin is DisplacementOrigin.CASTER_CELL
            )
            direction_grouped_fork_sequence = (
                occurrence.mechanic_key is MechanicKey.PUSH
                and occurrence.area is not None
                and occurrence.area.shape is AreaShape.FORK
                and occurrence.displacement_origin is DisplacementOrigin.CASTER_CELL
            )

            # Dofus LINE zones enumerate cells from the selected cell outward. For a
            # caster-origin directional line this is equivalent to nearest-to-farthest
            # from the caster. Resolve in that spatial order against the incrementally
            # updated projection so collisions with not-yet-resolved targets remain
            # meaningful and later targets still receive their own displacement.
            if directional_line_sequence and len(targets) > 1:
                caster_coord = self.aoe.geometry.cell_to_coordinate(caster.cell_id)
                targets.sort(
                    key=lambda actor: (
                        abs(self.aoe.geometry.cell_to_coordinate(actor.cell_id).x - caster_coord.x)
                        + abs(self.aoe.geometry.cell_to_coordinate(actor.cell_id).y - caster_coord.y),
                        int(actor.cell_id),
                        int(actor.actor_id),
                    )
                )
            elif direction_grouped_fork_sequence and len(targets) > 1:
                # PushUtil processes one canonical Direction8 ray at a time and its
                # getEntitiesInDirection walk discovers actors nearest-to-farthest.
                # We reproduce that ordering without depending on spell id or actor
                # container order. Different rays are accepted only when their planned
                # paths and diagonal side passages are independent; otherwise the
                # Kernel fails closed because cross-ray server ordering is not verified.
                origin_coord = self.aoe.geometry.cell_to_coordinate(caster.cell_id)
                planned = []
                for actor in targets:
                    plan = mechanic.plan_push(
                        source_cell=caster.cell_id,
                        target_cell=actor.cell_id,
                        distance=distance,
                    )
                    if plan.certainty is not Certainty.DETERMINISTIC:
                        return [plan], projection, ()
                    actor_coord = self.aoe.geometry.cell_to_coordinate(actor.cell_id)
                    direction = direction8_between(origin_coord, actor_coord)
                    side_cells: set[CellId] = set()
                    previous = actor.cell_id
                    for path_cell in plan.path:
                        previous_coord = self.aoe.geometry.cell_to_coordinate(previous)
                        path_coord = self.aoe.geometry.cell_to_coordinate(path_cell)
                        for side_coord in transition_side_cells(previous_coord, path_coord):
                            side_cells.add(self.aoe.geometry.coordinate_to_cell(side_coord))
                        previous = path_cell
                    planned.append((actor, direction, plan.path, frozenset(side_cells)))

                for i, (actor, direction, path, side_cells) in enumerate(planned):
                    path_cells = set(path)
                    for other, other_direction, other_path, other_side_cells in planned[i + 1:]:
                        if direction == other_direction:
                            continue
                        other_path_cells = set(other_path)
                        if (
                            other.cell_id in path_cells
                            or actor.cell_id in other_path_cells
                            or path_cells.intersection(other_path_cells)
                            or side_cells.intersection({other.cell_id, *other_path_cells})
                            or other_side_cells.intersection({actor.cell_id, *path_cells})
                        ):
                            return [MechanicResult(
                                certainty=Certainty.UNSUPPORTED,
                                explanation=(
                                    "Affected Direction8 rays interact; cross-ray displacement "
                                    "sequencing is not verified."
                                ),
                            )], projection, ()

                targets.sort(
                    key=lambda actor: (
                        int(direction8_between(
                            origin_coord,
                            self.aoe.geometry.cell_to_coordinate(actor.cell_id),
                        )),
                        abs(self.aoe.geometry.cell_to_coordinate(actor.cell_id).x - origin_coord.x)
                        + abs(self.aoe.geometry.cell_to_coordinate(actor.cell_id).y - origin_coord.y),
                        int(actor.cell_id),
                        int(actor.actor_id),
                    )
                )
            else:
                # Outside verified ordered cases, multi-target displacement remains
                # deterministic only when affected paths are independent.
                planned_paths = []
                for actor in targets:
                    source_cell = source_for(actor)
                    plan = (
                        mechanic.plan_push(source_cell=source_cell, target_cell=actor.cell_id, distance=distance)
                        if occurrence.mechanic_key is MechanicKey.PUSH
                        else mechanic.plan_pull(source_cell=source_cell, target_cell=actor.cell_id, distance=distance)
                    )
                    if plan.certainty is not Certainty.DETERMINISTIC:
                        return [plan], projection, ()
                    planned_paths.append((actor.actor_id, actor.cell_id, plan.path))
                if len(planned_paths) > 1:
                    starts = {actor_id: start for actor_id, start, _ in planned_paths}
                    for actor_id, _start, path in planned_paths:
                        other_starts = {cell for other_id, cell in starts.items() if other_id != actor_id}
                        if any(cell in other_starts for cell in path):
                            return [MechanicResult(
                                certainty=Certainty.UNSUPPORTED,
                                explanation="Affected displacement paths interact; server target sequencing is not verified.",
                            )], projection, ()
                    for i, (_aid, _start, path) in enumerate(planned_paths):
                        cells = set(path)
                        for _bid, _bstart, other_path in planned_paths[i + 1:]:
                            if cells.intersection(other_path):
                                return [MechanicResult(
                                    certainty=Certainty.UNSUPPORTED,
                                    explanation="Affected displacement paths intersect; server target sequencing is not verified.",
                                )], projection, ()

            results = []
            collision_requirements = []
            for actor in targets:
                current = projection.context.actor(actor.actor_id)
                assert current is not None and current.cell_id is not None
                source_cell = source_for(current)
                if occurrence.mechanic_key is MechanicKey.PUSH:
                    assert isinstance(parameters, PushEffectSpec)
                    result = mechanic.resolve_push(
                        map_definition,
                        source_cell=source_cell,
                        target_cell=current.cell_id,
                        distance=parameters.distance,
                        occupied_cells=projection.context.occupied_cells,
                    )
                else:
                    assert isinstance(parameters, PullEffectSpec)
                    result = mechanic.resolve_pull(
                        map_definition,
                        source_cell=source_cell,
                        target_cell=current.cell_id,
                        distance=parameters.distance,
                        occupied_cells=projection.context.occupied_cells,
                    )
                results.append(result)
                if result.certainty is Certainty.DETERMINISTIC and result.traversed_cells:
                    final_cell = result.traversed_cells[-1]
                    if final_cell != current.cell_id:
                        projection = self.projection_service.move_actor(projection, current.actor_id, final_cell)
                if (
                    occurrence.mechanic_key is MechanicKey.PUSH
                    and result.certainty is Certainty.DETERMINISTIC
                    and result.completed is False
                ):
                    collision_requirements.append(
                        LiveObservationRequirement(
                            kind=LiveRequirementKind.COLLISION_DAMAGE,
                            actor_id=current.actor_id,
                            source_spell_id=occurrence.spell_id,
                            effect_order=occurrence.order,
                            reason="Pushback collision damage is live-authoritative.",
                        )
                    )
            return results, projection, tuple(collision_requirements)


        return [
            MechanicResult(
                certainty=Certainty.UNSUPPORTED,
                explanation=(
                    f"Mechanic {occurrence.mechanic_key.value} is registered but has no verified "
                    "R7B ordered effect-resolution adapter."
                ),
            )
        ], projection, ()
