"""P17 pure party coordination model; no input, protocol, workflow, or clock imports.

A pending end-turn intent is NOT an observed turn end. All timeouts use
fixture logical ticks; actual real-time deadline policy is not certified.
"""
from __future__ import annotations
from anka_contracts.coordination_flow import PartyMember, PartyFixtureEvent, PartyTimelineReport


class PartyFixtureRejected(ValueError):
    pass


def replay_party(members: tuple[PartyMember, ...], events: tuple[PartyFixtureEvent, ...], *, wait_ticks: int = 4) -> PartyTimelineReport:
    if (type(members) is not tuple or not 2 <= len(members) <= 8
            or any(not isinstance(m, PartyMember) for m in members)
            or len({m.account_id for m in members}) != len(members)
            or len({m.actor_id for m in members}) != len(members)
            or sum(m.role == 'leader' for m in members) != 1):
        raise PartyFixtureRejected('P17_PARTY_MEMBERS_INVALID')
    if (type(events) is not tuple or len(events) > 512
            or any(not isinstance(e, PartyFixtureEvent) for e in events)):
        raise PartyFixtureRejected('P17_TIMELINE_INVALID')
    if type(wait_ticks) is not int or not 1 <= wait_ticks <= 1000:
        raise PartyFixtureRejected('P17_WAIT_BUDGET_INVALID')
    identities = {m.account_id: m for m in members}
    ready: set[str] = set()
    fight: str | None = None
    owner: int | None = None
    pending: int | None = None
    phase = 'WAIT_READY'
    phase_tick = 0
    reasons: list[str] = []
    failure_seq: int | None = None
    trace: list[tuple[int, str, str]] = []
    last_tick = 0
    event_ids: set[str] = set()
    for index, event in enumerate(events, 1):
        if event.sequence != index or event.tick < last_tick or event.event_id in event_ids:
            raise PartyFixtureRejected('P17_EVENT_ORDER_OR_DUPLICATE')
        last_tick = event.tick
        event_ids.add(event.event_id)
        if event.kind in ('READY', 'TURN_STARTED', 'END_TURN_INTENDED', 'TURN_ENDED', 'DISCONNECTED'):
            member = identities.get(event.account_id)
            if member is None or (event.generation, event.actor_id) != (member.generation, member.actor_id):
                reason = 'P17_ACCOUNT_GENERATION_OR_ACTOR_MISMATCH'
            else:
                reason = None
        else:
            reason = None
        if reason is None and event.kind in ('FIGHT_STARTED', 'TURN_STARTED', 'END_TURN_INTENDED', 'TURN_ENDED', 'FIGHT_ENDED'):
            if fight is not None and event.fight_id != fight:
                reason = 'P17_FIGHT_EPOCH_CONFLICT'
        if reason is None and phase in ('FINISHED', 'QUARANTINED'):
            reason = 'P17_EVENT_AFTER_TERMINAL_STATE'
        # Timeouts must be checked at every event boundary, not only when an
        # optional CHECK event is emitted. A late confirmation is not success.
        if reason is None:
            elapsed = event.tick - (phase_tick if phase != 'WAIT_READY' else 0)
            timeout_codes = {'WAIT_READY':'P17_READY_TIMEOUT',
                             'WAIT_FIGHT':'P17_FIGHT_START_TIMEOUT',
                             'WAIT_FIRST_TURN':'P17_FIRST_TURN_TIMEOUT',
                             'WAIT_TURN_END':'P17_TURN_END_UNCONFIRMED',
                             'WAIT_NEXT_TURN':'P17_NEXT_TURN_TIMEOUT'}
            if phase in timeout_codes and elapsed > wait_ticks:
                reason = timeout_codes[phase]
        if reason is None:
            k = event.kind
            if k == 'READY':
                if phase not in ('WAIT_READY', 'WAIT_FIGHT') or event.account_id in ready:
                    reason = 'P17_READY_PHASE_OR_DUPLICATE'
                else:
                    ready.add(event.account_id)
                    if len(ready) == len(members):
                        phase = 'WAIT_FIGHT'
                        phase_tick = event.tick
            elif k == 'FIGHT_STARTED':
                if phase != 'WAIT_FIGHT':
                    reason = 'P17_FIGHT_BEFORE_ALL_READY'
                else:
                    fight = event.fight_id
                    phase = 'WAIT_FIRST_TURN'
                    phase_tick = event.tick
            elif k == 'TURN_STARTED':
                if phase not in ('WAIT_FIRST_TURN', 'WAIT_NEXT_TURN') or owner is not None or pending is not None:
                    reason = 'P17_OVERLAPPING_OR_EARLY_TURN'
                else:
                    owner = event.actor_id
                    phase = 'TURN_ACTIVE'
                    phase_tick = event.tick
            elif k == 'END_TURN_INTENDED':
                if phase != 'TURN_ACTIVE' or event.actor_id != owner:
                    reason = 'P17_END_INTENT_NOT_OWNER'
                else:
                    pending = owner
                    phase = 'WAIT_TURN_END'
                    phase_tick = event.tick
            elif k == 'TURN_ENDED':
                if phase != 'WAIT_TURN_END' or event.actor_id != pending or event.actor_id != owner:
                    reason = 'P17_UNCONFIRMED_OR_WRONG_TURN_END'
                else:
                    pending = None
                    owner = None
                    phase = 'WAIT_NEXT_TURN'
                    phase_tick = event.tick
            elif k == 'FIGHT_ENDED':
                if phase not in ('WAIT_FIRST_TURN', 'TURN_ACTIVE', 'WAIT_TURN_END', 'WAIT_NEXT_TURN'):
                    reason = 'P17_FIGHT_END_OUT_OF_PHASE'
                else:
                    pending = None
                    owner = None
                    phase = 'FINISHED'
            elif k == 'CHECK':
                if phase in ('WAIT_FIGHT', 'WAIT_FIRST_TURN', 'WAIT_TURN_END', 'WAIT_NEXT_TURN') and event.tick - phase_tick > wait_ticks:
                    reason = {'WAIT_FIGHT': 'P17_FIGHT_START_TIMEOUT',
                              'WAIT_FIRST_TURN': 'P17_FIRST_TURN_TIMEOUT',
                              'WAIT_TURN_END': 'P17_TURN_END_UNCONFIRMED',
                              'WAIT_NEXT_TURN': 'P17_NEXT_TURN_TIMEOUT'}[phase]
                elif phase == 'WAIT_READY' and event.tick > wait_ticks:
                    reason = 'P17_READY_TIMEOUT'
            elif k == 'DISCONNECTED':
                reason = 'P17_PARTY_DISCONNECTED'
        if reason is not None:
            reasons.append(reason)
            failure_seq = event.sequence
            phase = 'QUARANTINED'
        trace.append((event.sequence, event.kind, phase))
        if reasons:
            break  # first divergence is retained; no later event may silently repair the timeline
    needed = {'WAIT_READY': ('READY',), 'WAIT_FIGHT': ('FIGHT_STARTED',),
              'WAIT_FIRST_TURN': ('TURN_STARTED',), 'TURN_ACTIVE': ('END_TURN_INTENDED', 'FIGHT_ENDED'),
              'WAIT_TURN_END': ('TURN_ENDED', 'FIGHT_ENDED'),
              'WAIT_NEXT_TURN': ('TURN_STARTED', 'FIGHT_ENDED'),
              'FINISHED': (), 'QUARANTINED': ('NEW_CERTIFIED_FIGHT_EPOCH_REQUIRED',)}[phase]
    return PartyTimelineReport(phase, fight, owner, tuple(sorted(ready)), pending,
                               tuple(reasons), needed, trace[-1][0] if trace else 0,
                               failure_seq, tuple(trace[-40:]))
