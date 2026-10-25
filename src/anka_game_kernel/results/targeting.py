from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.mechanics.targeting.model import EffectTargetClass
from anka_game_kernel.results.base import MechanicResult


class EffectTargetFailureReason(StrEnum):
    TARGET_CLASS_NOT_ALLOWED = "target_class_not_allowed"
    NO_TARGET_CLASSES_ALLOWED = "no_target_classes_allowed"
    ACTOR_KIND_NOT_ALLOWED = "actor_kind_not_allowed"
    SUMMON_KIND_NOT_ALLOWED = "summon_kind_not_allowed"
    CLASS_ID_EXCLUDED = "class_id_excluded"


@dataclass(frozen=True, slots=True)
class EffectTargetResult(MechanicResult):
    affects: bool | None = None
    target_class: EffectTargetClass | None = None
    failure: EffectTargetFailureReason | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        affects: bool,
        target_class: EffectTargetClass | None = None,
        failure: EffectTargetFailureReason | None = None,
        explanation: str | None = None,
    ) -> "EffectTargetResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            affects=affects,
            target_class=target_class,
            failure=failure,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_inputs: tuple[str, ...],
        explanation: str,
    ) -> "EffectTargetResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=missing_inputs,
            affects=None,
            explanation=explanation,
        )


class TargetCellFailureReason(StrEnum):
    CONFLICTING_CELL_REQUIREMENTS = "conflicting_cell_requirements"
    CELL_NOT_WALKABLE = "cell_not_walkable"
    CELL_NON_WALKABLE_DURING_FIGHT = "cell_non_walkable_during_fight"
    CASTER_CELL_NOT_FREE = "caster_cell_not_free"
    CELL_OCCUPIED = "cell_occupied"
    CELL_NOT_TAKEN = "cell_not_taken"


@dataclass(frozen=True, slots=True)
class TargetCellResult(MechanicResult):
    legal: bool | None = None
    failure: TargetCellFailureReason | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        legal: bool,
        failure: TargetCellFailureReason | None = None,
        explanation: str | None = None,
    ) -> "TargetCellResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=legal,
            failure=failure,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        explanation: str,
    ) -> "TargetCellResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            legal=None,
            failure=None,
            explanation=explanation,
        )
