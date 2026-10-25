from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.contexts.turn_history import CastRecord, TurnActionHistory
from anka_game_kernel.contexts.spell_sequences import SpellTargetSequenceState
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.contexts.effect_stacks import EffectStackState
from anka_game_kernel.domain.characteristics import CharacteristicKey
from anka_game_kernel.domain.combat_stats import CombatStatKey
from anka_game_kernel.domain.ids import ActorId, CellId, SpellId, StateId
from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.spell_modifiers import ProjectedSpellRangeModifier


@dataclass(frozen=True, slots=True)
class SummonProjectionChange:
    created_actor: ActorState


@dataclass(frozen=True, slots=True)
class CellProjectionChange:
    actor_id: ActorId
    before: CellId
    after: CellId


@dataclass(frozen=True, slots=True)
class StateProjectionChange:
    actor_id: ActorId
    before: frozenset[StateId]
    after: frozenset[StateId]
    added: frozenset[StateId]
    removed: frozenset[StateId]


@dataclass(frozen=True, slots=True)
class APProjectionChange:
    actor_id: ActorId
    before: int
    after: int
    spent: int


@dataclass(frozen=True, slots=True)
class APAdjustmentProjectionChange:
    actor_id: ActorId
    before: int
    after: int
    delta: int


@dataclass(frozen=True, slots=True)
class MPProjectionChange:
    actor_id: ActorId
    before: int
    after: int
    spent: int


@dataclass(frozen=True, slots=True)
class MPAdjustmentProjectionChange:
    actor_id: ActorId
    before: int
    after: int
    delta: int


@dataclass(frozen=True, slots=True)
class RangeBonusProjectionChange:
    actor_id: ActorId
    before: int
    after: int
    delta: int


@dataclass(frozen=True, slots=True)
class SpellRangeModifierProjectionChange:
    actor_id: ActorId
    modifier: ProjectedSpellRangeModifier


@dataclass(frozen=True, slots=True)
class CharacteristicProjectionChange:
    actor_id: ActorId
    characteristic: CharacteristicKey
    before: int | None
    after: int
    delta: int


@dataclass(frozen=True, slots=True)
class CombatStatProjectionChange:
    actor_id: ActorId
    stat: CombatStatKey
    before: int
    after: int
    delta: int


@dataclass(frozen=True, slots=True)
class GlobalTurnCastProjectionChange:
    before: tuple[CastRecord, ...]
    after: tuple[CastRecord, ...]
    appended: CastRecord




@dataclass(frozen=True, slots=True)
class SpellTargetSequenceProjectionChange:
    before: SpellTargetSequenceState | None
    after: SpellTargetSequenceState


@dataclass(frozen=True, slots=True)
class PerMPUsedModifierProjectionChange:
    before: PerMPUsedModifierState | None
    after: PerMPUsedModifierState


@dataclass(frozen=True, slots=True)
class EffectStackProjectionChange:
    before: EffectStackState | None
    after: EffectStackState


@dataclass(frozen=True, slots=True)
class TurnHistoryProjectionChange:
    actor_id: ActorId
    before: TurnActionHistory
    after: TurnActionHistory


@dataclass(frozen=True, slots=True)
class CooldownProjectionChange:
    actor_id: ActorId
    spell_id: SpellId
    before: int
    after: int


ProjectionChange: TypeAlias = (
    SummonProjectionChange
    | CellProjectionChange
    | StateProjectionChange
    | APProjectionChange
    | APAdjustmentProjectionChange
    | MPProjectionChange
    | MPAdjustmentProjectionChange
    | RangeBonusProjectionChange
    | SpellRangeModifierProjectionChange
    | CharacteristicProjectionChange
    | CombatStatProjectionChange
    | GlobalTurnCastProjectionChange
    | SpellTargetSequenceProjectionChange
    | PerMPUsedModifierProjectionChange
    | EffectStackProjectionChange
    | TurnHistoryProjectionChange
    | CooldownProjectionChange
)


@dataclass(frozen=True, slots=True)
class FightProjection:
    base_context: FightContext
    context: FightContext
    changes: tuple[ProjectionChange, ...] = ()

    @classmethod
    def from_context(cls, context: FightContext) -> "FightProjection":
        if not isinstance(context, FightContext):
            raise TypeError("context must be a FightContext")
        return cls(base_context=context, context=context)
