from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.effect_conditions import EffectTriggerKind
from anka_game_kernel.domain.ids import SpellId
from anka_game_kernel.domain.live_requirements import LiveRequirementKind
from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.domain.spell_effects import (
    DisplacementOrigin,
    EffectTargetScope,
    SpellEffectBranch,
    SpellProjectionCapability,
)
from anka_game_kernel.mechanics.aoe.model import AreaShape
from anka_game_kernel.knowledge.spell_overlay import SpellMechanicsOverlay
from anka_game_kernel.mechanics.effect_resolution.service import EffectResolutionService
from anka_game_kernel.mechanics.registry import MechanicRegistry
from anka_game_kernel.results.spell_readiness import (
    SpellGradeReadinessReport,
    SpellReadinessBlocker,
)

__all__ = ["SpellReadinessBlocker", "SpellReadinessService"]


@dataclass(frozen=True, slots=True)
class SpellReadinessService:
    overlay: SpellMechanicsOverlay
    mechanics: MechanicRegistry
    resolver: EffectResolutionService

    def grade(
        self,
        spell_id: SpellId,
        grade: int,
        *,
        branch: SpellEffectBranch = SpellEffectBranch.NORMAL,
    ) -> SpellGradeReadinessReport:
        view = self.overlay.require_grade(spell_id, grade)
        unknown: list[SpellReadinessBlocker] = []
        unsupported: list[SpellReadinessBlocker] = []
        live: list[LiveRequirementKind] = []

        if view.mechanics is None:
            unknown.append(SpellReadinessBlocker.NO_MECHANICS)
            return self._report(spell_id, grade, branch, None, unknown, unsupported, live)

        effects = (
            view.mechanics.normal_effects
            if branch is SpellEffectBranch.NORMAL
            else view.mechanics.critical_effects
        )
        if effects is None:
            unknown.append(SpellReadinessBlocker.BRANCH_UNKNOWN)
            return self._report(spell_id, grade, branch, None, unknown, unsupported, live)

        effective_grade = view.effective_grade
        certified = view.mechanics.certified_projection_capabilities
        arbitrary_los_certified = (
            SpellProjectionCapability.ARBITRARY_ANGLE_LOS in certified
        )
        displacement8_certified = (
            SpellProjectionCapability.EIGHT_DIRECTION_DISPLACEMENT in certified
        )
        radial_cross_certified = (
            SpellProjectionCapability.RADIAL_CROSS_DISPLACEMENT in certified
        )
        directional_line_multi_target_certified = (
            SpellProjectionCapability.DIRECTIONAL_LINE_MULTI_TARGET_DISPLACEMENT in certified
        )
        direction_grouped_multi_target_certified = (
            SpellProjectionCapability.DIRECTION_GROUPED_MULTI_TARGET_DISPLACEMENT in certified
        )
        if (
            effective_grade.requires_line_of_sight
            and not effective_grade.cast_in_line
            and not effective_grade.cast_in_diagonal
            and not arbitrary_los_certified
        ):
            self._add(unsupported, SpellReadinessBlocker.LINE_OF_SIGHT_UNSUPPORTED)

        supported_adapters = self.resolver.supported_mechanic_keys
        for occurrence in effects:
            if occurrence.area is None:
                self._add(unknown, SpellReadinessBlocker.EFFECT_AREA_UNKNOWN)
            if occurrence.target is None and occurrence.mechanic_key is not MechanicKey.SUMMON:
                self._add(unknown, SpellReadinessBlocker.EFFECT_TARGET_UNKNOWN)
            if occurrence.unresolved_semantics:
                self._add(unknown, SpellReadinessBlocker.UNRESOLVED_SEMANTICS)
            if (
                occurrence.target_scope is EffectTargetScope.CASTER_LINE_OF_SIGHT
                and not arbitrary_los_certified
            ):
                self._add(unsupported, SpellReadinessBlocker.LINE_OF_SIGHT_UNSUPPORTED)
            occurrence_live = self.resolver.live_requirement_kinds_for_occurrence(occurrence)
            lifecycle_live = LiveRequirementKind.STATUS_LIFECYCLE in occurrence_live
            if occurrence.trigger is not EffectTriggerKind.IMMEDIATE and not lifecycle_live:
                self._add(unsupported, SpellReadinessBlocker.NON_IMMEDIATE_TRIGGER)
            if occurrence.delay_turns not in (None, 0) and not lifecycle_live:
                self._add(unsupported, SpellReadinessBlocker.DELAYED_EFFECT)
            if occurrence.probability is not None and occurrence.probability.basis_points < 10000:
                if occurrence.probability.basis_points > 0:
                    self._add_live(live, LiveRequirementKind.RANDOM_OUTCOME)

            if occurrence.mechanic_key in {MechanicKey.PUSH, MechanicKey.PULL, MechanicKey.RECOIL}:
                radial_cross = (
                    occurrence.mechanic_key in {MechanicKey.PUSH, MechanicKey.PULL}
                    and occurrence.displacement_origin is DisplacementOrigin.SELECTED_TARGET_CELL
                    and occurrence.area is not None
                    and occurrence.area.shape is AreaShape.CROSS
                    and occurrence.area.min_radius >= 1
                )
                certified_radial_cross = radial_cross and radial_cross_certified
                directional_line = (
                    occurrence.mechanic_key in {MechanicKey.PUSH, MechanicKey.PULL}
                    and occurrence.area is not None
                    and occurrence.area.shape is AreaShape.LINE
                    and effective_grade.cast_in_line
                    and not effective_grade.cast_in_diagonal
                )
                certified_directional_line = (
                    directional_line and directional_line_multi_target_certified
                )
                direction_grouped_fork = (
                    occurrence.mechanic_key is MechanicKey.PUSH
                    and occurrence.area is not None
                    and occurrence.area.shape is AreaShape.FORK
                    and occurrence.displacement_origin is DisplacementOrigin.CASTER_CELL
                )
                certified_direction_grouped_fork = (
                    direction_grouped_fork and direction_grouped_multi_target_certified
                )
                if (
                    not displacement8_certified
                    and not radial_cross
                    and not directional_line
                    and (
                        effective_grade.cast_in_diagonal
                        or (
                            not effective_grade.cast_in_line
                            and not effective_grade.cast_in_diagonal
                        )
                    )
                ):
                    self._add(
                        unsupported,
                        SpellReadinessBlocker.DISPLACEMENT_DIRECTION_UNSUPPORTED,
                    )
                if (
                    occurrence.mechanic_key in {MechanicKey.PUSH, MechanicKey.PULL}
                    and occurrence.area is not None
                    and occurrence.area.shape is not AreaShape.POINT
                    and not certified_radial_cross
                    and not certified_directional_line
                    and not certified_direction_grouped_fork
                ):
                    self._add(unsupported, SpellReadinessBlocker.MULTI_TARGET_DISPLACEMENT_UNSUPPORTED)
                    if (
                        not directional_line
                        and not direction_grouped_fork
                        and not displacement8_certified
                        and not radial_cross
                    ):
                        self._add(
                            unsupported,
                            SpellReadinessBlocker.DISPLACEMENT_DIRECTION_UNSUPPORTED,
                        )

            if occurrence_live:
                for kind in occurrence_live:
                    self._add_live(live, kind)
                continue

            if self.mechanics.get(occurrence.mechanic_key) is None:
                self._add(unsupported, SpellReadinessBlocker.MECHANIC_UNREGISTERED)
            elif occurrence.mechanic_key not in supported_adapters:
                self._add(unsupported, SpellReadinessBlocker.RESOLVER_ADAPTER_UNSUPPORTED)

        structurally_ready = not unknown
        projection_ready = structurally_ready and not unsupported
        blockers = tuple((*unknown, *unsupported))
        return SpellGradeReadinessReport(
            certainty=Certainty.DETERMINISTIC,
            spell_id=spell_id,
            grade=grade,
            branch=branch,
            effect_count=len(effects),
            structurally_ready=structurally_ready,
            projection_ready=projection_ready,
            live_requirements=tuple(live),
            unsupported_blockers=tuple(unsupported),
            unknown_blockers=tuple(unknown),
            prediction_ready=projection_ready,
            blockers=blockers,
            explanation=(
                "V2 readiness separates structural knowledge, Kernel-owned deterministic projection "
                "capability, and outcomes intentionally delegated to live observation."
            ),
        )

    @staticmethod
    def _add(blockers: list[SpellReadinessBlocker], item: SpellReadinessBlocker) -> None:
        if item not in blockers:
            blockers.append(item)

    @staticmethod
    def _add_live(items: list[LiveRequirementKind], item: LiveRequirementKind) -> None:
        if item not in items:
            items.append(item)

    @staticmethod
    def _report(
        spell_id: SpellId,
        grade: int,
        branch: SpellEffectBranch,
        effect_count: int | None,
        unknown: list[SpellReadinessBlocker],
        unsupported: list[SpellReadinessBlocker],
        live: list[LiveRequirementKind],
    ) -> SpellGradeReadinessReport:
        blockers = tuple((*unknown, *unsupported))
        return SpellGradeReadinessReport(
            certainty=Certainty.DETERMINISTIC,
            spell_id=spell_id,
            grade=grade,
            branch=branch,
            effect_count=effect_count,
            structurally_ready=False,
            projection_ready=False,
            live_requirements=tuple(live),
            unsupported_blockers=tuple(unsupported),
            unknown_blockers=tuple(unknown),
            prediction_ready=False,
            blockers=blockers,
            explanation="Spell-grade mechanics are not sufficiently known for this branch.",
        )
