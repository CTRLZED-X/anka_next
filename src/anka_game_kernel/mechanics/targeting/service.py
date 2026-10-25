from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.mechanics.targeting.model import (
    EffectTargetClass,
    EffectTargetContext,
    EffectTargetSpec,
    TargetCellContext,
    TargetCellSpec,
)
from anka_game_kernel.results.targeting import (
    EffectTargetFailureReason,
    EffectTargetResult,
    TargetCellFailureReason,
    TargetCellResult,
)


@dataclass(frozen=True, slots=True)
class TargetingService:
    def evaluate_effect_actors(
        self,
        spec: EffectTargetSpec,
        caster: ActorState,
        target: ActorState,
    ) -> EffectTargetResult:
        is_self = caster.actor_id == target.actor_id
        same_team = (
            caster.team_id == target.team_id
            if caster.team_id is not None and target.team_id is not None
            else None
        )
        return self.evaluate_effect(
            spec,
            EffectTargetContext(
                is_self=is_self,
                same_team=same_team,
                is_summoned=target.summoned,
                actor_kind=target.actor_kind,
                summon_kind=target.summon_kind,
                class_id=target.class_id,
            ),
        )

    def evaluate_effect(
        self,
        spec: EffectTargetSpec,
        context: EffectTargetContext,
    ) -> EffectTargetResult:
        if not spec.allowed_classes:
            return EffectTargetResult.deterministic(
                affects=False,
                failure=EffectTargetFailureReason.NO_TARGET_CLASSES_ALLOWED,
                explanation="The semantic effect target specification allows no target classes.",
            )

        if context.is_self:
            target_class = EffectTargetClass.SELF
        else:
            # Team relation is always required for a non-self actor because ally
            # and enemy semantics are distinct. Summon status, however, is only
            # required when the target specification distinguishes summons from
            # non-summons on that side. If both variants are allowed, asking for
            # is_summoned would introduce false LIVE_REQUIRED results and can make
            # otherwise deterministic damage/control casts disappear from FightAI.
            if context.same_team is None:
                return EffectTargetResult.incomplete(
                    missing_inputs=("same_team",),
                    explanation="Non-self effect applicability requires team relation.",
                )

            side_classes = (
                frozenset({EffectTargetClass.ALLY_NON_SUMMON, EffectTargetClass.ALLY_SUMMON})
                if context.same_team
                else frozenset({EffectTargetClass.ENEMY_NON_SUMMON, EffectTargetClass.ENEMY_SUMMON})
            )
            if context.is_summoned is None:
                allowed_on_side = side_classes & spec.allowed_classes
                if not allowed_on_side:
                    return EffectTargetResult.deterministic(
                        affects=False,
                        target_class=None,
                        failure=EffectTargetFailureReason.TARGET_CLASS_NOT_ALLOWED,
                        explanation="Neither summon nor non-summon target class is allowed on this team side.",
                    )
                if allowed_on_side != side_classes:
                    return EffectTargetResult.incomplete(
                        missing_inputs=("is_summoned",),
                        explanation=(
                            "Effect target semantics distinguish summon from non-summon on this team side."
                        ),
                    )
                target_class = None
            elif context.same_team:
                target_class = (
                    EffectTargetClass.ALLY_SUMMON
                    if context.is_summoned
                    else EffectTargetClass.ALLY_NON_SUMMON
                )
            else:
                target_class = (
                    EffectTargetClass.ENEMY_SUMMON
                    if context.is_summoned
                    else EffectTargetClass.ENEMY_NON_SUMMON
                )

        if target_class is not None and target_class not in spec.allowed_classes:
            return EffectTargetResult.deterministic(
                affects=False,
                target_class=target_class,
                failure=EffectTargetFailureReason.TARGET_CLASS_NOT_ALLOWED,
                explanation=f"Effect target class {target_class.value} is not allowed.",
            )

        if spec.excluded_class_ids and context.is_summoned is None and not context.is_self:
            return EffectTargetResult.incomplete(
                missing_inputs=("is_summoned",),
                explanation=(
                    "Class exclusions apply only to non-summons, so summon status is required for this effect."
                ),
            )

        if spec.excluded_class_ids and context.is_summoned is not True:
            from anka_game_kernel.domain.actor_taxonomy import ActorKind

            if context.class_id is None:
                if context.actor_kind is not ActorKind.PLAYER:
                    if context.actor_kind is ActorKind.UNKNOWN:
                        return EffectTargetResult.incomplete(
                            missing_inputs=("class_id",),
                            explanation=(
                                "Effect class exclusions require class identity when the target "
                                "could still be a player."
                            ),
                        )
                else:
                    return EffectTargetResult.incomplete(
                        missing_inputs=("class_id",),
                        explanation="Effect class exclusions require the target's canonical class identity.",
                    )
            elif context.class_id in spec.excluded_class_ids:
                return EffectTargetResult.deterministic(
                    affects=False,
                    target_class=target_class,
                    failure=EffectTargetFailureReason.CLASS_ID_EXCLUDED,
                    explanation=f"Class {int(context.class_id)} is explicitly excluded by the effect.",
                )

        if spec.allowed_actor_kinds is not None:
            from anka_game_kernel.domain.actor_taxonomy import ActorKind

            if context.actor_kind is ActorKind.UNKNOWN:
                return EffectTargetResult.incomplete(
                    missing_inputs=("actor_kind",),
                    explanation="Effect targeting requires the canonical actor kind.",
                )
            if context.actor_kind not in spec.allowed_actor_kinds:
                return EffectTargetResult.deterministic(
                    affects=False,
                    target_class=target_class,
                    failure=EffectTargetFailureReason.ACTOR_KIND_NOT_ALLOWED,
                    explanation=f"Actor kind {context.actor_kind.value} is not allowed.",
                )

        if spec.allowed_summon_kinds is not None:
            if context.is_summoned is None:
                return EffectTargetResult.incomplete(
                    missing_inputs=("is_summoned",),
                    explanation="Summon-kind targeting requires knowing whether the target is a summon.",
                )
            if context.is_summoned is not True:
                return EffectTargetResult.deterministic(
                    affects=False,
                    target_class=target_class,
                    failure=EffectTargetFailureReason.SUMMON_KIND_NOT_ALLOWED,
                    explanation="Effect requires a specific summon kind, but the target is not a summon.",
                )
            if context.summon_kind is None:
                return EffectTargetResult.incomplete(
                    missing_inputs=("summon_kind",),
                    explanation="Effect targeting requires the canonical summon kind.",
                )
            if context.summon_kind not in spec.allowed_summon_kinds:
                return EffectTargetResult.deterministic(
                    affects=False,
                    target_class=target_class,
                    failure=EffectTargetFailureReason.SUMMON_KIND_NOT_ALLOWED,
                    explanation=f"Summon kind {context.summon_kind.value} is not allowed.",
                )

        return EffectTargetResult.deterministic(
            affects=True,
            target_class=target_class,
            explanation=(
                f"Effect target class {target_class.value} and semantic filters are allowed."
                if target_class is not None
                else "Both summon and non-summon classes on the resolved team side are allowed; summon status is irrelevant."
            ),
        )

    def evaluate_cell(
        self,
        map_definition: MapDefinition,
        target_cell: CellId,
        spec: TargetCellSpec,
        context: TargetCellContext,
    ) -> TargetCellResult:
        if spec.need_free_cell and spec.need_taken_cell:
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CONFLICTING_CELL_REQUIREMENTS,
                explanation="A target cell cannot be required to be both free and taken.",
            )

        cells_by_id = {cell.cell_id: cell for cell in map_definition.cells}
        cell_definition = cells_by_id.get(target_cell)
        if cell_definition is None:
            return TargetCellResult.incomplete(
                missing_input=f"map_cell:{target_cell}",
                explanation="Target-cell evaluation requires the target cell's static map definition.",
            )

        if not spec.need_free_cell and not spec.need_taken_cell:
            return TargetCellResult.deterministic(
                legal=True,
                explanation="The target cell exists and no target-cell occupancy constraint applies.",
            )

        if spec.need_taken_cell:
            if target_cell == context.caster_cell:
                return TargetCellResult.deterministic(
                    legal=True,
                    explanation="Taken-cell requirement accepts the caster cell.",
                )
            if context.occupied_cells is None:
                return TargetCellResult.incomplete(
                    missing_input="occupied_cells",
                    explanation="Taken-cell evaluation requires the runtime occupancy snapshot.",
                )
            if target_cell in context.occupied_cells:
                return TargetCellResult.deterministic(
                    legal=True,
                    explanation="Target cell is occupied.",
                )
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CELL_NOT_TAKEN,
                explanation="Taken-cell requirement failed because the target is not the caster and is unoccupied.",
            )

        if not cell_definition.walkable:
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CELL_NOT_WALKABLE,
                explanation="Free-cell requirement failed because the target cell is not walkable.",
            )
        if cell_definition.non_walkable_during_fight:
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CELL_NON_WALKABLE_DURING_FIGHT,
                explanation="Free-cell requirement failed because the target cell is non-walkable during fights.",
            )
        if target_cell == context.caster_cell:
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CASTER_CELL_NOT_FREE,
                explanation="Free-cell requirement excludes the caster cell.",
            )
        if context.occupied_cells is None:
            return TargetCellResult.incomplete(
                missing_input="occupied_cells",
                explanation="Free-cell evaluation requires the runtime occupancy snapshot.",
            )
        if target_cell in context.occupied_cells:
            return TargetCellResult.deterministic(
                legal=False,
                failure=TargetCellFailureReason.CELL_OCCUPIED,
                explanation="Free-cell requirement failed because the target cell is occupied.",
            )
        return TargetCellResult.deterministic(
            legal=True,
            explanation="Target cell satisfies the free-cell requirement.",
        )
