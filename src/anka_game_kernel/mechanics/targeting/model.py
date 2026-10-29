from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from anka_game_kernel.domain.ids import CellId, ClassId
from anka_game_kernel.domain.actor_taxonomy import ActorKind, SummonKind


class EffectTargetClass(StrEnum):
    SELF = "self"
    ALLY_NON_SUMMON = "ally_non_summon"
    ALLY_SUMMON = "ally_summon"
    ENEMY_NON_SUMMON = "enemy_non_summon"
    ENEMY_SUMMON = "enemy_summon"


@dataclass(frozen=True, slots=True)
class EffectTargetSpec:
    allowed_classes: frozenset[EffectTargetClass] = field(
        default_factory=lambda: frozenset(EffectTargetClass)
    )
    allowed_actor_kinds: frozenset[ActorKind] | None = None
    allowed_summon_kinds: frozenset[SummonKind] | None = None
    excluded_class_ids: frozenset[ClassId] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if any(not isinstance(value, EffectTargetClass) for value in self.allowed_classes):
            raise TypeError(
                "EffectTargetSpec.allowed_classes accepts EffectTargetClass values only; "
                "raw target-mask bits must be decoded by a version-aware normalizer first."
            )
        if self.allowed_actor_kinds is not None:
            if not isinstance(self.allowed_actor_kinds, frozenset):
                raise TypeError("allowed_actor_kinds must be a frozenset of ActorKind values or None")
            if not self.allowed_actor_kinds:
                raise ValueError("allowed_actor_kinds cannot be empty when supplied")
            if any(not isinstance(value, ActorKind) for value in self.allowed_actor_kinds):
                raise TypeError("allowed_actor_kinds must contain ActorKind values")
            if ActorKind.UNKNOWN in self.allowed_actor_kinds:
                raise ValueError("ActorKind.UNKNOWN cannot be an allowed concrete target kind")
        if self.allowed_summon_kinds is not None:
            if not isinstance(self.allowed_summon_kinds, frozenset):
                raise TypeError("allowed_summon_kinds must be a frozenset of SummonKind values or None")
            if not self.allowed_summon_kinds:
                raise ValueError("allowed_summon_kinds cannot be empty when supplied")
            if any(not isinstance(value, SummonKind) for value in self.allowed_summon_kinds):
                raise TypeError("allowed_summon_kinds must contain SummonKind values")
            if SummonKind.UNKNOWN in self.allowed_summon_kinds:
                raise ValueError("SummonKind.UNKNOWN cannot be an allowed concrete summon kind")
        if not isinstance(self.excluded_class_ids, frozenset):
            raise TypeError("excluded_class_ids must be a frozenset of ClassId values")
        if any(not isinstance(value, ClassId) for value in self.excluded_class_ids):
            raise TypeError("excluded_class_ids must contain ClassId values")


@dataclass(frozen=True, slots=True)
class EffectTargetContext:
    is_self: bool
    same_team: bool | None
    is_summoned: bool | None
    actor_kind: ActorKind = ActorKind.UNKNOWN
    summon_kind: SummonKind | None = None
    class_id: ClassId | None = None


@dataclass(frozen=True, slots=True)
class TargetCellSpec:
    need_free_cell: bool = False
    need_taken_cell: bool = False


@dataclass(frozen=True, slots=True)
class TargetCellContext:
    caster_cell: CellId
    # Conservative blocker occupancy. Unknown-life actors may be present here.
    occupied_cells: frozenset[CellId] | None
    # Positive occupancy authority. Only explicitly alive actors belong here.
    proven_occupied_cells: frozenset[CellId] | None = None
