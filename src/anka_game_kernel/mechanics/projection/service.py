from __future__ import annotations

from dataclasses import dataclass, replace

from anka_game_kernel.contexts.projection import (
    APProjectionChange,
    APAdjustmentProjectionChange,
    CellProjectionChange,
    CharacteristicProjectionChange,
    CombatStatProjectionChange,
    CooldownProjectionChange,
    FightProjection,
    GlobalTurnCastProjectionChange,
    MPProjectionChange,
    MPAdjustmentProjectionChange,
    RangeBonusProjectionChange,
    SpellRangeModifierProjectionChange,
    SpellTargetSequenceProjectionChange,
    PerMPUsedModifierProjectionChange,
    EffectStackProjectionChange,
    StateProjectionChange,
    SummonProjectionChange,
    TurnHistoryProjectionChange,
)
from anka_game_kernel.contexts.turn_history import CastRecord, MovementRecord
from anka_game_kernel.contexts.spell_sequences import SpellTargetSequenceState
from anka_game_kernel.contexts.per_mp_modifiers import PerMPUsedModifierState
from anka_game_kernel.contexts.effect_stacks import EffectStackState
from anka_game_kernel.domain.actors import ActorState, SpellCooldown
from anka_game_kernel.domain.actor_taxonomy import ActorKind, SummonKind
from anka_game_kernel.domain.combat_stats import CombatStatKey
from anka_game_kernel.domain.characteristics import (
    CharacteristicKey,
    SemanticCharacteristicValue,
    SemanticCharacteristics,
)
from anka_game_kernel.domain.spell_modifiers import ProjectedSpellRangeModifier
from anka_game_kernel.domain.ids import ActorId, CellId, CreatureId, SpellId, StateId


@dataclass(frozen=True, slots=True)
class FightProjectionService:
    """Pure helper for constructing hypothetical caller-owned fight snapshots."""

    @staticmethod
    def _replace_actor(projection: FightProjection, actor: ActorState) -> FightProjection:
        actors = tuple(
            actor if existing.actor_id == actor.actor_id else existing
            for existing in projection.context.actors
        )
        return replace(projection, context=replace(projection.context, actors=actors))

    def create_summon(
        self,
        projection: FightProjection,
        *,
        summoner_id: ActorId,
        cell_id: CellId,
        creature_id: CreatureId,
        summon_kind: SummonKind = SummonKind.NORMAL,
    ) -> FightProjection:
        summoner = projection.context.actor(summoner_id)
        if summoner is None:
            raise KeyError(f"actor {summoner_id} was not found in the projected fight context")
        if summoner.team_id is None:
            raise ValueError("summoner team is unknown and summon ownership cannot be projected")
        if projection.context.actor_at(cell_id) is not None:
            raise ValueError("summon projection requires an unoccupied target cell")
        if not isinstance(creature_id, CreatureId):
            raise TypeError("creature_id must be a CreatureId")
        if not isinstance(summon_kind, SummonKind):
            raise TypeError("summon_kind must be a SummonKind")

        # Projected summons need a context-local actor key before the server assigns the
        # authoritative runtime ActorId. Use a far-negative reserved projection band and
        # scan for a collision in the supplied snapshot; never claim this ID is live truth.
        occupied_ids = {int(actor.actor_id) for actor in projection.context.actors}
        candidate = -9_000_000_000_000_000_000
        while candidate in occupied_ids:
            candidate += 1
        created = ActorState(
            actor_id=ActorId(candidate),
            team_id=summoner.team_id,
            summoned=True,
            summoner_id=summoner_id,
            cell_id=cell_id,
            current_hp=None,
            max_hp=None,
            current_ap=None,
            current_mp=None,
            alive=True,
            actor_kind=ActorKind.MONSTER,
            summon_kind=summon_kind,
            creature_id=creature_id,
            cooldowns_complete=False,
        )
        updated = replace(
            projection,
            context=replace(
                projection.context,
                actors=projection.context.actors + (created,),
            ),
        )
        return replace(
            updated,
            changes=projection.changes + (SummonProjectionChange(created_actor=created),),
        )

    def move_actor(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        new_cell: CellId,
    ) -> FightProjection:
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.cell_id is None:
            raise ValueError(f"actor {actor_id} cell is unknown and cannot be projected")
        if not isinstance(new_cell, CellId):
            raise TypeError("new_cell must be a CellId")
        if new_cell == actor.cell_id:
            return projection
        moved_actor = replace(actor, cell_id=new_cell)
        moved = self._replace_actor(projection, moved_actor)
        change = CellProjectionChange(
            actor_id=actor_id,
            before=actor.cell_id,
            after=new_cell,
        )
        return replace(moved, changes=projection.changes + (change,))

    def spend_ap(self, projection: FightProjection, actor_id: ActorId, amount: int) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        if amount < 0:
            raise ValueError("amount cannot be negative")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.current_ap is None:
            raise ValueError(f"actor {actor_id} current AP is unknown and cannot be projected")
        after = actor.current_ap - amount
        if after < 0:
            raise ValueError("AP projection cannot produce a negative value")
        if amount == 0:
            return projection
        updated = self._replace_actor(projection, replace(actor, current_ap=after))
        change = APProjectionChange(actor_id=actor_id, before=actor.current_ap, after=after, spent=amount)
        return replace(updated, changes=projection.changes + (change,))

    def adjust_ap(
        self, projection: FightProjection, actor_id: ActorId, amount: int
    ) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.current_ap is None:
            raise ValueError(f"actor {actor_id} current AP is unknown and cannot be projected")
        before = actor.current_ap
        after = max(0, before + amount)
        delta = after - before
        if delta == 0:
            return projection
        updated = self._replace_actor(projection, replace(actor, current_ap=after))
        change = APAdjustmentProjectionChange(
            actor_id=actor_id, before=before, after=after, delta=delta
        )
        return replace(updated, changes=projection.changes + (change,))

    def spend_mp(self, projection: FightProjection, actor_id: ActorId, amount: int) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        if amount < 0:
            raise ValueError("amount cannot be negative")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.current_mp is None:
            raise ValueError(f"actor {actor_id} current MP is unknown and cannot be projected")
        after = actor.current_mp - amount
        if after < 0:
            raise ValueError("MP projection cannot produce a negative value")
        if amount == 0:
            return projection
        updated = self._replace_actor(projection, replace(actor, current_mp=after))
        change = MPProjectionChange(actor_id=actor_id, before=actor.current_mp, after=after, spent=amount)
        return replace(updated, changes=projection.changes + (change,))

    def adjust_mp(
        self, projection: FightProjection, actor_id: ActorId, amount: int
    ) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.current_mp is None:
            raise ValueError(f"actor {actor_id} current MP is unknown and cannot be projected")
        before = actor.current_mp
        after = before + amount
        if after < 0:
            raise ValueError("MP adjustment projection cannot produce a negative value")
        if amount == 0:
            return projection
        updated = self._replace_actor(projection, replace(actor, current_mp=after))
        change = MPAdjustmentProjectionChange(
            actor_id=actor_id, before=before, after=after, delta=amount
        )
        return replace(updated, changes=projection.changes + (change,))

    def adjust_range_bonus(
        self, projection: FightProjection, actor_id: ActorId, amount: int
    ) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.combat_stats is None or actor.combat_stats.range_bonus is None:
            raise ValueError(f"actor {actor_id} range bonus is unknown and cannot be projected")
        before = actor.combat_stats.range_bonus
        after = before + amount
        if amount == 0:
            return projection
        updated_actor = replace(actor, combat_stats=replace(actor.combat_stats, range_bonus=after))
        updated = self._replace_actor(projection, updated_actor)
        change = RangeBonusProjectionChange(actor_id=actor_id, before=before, after=after, delta=amount)
        return replace(updated, changes=projection.changes + (change,))

    def adjust_combat_stat(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        stat: CombatStatKey,
        amount: int,
    ) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        if not isinstance(stat, CombatStatKey):
            raise TypeError("stat must be a CombatStatKey")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.combat_stats is None:
            raise ValueError(f"actor {actor_id} combat stats are unknown")
        before = getattr(actor.combat_stats, stat.value)
        if before is None:
            raise ValueError(f"actor {actor_id} combat stat {stat.value} is unknown")
        after = before + amount
        if amount == 0:
            return projection
        updated_stats = replace(actor.combat_stats, **{stat.value: after})
        updated_actor = replace(actor, combat_stats=updated_stats)
        updated = self._replace_actor(projection, updated_actor)
        change = CombatStatProjectionChange(
            actor_id=actor_id, stat=stat, before=before, after=after, delta=amount
        )
        return replace(updated, changes=projection.changes + (change,))

    def adjust_semantic_characteristic(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        characteristic: CharacteristicKey,
        amount: int,
    ) -> FightProjection:
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("amount must be an int")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.semantic_characteristics is None:
            raise ValueError(f"actor {actor_id} semantic characteristics are unknown")
        before = actor.semantic_characteristics.get(characteristic)
        after = (0 if before is None else before) + amount
        if amount == 0:
            return projection
        kept = tuple(
            item for item in actor.semantic_characteristics.values if item.key is not characteristic
        )
        updated_semantic = SemanticCharacteristics(
            values=kept + (SemanticCharacteristicValue(characteristic, after),)
        )
        updated_actor = replace(actor, semantic_characteristics=updated_semantic)
        updated = self._replace_actor(projection, updated_actor)
        change = CharacteristicProjectionChange(
            actor_id=actor_id,
            characteristic=characteristic,
            before=before,
            after=after,
            delta=amount,
        )
        return replace(updated, changes=projection.changes + (change,))

    def add_spell_range_modifier(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        modifier: ProjectedSpellRangeModifier,
    ) -> FightProjection:
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if not isinstance(modifier, ProjectedSpellRangeModifier):
            raise TypeError("modifier must be a ProjectedSpellRangeModifier")
        # max_stacks=1 is the only verified stack behavior currently needed. Replace an
        # equivalent selector/bound from the same source rather than duplicating it.
        existing = actor.spell_range_modifiers
        if modifier.max_stacks == 1:
            existing = tuple(
                item for item in existing
                if not (
                    item.source_spell_id == modifier.source_spell_id
                    and item.bound is modifier.bound
                    and item.affected_class_id == modifier.affected_class_id
                    and item.required_tags == modifier.required_tags
                )
            )
        updated_actor = replace(actor, spell_range_modifiers=existing + (modifier,))
        updated = self._replace_actor(projection, updated_actor)
        change = SpellRangeModifierProjectionChange(actor_id=actor_id, modifier=modifier)
        return replace(updated, changes=projection.changes + (change,))


    def set_spell_target_sequence(
        self,
        projection: FightProjection,
        state: SpellTargetSequenceState,
    ) -> FightProjection:
        if not isinstance(state, SpellTargetSequenceState):
            raise TypeError("state must be a SpellTargetSequenceState")
        current = projection.context.spell_target_sequences
        if current is None:
            raise ValueError("spell target-sequence state is unknown and cannot be projected")
        before = projection.context.spell_target_sequence(state.caster_id, state.spell_id)
        kept = tuple(
            item
            for item in current
            if not (item.caster_id == state.caster_id and item.spell_id == state.spell_id)
        )
        updated = replace(
            projection,
            context=replace(projection.context, spell_target_sequences=kept + (state,)),
        )
        change = SpellTargetSequenceProjectionChange(before=before, after=state)
        return replace(updated, changes=projection.changes + (change,))

    def upsert_per_mp_used_modifier(
        self,
        projection: FightProjection,
        state: PerMPUsedModifierState,
    ) -> FightProjection:
        if not isinstance(state, PerMPUsedModifierState):
            raise TypeError("state must be a PerMPUsedModifierState")
        current = projection.context.per_mp_used_modifiers
        before = projection.context.per_mp_used_modifier(
            state.actor_id, state.source_spell_id
        )
        kept = tuple(
            item
            for item in current
            if not (
                item.actor_id == state.actor_id
                and item.source_spell_id == state.source_spell_id
            )
        )
        updated = replace(
            projection,
            context=replace(
                projection.context,
                per_mp_used_modifiers=kept + (state,),
            ),
        )
        change = PerMPUsedModifierProjectionChange(before=before, after=state)
        return replace(updated, changes=projection.changes + (change,))

    def apply_per_mp_used_modifiers(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        mp_spent: int,
    ) -> FightProjection:
        if not isinstance(actor_id, ActorId):
            raise TypeError("actor_id must be an ActorId")
        if isinstance(mp_spent, bool) or not isinstance(mp_spent, int):
            raise TypeError("mp_spent must be an int")
        if mp_spent < 0:
            raise ValueError("mp_spent cannot be negative")
        if mp_spent == 0:
            return projection

        relevant = tuple(
            item
            for item in projection.context.per_mp_used_modifiers
            if item.actor_id == actor_id and item.remaining_triggers > 0
        )
        for state in relevant:
            triggers = min(mp_spent, state.remaining_triggers)
            if triggers <= 0:
                continue
            if state.range_delta_per_mp:
                projection = self.adjust_range_bonus(
                    projection,
                    actor_id,
                    state.range_delta_per_mp * triggers,
                )
            if state.characteristic_delta_per_mp:
                projection = self.adjust_semantic_characteristic(
                    projection,
                    actor_id,
                    state.characteristic,
                    state.characteristic_delta_per_mp * triggers,
                )
            projection = self.upsert_per_mp_used_modifier(
                projection,
                replace(
                    state,
                    triggers_applied=state.triggers_applied + triggers,
                ),
            )
        return projection

    def append_cast(self, projection: FightProjection, record: CastRecord) -> FightProjection:
        history = projection.context.current_turn
        if history is None:
            raise ValueError("current turn history is unknown and cannot be projected")
        if history.actor_id != record.caster_id:
            raise ValueError("cast record actor must match projected current turn actor")
        after = replace(history, casts=history.casts + (record,))
        context_changes = {"current_turn": after}
        changes = projection.changes + (
            TurnHistoryProjectionChange(actor_id=record.caster_id, before=history, after=after),
        )
        global_before = projection.context.global_turn_casts
        if global_before is not None:
            global_after = global_before + (record,)
            context_changes["global_turn_casts"] = global_after
            changes = changes + (
                GlobalTurnCastProjectionChange(
                    before=global_before, after=global_after, appended=record
                ),
            )
        updated = replace(projection, context=replace(projection.context, **context_changes))
        return replace(updated, changes=changes)

    def append_movement(self, projection: FightProjection, record: MovementRecord) -> FightProjection:
        history = projection.context.current_turn
        if history is None:
            raise ValueError("current turn history is unknown and cannot be projected")
        if history.actor_id != record.actor_id:
            raise ValueError("movement record actor must match projected current turn actor")
        after = replace(history, movements=history.movements + (record,))
        updated = replace(projection, context=replace(projection.context, current_turn=after))
        change = TurnHistoryProjectionChange(actor_id=record.actor_id, before=history, after=after)
        return replace(updated, changes=projection.changes + (change,))

    def increment_effect_stack(
        self,
        projection: FightProjection,
        *,
        actor_id: ActorId,
        spell_id: SpellId,
        effect_order: int,
        max_stacks: int,
    ) -> FightProjection:
        if isinstance(effect_order, bool) or not isinstance(effect_order, int):
            raise TypeError("effect_order must be an int")
        if effect_order < 0:
            raise ValueError("effect_order cannot be negative")
        if isinstance(max_stacks, bool) or not isinstance(max_stacks, int):
            raise TypeError("max_stacks must be an int")
        if max_stacks < 1:
            raise ValueError("max_stacks must be >= 1")
        if projection.context.actor(actor_id) is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        before = projection.context.effect_stack(actor_id, spell_id, effect_order)
        next_stacks = min((0 if before is None else before.stacks) + 1, max_stacks)
        after = EffectStackState(actor_id=actor_id, source_spell_id=spell_id, effect_order=effect_order, stacks=next_stacks)
        stacks = tuple(
            after if (item.actor_id, item.source_spell_id, item.effect_order) == (actor_id, spell_id, effect_order) else item
            for item in projection.context.effect_stacks
        )
        if before is None:
            stacks = stacks + (after,)
        updated = replace(projection, context=replace(projection.context, effect_stacks=stacks))
        return replace(updated, changes=projection.changes + (EffectStackProjectionChange(before=before, after=after),))

    def set_cooldown(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        spell_id: SpellId,
        turns_remaining: int,
    ) -> FightProjection:
        if isinstance(turns_remaining, bool) or not isinstance(turns_remaining, int):
            raise TypeError("turns_remaining must be an int")
        if turns_remaining < 0:
            raise ValueError("turns_remaining cannot be negative")
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        before = actor.cooldown_remaining(spell_id)
        if before is None:
            raise ValueError(f"actor {actor_id} cooldown for spell {spell_id} is unknown")
        if before == turns_remaining:
            return projection
        found = any(item.spell_id == spell_id for item in actor.cooldowns)
        cooldowns = tuple(
            SpellCooldown(spell_id, turns_remaining) if item.spell_id == spell_id else item
            for item in actor.cooldowns
        )
        if not found:
            cooldowns = cooldowns + (SpellCooldown(spell_id, turns_remaining),)
        updated = self._replace_actor(projection, replace(actor, cooldowns=cooldowns))
        change = CooldownProjectionChange(
            actor_id=actor_id, spell_id=spell_id, before=before, after=turns_remaining
        )
        return replace(updated, changes=projection.changes + (change,))

    def replace_states(
        self,
        projection: FightProjection,
        actor_id: ActorId,
        new_states: frozenset[StateId],
    ) -> FightProjection:
        actor = projection.context.actor(actor_id)
        if actor is None:
            raise KeyError(f"actor {actor_id} was not found in the projected fight context")
        if actor.active_state_ids is None:
            raise ValueError(f"actor {actor_id} active state snapshot is unknown")
        if not isinstance(new_states, frozenset) or any(
            not isinstance(state_id, StateId) for state_id in new_states
        ):
            raise TypeError("new_states must be a frozenset of StateId values")
        if new_states == actor.active_state_ids:
            return projection

        before = actor.active_state_ids
        changed_actor = replace(
            actor,
            active_state_ids=new_states,
            active_states=None,
        )
        changed = self._replace_actor(projection, changed_actor)
        change = StateProjectionChange(
            actor_id=actor_id,
            before=before,
            after=new_states,
            added=new_states - before,
            removed=before - new_states,
        )
        return replace(changed, changes=projection.changes + (change,))
