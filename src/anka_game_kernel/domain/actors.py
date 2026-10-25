from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.combat_stats import ActorCombatStats
from anka_game_kernel.domain.actor_taxonomy import ActorKind, SummonKind
from anka_game_kernel.domain.characteristics import SemanticCharacteristics
from anka_game_kernel.domain.statuses import ActiveEffectInstance, ActiveStateInstance
from anka_game_kernel.domain.spell_modifiers import ProjectedSpellRangeModifier
from anka_game_kernel.domain.ids import (
    ActorId,
    CellId,
    CharacteristicId,
    ClassId,
    CompanionId,
    CreatureId,
    MonsterId,
    SpellId,
    StateId,
    TeamId,
)


@dataclass(frozen=True, slots=True)
class CharacteristicValue:
    characteristic_id: CharacteristicId
    value: int

    def __post_init__(self) -> None:
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError("characteristic value must be an int")


@dataclass(frozen=True, slots=True)
class SpellCooldown:
    spell_id: SpellId
    turns_remaining: int

    def __post_init__(self) -> None:
        if isinstance(self.turns_remaining, bool) or not isinstance(self.turns_remaining, int):
            raise TypeError("turns_remaining must be an int")
        if self.turns_remaining < 0:
            raise ValueError("turns_remaining cannot be negative")


@dataclass(frozen=True, slots=True)
class ActorState:
    actor_id: ActorId
    team_id: TeamId | None = None
    summoned: bool | None = None
    summoner_id: ActorId | None = None
    cell_id: CellId | None = None
    current_hp: int | None = None
    max_hp: int | None = None
    current_ap: int | None = None
    current_mp: int | None = None
    active_state_ids: frozenset[StateId] | None = None
    active_states: tuple[ActiveStateInstance, ...] | None = None
    active_effects: tuple[ActiveEffectInstance, ...] | None = None
    characteristics: tuple[CharacteristicValue, ...] = ()
    cooldowns: tuple[SpellCooldown, ...] = ()
    # Keep ``alive`` immediately after ``cooldowns``.  This is part of the
    # historical positional-construction contract used by the deterministic
    # kernel and by archived replay/regression fixtures.  New extension fields
    # must be appended after the historical fields instead of being inserted
    # into this prefix.
    alive: bool | None = None
    combat_stats: ActorCombatStats | None = None
    semantic_characteristics: SemanticCharacteristics | None = None
    actor_kind: ActorKind = ActorKind.UNKNOWN
    summon_kind: SummonKind | None = None
    class_id: ClassId | None = None
    monster_id: MonsterId | None = None
    companion_id: CompanionId | None = None
    creature_id: CreatureId | None = None
    spell_range_modifiers: tuple[ProjectedSpellRangeModifier, ...] = ()
    # Range-property traffic can be identity-certified while its arithmetic is
    # still unresolved. Mark only affected spells unknown instead of either
    # guessing the modifier or poisoning every spell range.
    spell_range_unknown_spell_ids: frozenset[SpellId] = frozenset()
    cooldowns_complete: bool = False
    previous_turn_enemy_attacks_received: int | None = None
    eroded_hp: int | None = None
    # A complete cooldown snapshot can still become stale for one spell after a
    # newer confirmed cast whose grade/rule cannot yet be reconciled.  This
    # extension field is deliberately appended so it cannot remap historical
    # positional ActorState constructors.
    cooldown_unknown_spell_ids: frozenset[SpellId] = frozenset()

    def __post_init__(self) -> None:
        for name, value in (
            ("current_hp", self.current_hp),
            ("max_hp", self.max_hp),
            ("eroded_hp", self.eroded_hp),
            ("current_ap", self.current_ap),
            ("current_mp", self.current_mp),
        ):
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError(f"{name} must be an int or None")
                if value < 0:
                    raise ValueError(f"{name} cannot be negative")
        if not isinstance(self.cooldowns_complete, bool):
            raise TypeError("cooldowns_complete must be a bool")
        if not isinstance(self.cooldown_unknown_spell_ids, frozenset):
            raise TypeError("cooldown_unknown_spell_ids must be a frozenset")
        if any(not isinstance(value, SpellId) for value in self.cooldown_unknown_spell_ids):
            raise TypeError("cooldown_unknown_spell_ids must contain SpellId values")
        if self.previous_turn_enemy_attacks_received is not None:
            if isinstance(self.previous_turn_enemy_attacks_received, bool) or not isinstance(
                self.previous_turn_enemy_attacks_received, int
            ):
                raise TypeError("previous_turn_enemy_attacks_received must be an int or None")
            if self.previous_turn_enemy_attacks_received < 0:
                raise ValueError("previous_turn_enemy_attacks_received cannot be negative")
        if self.alive is not None and not isinstance(self.alive, bool):
            raise TypeError("alive must be a bool or None")
        if self.summoned is not None and not isinstance(self.summoned, bool):
            raise TypeError("summoned must be a bool or None")
        if self.summoner_id is not None and self.summoned is False:
            raise ValueError("summoner_id cannot be set when summoned is explicitly false")
        if not isinstance(self.actor_kind, ActorKind):
            raise TypeError("actor_kind must be an ActorKind")
        if self.summon_kind is not None and not isinstance(self.summon_kind, SummonKind):
            raise TypeError("summon_kind must be a SummonKind or None")
        if self.summon_kind is not None and self.summoned is not True:
            raise ValueError("summon_kind requires summoned=True")
        if self.class_id is not None:
            if not isinstance(self.class_id, ClassId):
                raise TypeError("class_id must be a ClassId or None")
            if self.actor_kind is not ActorKind.PLAYER:
                raise ValueError("class_id requires actor_kind=player")
        if self.monster_id is not None:
            if not isinstance(self.monster_id, MonsterId):
                raise TypeError("monster_id must be a MonsterId or None")
            if self.actor_kind is not ActorKind.MONSTER:
                raise ValueError("monster_id requires actor_kind=monster")
        if self.companion_id is not None:
            if not isinstance(self.companion_id, CompanionId):
                raise TypeError("companion_id must be a CompanionId or None")
            if self.actor_kind is not ActorKind.COMPANION:
                raise ValueError("companion_id requires actor_kind=companion")
        if self.creature_id is not None and not isinstance(self.creature_id, CreatureId):
            raise TypeError("creature_id must be a CreatureId or None")
        if not isinstance(self.spell_range_modifiers, tuple):
            raise TypeError("spell_range_modifiers must be a tuple")
        if any(not isinstance(value, ProjectedSpellRangeModifier) for value in self.spell_range_modifiers):
            raise TypeError("spell_range_modifiers must contain ProjectedSpellRangeModifier values")
        if not isinstance(self.spell_range_unknown_spell_ids, frozenset):
            raise TypeError("spell_range_unknown_spell_ids must be a frozenset")
        if any(not isinstance(value, SpellId) for value in self.spell_range_unknown_spell_ids):
            raise TypeError("spell_range_unknown_spell_ids must contain SpellId values")
        if self.combat_stats is not None and not isinstance(self.combat_stats, ActorCombatStats):
            raise TypeError("combat_stats must be ActorCombatStats or None")
        if self.semantic_characteristics is not None and not isinstance(
            self.semantic_characteristics, SemanticCharacteristics
        ):
            raise TypeError("semantic_characteristics must be SemanticCharacteristics or None")
        if self.active_states is not None:
            if not isinstance(self.active_states, tuple):
                raise TypeError("active_states must be a tuple of ActiveStateInstance values or None")
            if any(not isinstance(item, ActiveStateInstance) for item in self.active_states):
                raise TypeError("active_states must contain only ActiveStateInstance values")
            detailed_state_ids = frozenset(item.state_id for item in self.active_states)
            if self.active_state_ids is None:
                object.__setattr__(self, "active_state_ids", detailed_state_ids)
            elif self.active_state_ids != detailed_state_ids:
                raise ValueError("active_state_ids must match the IDs represented by active_states")

        if self.active_effects is not None:
            if not isinstance(self.active_effects, tuple):
                raise TypeError("active_effects must be a tuple of ActiveEffectInstance values or None")
            if any(not isinstance(item, ActiveEffectInstance) for item in self.active_effects):
                raise TypeError("active_effects must contain only ActiveEffectInstance values")

        if self.active_state_ids is not None:
            if not isinstance(self.active_state_ids, frozenset):
                raise TypeError("active_state_ids must be a frozenset of StateId values or None")
            if any(not isinstance(state_id, StateId) for state_id in self.active_state_ids):
                raise TypeError("active_state_ids must contain only StateId values")

        characteristic_ids = [item.characteristic_id for item in self.characteristics]
        if len(set(characteristic_ids)) != len(characteristic_ids):
            raise ValueError("actor state cannot contain duplicate characteristic ids")
        cooldown_spell_ids = [item.spell_id for item in self.cooldowns]
        if len(set(cooldown_spell_ids)) != len(cooldown_spell_ids):
            raise ValueError("actor state cannot contain duplicate spell cooldowns")
        if set(cooldown_spell_ids).intersection(self.cooldown_unknown_spell_ids):
            raise ValueError("a spell cooldown cannot be both known and explicitly unknown")

    def characteristic(self, characteristic_id: CharacteristicId) -> int | None:
        for item in self.characteristics:
            if item.characteristic_id == characteristic_id:
                return item.value
        return None

    def cooldown_remaining(self, spell_id: SpellId) -> int | None:
        if spell_id in self.cooldown_unknown_spell_ids:
            return None
        for cooldown in self.cooldowns:
            if cooldown.spell_id == spell_id:
                return cooldown.turns_remaining
        if self.cooldowns_complete:
            return 0
        return None
