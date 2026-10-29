from __future__ import annotations

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.combat_stats import Element
from anka_game_kernel.domain.ids import ActorId
from anka_game_kernel.results.actor_queries import (
    EffectiveHealthResult,
    ElementalResistanceResult,
    HealthPercentResult,
    LockDodgeResult,
    ResourceSnapshotResult,
    SummonCountResult,
)


class ActorQueryService:
    """Read-only semantic queries over a caller-owned fight snapshot."""

    @staticmethod
    def health_percent(context: FightContext, actor_id: ActorId) -> HealthPercentResult:
        actor = context.actor(actor_id)
        if actor is None:
            return HealthPercentResult.incomplete(missing_inputs=(f"actor:{actor_id}",))

        missing: list[str] = []
        if actor.current_hp is None:
            missing.append(f"actor:{actor_id}.current_hp")
        if actor.max_hp is None:
            missing.append(f"actor:{actor_id}.max_hp")
        if missing:
            return HealthPercentResult.incomplete(missing_inputs=tuple(missing))
        if actor.max_hp == 0:
            return HealthPercentResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.max_hp_positive",)
            )

        return HealthPercentResult.known(actor.current_hp * 100.0 / actor.max_hp)

    @staticmethod
    def effective_health(context: FightContext, actor_id: ActorId) -> EffectiveHealthResult:
        actor = context.actor(actor_id)
        if actor is None:
            return EffectiveHealthResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        missing: list[str] = []
        if actor.current_hp is None:
            missing.append(f"actor:{actor_id}.current_hp")
        shield_hp: int | None = None
        if actor.combat_stats is None:
            missing.append(f"actor:{actor_id}.combat_stats")
        else:
            shield_hp = actor.combat_stats.shield_hp
            if shield_hp is None:
                missing.append(f"actor:{actor_id}.combat_stats.shield_hp")
        if missing:
            return EffectiveHealthResult.incomplete(missing_inputs=tuple(missing))
        assert actor.current_hp is not None and shield_hp is not None
        return EffectiveHealthResult.known(actor.current_hp + shield_hp)

    @staticmethod
    def resource_snapshot(context: FightContext, actor_id: ActorId) -> ResourceSnapshotResult:
        actor = context.actor(actor_id)
        if actor is None:
            return ResourceSnapshotResult.incomplete(
                current_ap=None,
                max_ap=None,
                current_mp=None,
                max_mp=None,
                range_bonus=None,
                missing_inputs=(f"actor:{actor_id}",),
            )

        combat = actor.combat_stats
        max_ap = combat.max_ap if combat is not None else None
        max_mp = combat.max_mp if combat is not None else None
        range_bonus = combat.range_bonus if combat is not None else None

        missing: list[str] = []
        if actor.current_ap is None:
            missing.append(f"actor:{actor_id}.current_ap")
        if actor.current_mp is None:
            missing.append(f"actor:{actor_id}.current_mp")
        if combat is None:
            missing.extend(
                (
                    f"actor:{actor_id}.combat_stats.max_ap",
                    f"actor:{actor_id}.combat_stats.max_mp",
                    f"actor:{actor_id}.combat_stats.range_bonus",
                )
            )
        else:
            if max_ap is None:
                missing.append(f"actor:{actor_id}.combat_stats.max_ap")
            if max_mp is None:
                missing.append(f"actor:{actor_id}.combat_stats.max_mp")
            if range_bonus is None:
                missing.append(f"actor:{actor_id}.combat_stats.range_bonus")

        if missing:
            return ResourceSnapshotResult.incomplete(
                current_ap=actor.current_ap,
                max_ap=max_ap,
                current_mp=actor.current_mp,
                max_mp=max_mp,
                range_bonus=range_bonus,
                missing_inputs=tuple(missing),
            )
        return ResourceSnapshotResult.known(
            current_ap=actor.current_ap,
            max_ap=max_ap,
            current_mp=actor.current_mp,
            max_mp=max_mp,
            range_bonus=range_bonus,
        )

    @staticmethod
    def elemental_resistance(
        context: FightContext,
        actor_id: ActorId,
        element: Element,
    ) -> ElementalResistanceResult:
        if not isinstance(element, Element):
            raise TypeError("element must be an Element")
        actor = context.actor(actor_id)
        if actor is None:
            return ElementalResistanceResult.incomplete(
                missing_inputs=(f"actor:{actor_id}",)
            )
        if actor.combat_stats is None:
            return ElementalResistanceResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.combat_stats",)
            )
        resistance = actor.combat_stats.elemental_resistance(element)
        if resistance is None:
            return ElementalResistanceResult.incomplete(
                missing_inputs=(
                    f"actor:{actor_id}.combat_stats.resistance:{element.value}",
                )
            )
        return ElementalResistanceResult.known(resistance)


    @staticmethod
    def summon_count(context: FightContext, actor_id: ActorId) -> SummonCountResult:
        if context.actor(actor_id) is None:
            return SummonCountResult.incomplete(
                count=0,
                missing_inputs=(f"actor:{actor_id}",),
            )

        count = 0
        unresolved: list[str] = []
        for actor in context.actors:
            if actor.actor_id == actor_id or actor.alive is False:
                continue
            if actor.summoned is None:
                unresolved.append(f"actor:{actor.actor_id}.summoned")
                continue
            if actor.summoned is False:
                continue
            if actor.summoner_id is None:
                unresolved.append(f"actor:{actor.actor_id}.summoner_id")
                continue
            if actor.summoner_id != actor_id:
                continue
            if actor.alive is None:
                unresolved.append(f"actor:{actor.actor_id}.alive")
                continue
            count += 1

        if unresolved:
            return SummonCountResult.incomplete(
                count=count,
                missing_inputs=tuple(unresolved),
            )
        return SummonCountResult.known(count)

    @staticmethod
    def lock_dodge(context: FightContext, actor_id: ActorId) -> LockDodgeResult:
        actor = context.actor(actor_id)
        if actor is None:
            return LockDodgeResult.incomplete(
                lock=None,
                dodge=None,
                missing_inputs=(f"actor:{actor_id}",),
            )
        if actor.combat_stats is None:
            return LockDodgeResult.incomplete(
                lock=None,
                dodge=None,
                missing_inputs=(f"actor:{actor_id}.combat_stats",),
            )

        missing: list[str] = []
        if actor.combat_stats.lock is None:
            missing.append(f"actor:{actor_id}.combat_stats.lock")
        if actor.combat_stats.dodge is None:
            missing.append(f"actor:{actor_id}.combat_stats.dodge")

        if missing:
            return LockDodgeResult.incomplete(
                lock=actor.combat_stats.lock,
                dodge=actor.combat_stats.dodge,
                missing_inputs=tuple(missing),
            )
        return LockDodgeResult.known(
            lock=actor.combat_stats.lock,
            dodge=actor.combat_stats.dodge,
        )
