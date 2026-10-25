from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from anka_game_kernel.domain.actor_taxonomy import ActorKind
from anka_game_kernel.domain.ids import ClassId, StateId


class ConditionSubject(StrEnum):
    CASTER = "caster"
    TARGET = "target"


class ConditionOperator(StrEnum):
    ALL = "all"
    ANY = "any"


class EffectTriggerKind(StrEnum):
    IMMEDIATE = "immediate"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    ON_DAMAGE = "on_damage"
    ON_MOVE = "on_move"
    ON_CAST = "on_cast"
    ON_DEATH = "on_death"


@dataclass(frozen=True, slots=True)
class StateCondition:
    subject: ConditionSubject
    state_id: StateId
    present: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if not isinstance(self.state_id, StateId):
            raise TypeError("state_id must be a StateId")
        if not isinstance(self.present, bool):
            raise TypeError("present must be a bool")


@dataclass(frozen=True, slots=True)
class ActorKindCondition:
    subject: ConditionSubject
    allowed_kinds: frozenset[ActorKind]

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if not isinstance(self.allowed_kinds, frozenset):
            raise TypeError("allowed_kinds must be a frozenset of ActorKind values")
        if not self.allowed_kinds:
            raise ValueError("allowed_kinds cannot be empty")
        if any(not isinstance(item, ActorKind) for item in self.allowed_kinds):
            raise TypeError("allowed_kinds must contain ActorKind values")
        if ActorKind.UNKNOWN in self.allowed_kinds:
            raise ValueError("ActorKind.UNKNOWN cannot be an allowed concrete actor kind")


@dataclass(frozen=True, slots=True)
class SummonCondition:
    subject: ConditionSubject
    summoned: bool

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if not isinstance(self.summoned, bool):
            raise TypeError("summoned must be a bool")


@dataclass(frozen=True, slots=True)
class ShieldPresenceCondition:
    """Match whether the selected actor currently has strictly-positive live shield HP."""

    subject: ConditionSubject
    present: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if not isinstance(self.present, bool):
            raise TypeError("present must be a bool")


@dataclass(frozen=True, slots=True)
class SelectedTargetDistanceCondition:
    """Match the Manhattan distance between a subject actor and the selected cast target actor."""

    subject: ConditionSubject
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if self.minimum is not None and (isinstance(self.minimum, bool) or not isinstance(self.minimum, int)):
            raise TypeError("minimum must be an int or None")
        if self.maximum is not None and (isinstance(self.maximum, bool) or not isinstance(self.maximum, int)):
            raise TypeError("maximum must be an int or None")
        if self.minimum is None and self.maximum is None:
            raise ValueError("selected-target distance condition requires minimum or maximum")
        if self.minimum is not None and self.minimum < 0:
            raise ValueError("minimum cannot be negative")
        if self.maximum is not None and self.maximum < 0:
            raise ValueError("maximum cannot be negative")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")




class SelectedTargetTeamRelation(StrEnum):
    ALLY = "ally"
    ENEMY = "enemy"


@dataclass(frozen=True, slots=True)
class SelectedTargetTeamRelationCondition:
    """Match whether the selected cast target is allied with or enemy to a subject actor."""

    subject: ConditionSubject
    relation: SelectedTargetTeamRelation

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if not isinstance(self.relation, SelectedTargetTeamRelation):
            raise TypeError("relation must be a SelectedTargetTeamRelation")




@dataclass(frozen=True, slots=True)
class AdjacentActorCondition:
    """Match whether a subject is in contact with an actor matching generic runtime filters."""

    subject: ConditionSubject
    relation: SelectedTargetTeamRelation | None = None
    summoned: bool | None = None
    summoner_class_id: ClassId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if self.relation is not None and not isinstance(self.relation, SelectedTargetTeamRelation):
            raise TypeError("relation must be a SelectedTargetTeamRelation or None")
        if self.summoned is not None and not isinstance(self.summoned, bool):
            raise TypeError("summoned must be a bool or None")
        if self.summoner_class_id is not None:
            if not isinstance(self.summoner_class_id, ClassId):
                raise TypeError("summoner_class_id must be a ClassId or None")
            if self.summoned is not True:
                raise ValueError("summoner_class_id requires summoned=True")


@dataclass(frozen=True, slots=True)
class PreviousTurnEnemyAttackCountCondition:
    """Match a caller-owned count of enemy attacks suffered on the prior turn."""

    subject: ConditionSubject
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ConditionSubject):
            raise TypeError("subject must be a ConditionSubject")
        if self.minimum is not None and (isinstance(self.minimum, bool) or not isinstance(self.minimum, int)):
            raise TypeError("minimum must be an int or None")
        if self.maximum is not None and (isinstance(self.maximum, bool) or not isinstance(self.maximum, int)):
            raise TypeError("maximum must be an int or None")
        if self.minimum is None and self.maximum is None:
            raise ValueError("previous-turn enemy-attack condition requires minimum or maximum")
        if self.minimum is not None and self.minimum < 0:
            raise ValueError("minimum cannot be negative")
        if self.maximum is not None and self.maximum < 0:
            raise ValueError("maximum cannot be negative")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")




class SpellTargetSequenceRelation(StrEnum):
    ABSENT = "absent"
    PRESENT = "present"
    SAME_SELECTED_TARGET = "same_selected_target"
    DIFFERENT_SELECTED_TARGET = "different_selected_target"


@dataclass(frozen=True, slots=True)
class SpellTargetSequenceCondition:
    """Match caller-owned target-sequence state for the current spell/caster."""

    subject: ConditionSubject
    relation: SpellTargetSequenceRelation
    minimum_stacks: int | None = None
    maximum_stacks: int | None = None

    def __post_init__(self) -> None:
        if self.subject is not ConditionSubject.CASTER:
            raise ValueError("spell target-sequence conditions currently require subject=caster")
        if not isinstance(self.relation, SpellTargetSequenceRelation):
            raise TypeError("relation must be a SpellTargetSequenceRelation")
        for name, value in (("minimum_stacks", self.minimum_stacks), ("maximum_stacks", self.maximum_stacks)):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{name} must be an int or None")
                if value < 1:
                    raise ValueError(f"{name} must be >= 1 when known")
        if (
            self.minimum_stacks is not None
            and self.maximum_stacks is not None
            and self.minimum_stacks > self.maximum_stacks
        ):
            raise ValueError("minimum_stacks cannot exceed maximum_stacks")


EffectConditionPredicate: TypeAlias = (
    StateCondition
    | ActorKindCondition
    | SummonCondition
    | ShieldPresenceCondition
    | SelectedTargetDistanceCondition
    | SelectedTargetTeamRelationCondition
    | AdjacentActorCondition
    | PreviousTurnEnemyAttackCountCondition
    | SpellTargetSequenceCondition
)


@dataclass(frozen=True, slots=True)
class EffectConditionSpec:
    predicates: tuple[EffectConditionPredicate, ...]
    operator: ConditionOperator = ConditionOperator.ALL

    def __post_init__(self) -> None:
        if not isinstance(self.operator, ConditionOperator):
            raise TypeError("operator must be a ConditionOperator")
        if not isinstance(self.predicates, tuple):
            raise TypeError("predicates must be a tuple")
        if not self.predicates:
            raise ValueError("predicates cannot be empty")
        if any(
            not isinstance(
                item,
                (
                    StateCondition,
                    ActorKindCondition,
                    SummonCondition,
                    ShieldPresenceCondition,
                    SelectedTargetDistanceCondition,
                    SelectedTargetTeamRelationCondition,
                    AdjacentActorCondition,
                    PreviousTurnEnemyAttackCountCondition,
                    SpellTargetSequenceCondition,
                ),
            )
            for item in self.predicates
        ):
            raise TypeError("predicates contain an unsupported condition predicate")
