from __future__ import annotations

from anka_game_kernel.contexts.fight import FightContext
from anka_game_kernel.domain.ids import ActorId, EffectId, StateId
from anka_game_kernel.domain.statuses import ActiveEffectInstance, ActiveStateInstance
from anka_game_kernel.results.status_queries import (
    ActiveEffectsResult,
    ActiveStatesResult,
    StatusForecastResult,
    StatusPresenceResult,
    StatusTurnsResult,
)


class StatusQueryService:
    """Read-only queries over caller-owned active state/effect snapshots."""

    @staticmethod
    def _validate_ticks(ticks_ahead: int) -> None:
        if isinstance(ticks_ahead, bool) or not isinstance(ticks_ahead, int):
            raise TypeError("ticks_ahead must be an int")
        if ticks_ahead < 0:
            raise ValueError("ticks_ahead cannot be negative")

    @staticmethod
    def active_states(context: FightContext, actor_id: ActorId) -> ActiveStatesResult:
        actor = context.actor(actor_id)
        if actor is None:
            return ActiveStatesResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_states is None:
            return ActiveStatesResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_states",)
            )
        return ActiveStatesResult.known(actor.active_states)

    @staticmethod
    def active_effects(context: FightContext, actor_id: ActorId) -> ActiveEffectsResult:
        actor = context.actor(actor_id)
        if actor is None:
            return ActiveEffectsResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_effects is None:
            return ActiveEffectsResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_effects",)
            )
        return ActiveEffectsResult.known(actor.active_effects)

    @staticmethod
    def state_presence(
        context: FightContext,
        actor_id: ActorId,
        state_id: StateId,
    ) -> StatusPresenceResult:
        actor = context.actor(actor_id)
        if actor is None:
            return StatusPresenceResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_state_ids is None:
            return StatusPresenceResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_state_ids",)
            )
        return StatusPresenceResult.known(state_id in actor.active_state_ids)

    @staticmethod
    def effect_presence(
        context: FightContext,
        actor_id: ActorId,
        effect_id: EffectId,
    ) -> StatusPresenceResult:
        actor = context.actor(actor_id)
        if actor is None:
            return StatusPresenceResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_effects is None:
            return StatusPresenceResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_effects",)
            )
        return StatusPresenceResult.known(
            any(item.effect_id == effect_id for item in actor.active_effects)
        )

    @staticmethod
    def state_turns(
        context: FightContext,
        actor_id: ActorId,
        state_id: StateId,
    ) -> StatusTurnsResult:
        actor = context.actor(actor_id)
        if actor is None:
            return StatusTurnsResult.incomplete(
                active=None,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}",),
            )
        if actor.active_state_ids is None:
            return StatusTurnsResult.incomplete(
                active=None,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.active_state_ids",),
            )
        if state_id not in actor.active_state_ids:
            return StatusTurnsResult.known(active=False, turns_remaining=0)
        if actor.active_states is None:
            return StatusTurnsResult.incomplete(
                active=True,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.active_states",),
            )
        matches = tuple(item for item in actor.active_states if item.state_id == state_id)
        return StatusQueryService._turns_from_state_matches(actor_id, state_id, matches)

    @staticmethod
    def _turns_from_state_matches(
        actor_id: ActorId,
        state_id: StateId,
        matches: tuple[ActiveStateInstance, ...],
    ) -> StatusTurnsResult:
        if len(matches) != 1:
            return StatusTurnsResult.incomplete(
                active=True,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.state:{state_id}.instance_aggregation",),
            )
        turns = matches[0].turns_remaining
        if turns is None:
            return StatusTurnsResult.incomplete(
                active=True,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.state:{state_id}.turns_remaining",),
            )
        return StatusTurnsResult.known(active=True, turns_remaining=turns)

    @staticmethod
    def effect_turns(
        context: FightContext,
        actor_id: ActorId,
        effect_id: EffectId,
    ) -> StatusTurnsResult:
        actor = context.actor(actor_id)
        if actor is None:
            return StatusTurnsResult.incomplete(
                active=None,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}",),
            )
        if actor.active_effects is None:
            return StatusTurnsResult.incomplete(
                active=None,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.active_effects",),
            )
        matches = tuple(item for item in actor.active_effects if item.effect_id == effect_id)
        if not matches:
            return StatusTurnsResult.known(active=False, turns_remaining=0)
        if len(matches) != 1:
            return StatusTurnsResult.incomplete(
                active=True,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.effect:{effect_id}.instance_aggregation",),
            )
        turns = matches[0].turns_remaining
        if turns is None:
            return StatusTurnsResult.incomplete(
                active=True,
                turns_remaining=None,
                missing_inputs=(f"actor:{actor_id}.effect:{effect_id}.turns_remaining",),
            )
        return StatusTurnsResult.known(active=True, turns_remaining=turns)

    @staticmethod
    def state_active_after_ticks(
        context: FightContext,
        actor_id: ActorId,
        state_id: StateId,
        ticks_ahead: int,
    ) -> StatusForecastResult:
        StatusQueryService._validate_ticks(ticks_ahead)
        actor = context.actor(actor_id)
        if actor is None:
            return StatusForecastResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_state_ids is None:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_state_ids",)
            )
        if state_id not in actor.active_state_ids:
            return StatusForecastResult.known(False)
        if ticks_ahead == 0:
            return StatusForecastResult.known(True)
        if actor.active_states is None:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_states",)
            )
        matches = tuple(item for item in actor.active_states if item.state_id == state_id)
        if len(matches) != 1:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.state:{state_id}.instance_aggregation",)
            )
        active = matches[0].active_after_ticks(ticks_ahead)
        if active is None:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.state:{state_id}.turns_remaining",)
            )
        return StatusForecastResult.known(active)

    @staticmethod
    def effect_active_after_ticks(
        context: FightContext,
        actor_id: ActorId,
        effect_id: EffectId,
        ticks_ahead: int,
    ) -> StatusForecastResult:
        StatusQueryService._validate_ticks(ticks_ahead)
        actor = context.actor(actor_id)
        if actor is None:
            return StatusForecastResult.incomplete(missing_inputs=(f"actor:{actor_id}",))
        if actor.active_effects is None:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.active_effects",)
            )
        matches = tuple(item for item in actor.active_effects if item.effect_id == effect_id)
        if not matches:
            return StatusForecastResult.known(False)
        if ticks_ahead == 0:
            return StatusForecastResult.known(True)
        if len(matches) != 1:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.effect:{effect_id}.instance_aggregation",)
            )
        active = matches[0].active_after_ticks(ticks_ahead)
        if active is None:
            return StatusForecastResult.incomplete(
                missing_inputs=(f"actor:{actor_id}.effect:{effect_id}.turns_remaining",)
            )
        return StatusForecastResult.known(active)
