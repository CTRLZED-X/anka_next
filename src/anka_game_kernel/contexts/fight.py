from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.contexts.turn_history import CastRecord, TurnActionHistory
from anka_game_kernel.contexts.spell_sequences import SpellTargetSequenceState
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.contexts.effect_stacks import EffectStackState
from anka_game_kernel.domain.ids import ActorId, CellId, MapId


@dataclass(frozen=True, slots=True)
class FightContext:
    """Immutable caller-owned fight snapshot contract.

    The Kernel derives convenience views from this value but never mutates or
    refreshes it. Live reducers in the future main project remain authoritative.
    """

    actors: tuple[ActorState, ...] = ()
    round_number: int | None = None
    active_actor_id: ActorId | None = None
    turn_order: tuple[ActorId, ...] | None = None
    current_turn: TurnActionHistory | None = None
    global_turn_casts: tuple[CastRecord, ...] | None = None
    spell_target_sequences: tuple[SpellTargetSequenceState, ...] | None = None
    per_mp_used_modifiers: tuple[PerMPUsedModifierState, ...] = ()
    effect_stacks: tuple[EffectStackState, ...] = ()
    map_id: MapId | None = None
    # Geometry may be fight-instance-scoped and differ from the semantic protocol MapId.
    geometry_map_id: MapId | None = None
    # Current-fight protocol may prove specific placement cells usable even when
    # the packaged static map has stale fight-walkability bits.  This override is
    # immutable and scoped to this caller-owned fight snapshot.
    geometry_live_walkable_cells: frozenset[CellId] = frozenset()

    def __post_init__(self) -> None:
        if self.map_id is not None and not isinstance(self.map_id, MapId):
            raise TypeError("map_id must be a MapId or None")
        if self.geometry_map_id is not None and not isinstance(self.geometry_map_id, MapId):
            raise TypeError("geometry_map_id must be a MapId or None")
        if not isinstance(self.geometry_live_walkable_cells, frozenset) or any(
            not isinstance(cell_id, CellId) for cell_id in self.geometry_live_walkable_cells
        ):
            raise TypeError("geometry_live_walkable_cells must be a frozenset of CellId values")

        if self.round_number is not None:
            if isinstance(self.round_number, bool) or not isinstance(self.round_number, int):
                raise TypeError("round_number must be an int or None")
            if self.round_number < 1:
                raise ValueError("round_number must be >= 1 when known")

        actor_ids = [actor.actor_id for actor in self.actors]
        if len(set(actor_ids)) != len(actor_ids):
            raise ValueError("fight context cannot contain duplicate actor ids")

        if self.active_actor_id is not None:
            if not isinstance(self.active_actor_id, ActorId):
                raise TypeError("active_actor_id must be an ActorId or None")
            if self.active_actor_id not in actor_ids:
                raise ValueError("active_actor_id must reference an actor in the fight snapshot")

        if self.turn_order is not None:
            if not isinstance(self.turn_order, tuple) or any(
                not isinstance(actor_id, ActorId) for actor_id in self.turn_order
            ):
                raise TypeError("turn_order must be a tuple of ActorId values or None")
            if len(set(self.turn_order)) != len(self.turn_order):
                raise ValueError("turn_order cannot contain duplicate actor ids")
            unknown_turn_ids = set(self.turn_order) - set(actor_ids)
            if unknown_turn_ids:
                raise ValueError("turn_order cannot reference actors absent from the fight snapshot")

        if self.global_turn_casts is not None:
            if not isinstance(self.global_turn_casts, tuple) or any(
                not isinstance(item, CastRecord) for item in self.global_turn_casts
            ):
                raise TypeError("global_turn_casts must be a tuple of CastRecord values or None")
            unknown_casters = {item.caster_id for item in self.global_turn_casts} - set(actor_ids)
            if unknown_casters:
                raise ValueError("global_turn_casts cannot reference actors absent from the fight snapshot")

        if self.spell_target_sequences is not None:
            if not isinstance(self.spell_target_sequences, tuple) or any(
                not isinstance(item, SpellTargetSequenceState) for item in self.spell_target_sequences
            ):
                raise TypeError(
                    "spell_target_sequences must be a tuple of SpellTargetSequenceState values or None"
                )
            keys = [(item.caster_id, item.spell_id) for item in self.spell_target_sequences]
            if len(set(keys)) != len(keys):
                raise ValueError("spell_target_sequences cannot duplicate a caster/spell pair")
            unknown_actors = (
                {item.caster_id for item in self.spell_target_sequences}
                | {item.target_actor_id for item in self.spell_target_sequences}
            ) - set(actor_ids)
            if unknown_actors:
                raise ValueError(
                    "spell_target_sequences cannot reference actors absent from the fight snapshot"
                )

        if not isinstance(self.per_mp_used_modifiers, tuple) or any(
            not isinstance(item, PerMPUsedModifierState)
            for item in self.per_mp_used_modifiers
        ):
            raise TypeError(
                "per_mp_used_modifiers must be a tuple of PerMPUsedModifierState values"
            )
        modifier_keys = [
            (item.actor_id, item.source_spell_id)
            for item in self.per_mp_used_modifiers
        ]
        if len(set(modifier_keys)) != len(modifier_keys):
            raise ValueError("per_mp_used_modifiers cannot duplicate an actor/spell pair")
        unknown_modifier_actors = {
            item.actor_id for item in self.per_mp_used_modifiers
        } - set(actor_ids)
        if unknown_modifier_actors:
            raise ValueError(
                "per_mp_used_modifiers cannot reference actors absent from the fight snapshot"
            )

        if not isinstance(self.effect_stacks, tuple) or any(
            not isinstance(item, EffectStackState) for item in self.effect_stacks
        ):
            raise TypeError("effect_stacks must be a tuple of EffectStackState values")
        effect_stack_keys = [
            (item.actor_id, item.source_spell_id, item.effect_order)
            for item in self.effect_stacks
        ]
        if len(set(effect_stack_keys)) != len(effect_stack_keys):
            raise ValueError("effect_stacks cannot duplicate an actor/spell/effect-order key")
        unknown_effect_stack_actors = {item.actor_id for item in self.effect_stacks} - set(actor_ids)
        if unknown_effect_stack_actors:
            raise ValueError("effect_stacks cannot reference actors absent from the fight snapshot")

        if self.current_turn is not None:
            if not isinstance(self.current_turn, TurnActionHistory):
                raise TypeError("current_turn must be a TurnActionHistory or None")
            if self.active_actor_id is not None and self.current_turn.actor_id != self.active_actor_id:
                raise ValueError("current_turn actor must match active_actor_id")
            if self.round_number is not None and self.current_turn.round_number != self.round_number:
                raise ValueError("current_turn round must match round_number")
            if self.actor(self.current_turn.actor_id) is None:
                raise ValueError("current_turn actor must exist in the fight snapshot")
            if self.global_turn_casts is not None and any(
                cast not in self.global_turn_casts for cast in self.current_turn.casts
            ):
                raise ValueError("current_turn casts must be represented in global_turn_casts when global history is known")

        occupied = [
            actor.cell_id
            for actor in self.actors
            if actor.cell_id is not None and actor.alive is not False
        ]
        if len(set(occupied)) != len(occupied):
            raise ValueError("fight context cannot place two active actors on the same cell")

    def global_cast_count(self, spell_id) -> int | None:
        from anka_game_kernel.domain.ids import SpellId
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if self.global_turn_casts is None:
            return None
        return sum(item.spell_id == spell_id for item in self.global_turn_casts)

    def spell_target_sequence(self, caster_id, spell_id):
        from anka_game_kernel.domain.ids import SpellId
        if not isinstance(caster_id, ActorId):
            raise TypeError("caster_id must be an ActorId")
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if self.spell_target_sequences is None:
            return None
        for item in self.spell_target_sequences:
            if item.caster_id == caster_id and item.spell_id == spell_id:
                return item
        return None

    def effect_stack(self, actor_id, spell_id, effect_order):
        from anka_game_kernel.domain.ids import SpellId
        if not isinstance(actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if isinstance(effect_order, bool) or not isinstance(effect_order, int):
            raise TypeError("effect_order must be an int")
        if effect_order < 0:
            raise ValueError("effect_order cannot be negative")
        for item in self.effect_stacks:
            if (
                item.actor_id == actor_id
                and item.source_spell_id == spell_id
                and item.effect_order == effect_order
            ):
                return item
        return None

    def per_mp_used_modifier(self, actor_id, spell_id):
        from anka_game_kernel.domain.ids import SpellId
        if not isinstance(actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        for item in self.per_mp_used_modifiers:
            if item.actor_id == actor_id and item.source_spell_id == spell_id:
                return item
        return None

    @property
    def occupied_cells(self) -> frozenset[CellId] | None:
        if any(actor.cell_id is None and actor.alive is not False for actor in self.actors):
            return None
        return frozenset(
            actor.cell_id
            for actor in self.actors
            if actor.cell_id is not None and actor.alive is not False
        )


    def require_map(self, map_id: MapId) -> bool:
        """Return False when map identity is missing; reject contradictory map inputs."""
        if not isinstance(map_id, MapId):
            raise TypeError("map_id must be a MapId")
        if self.map_id is None:
            return False
        expected = self.geometry_map_id if self.geometry_map_id is not None else self.map_id
        if expected != map_id:
            raise ValueError(
                f"fight context geometry map_id {expected} (semantic={self.map_id}) does not match map definition {map_id}"
            )
        return True

    def actor(self, actor_id: ActorId) -> ActorState | None:
        for actor in self.actors:
            if actor.actor_id == actor_id:
                return actor
        return None

    def actor_at(self, cell_id: CellId) -> ActorState | None:
        for actor in self.actors:
            if actor.cell_id == cell_id and actor.alive is not False:
                return actor
        return None
