"""Per-source, research-only turn-order consistency audit.

Never create a global CRA+ENU order from independent sockets. The audit flags
missing causal evidence but does not certify a turn owner or authorize input.
"""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.historical_lifecycle import LegacyFightObservation

@dataclass(frozen=True, slots=True)
class LegacyTimelineReport:
    status: str
    first_issue: str|None
    observation_count: int
    last_observed_round: int|None
    pending_owner: int|None
    research_only: bool = True
    live_ready: bool = False
    physical_input_sent: bool = False


def audit_historical_timeline(observations:tuple[LegacyFightObservation,...])->LegacyTimelineReport:
    """Interpret *one* bound flow/fight; decline mixed scope or missing witnesses."""
    if not observations:
        return LegacyTimelineReport('INSUFFICIENT_EVIDENCE','P45_EMPTY_SEQUENCE',0,None,None)
    first=observations[0]
    fight=first.fight_id
    flow=first.evidence.flow_digest
    generation=first.evidence.transport_generation
    build=first.evidence.protocol_build
    last_cursor=(-1,-1)
    round_no=None
    owner=None
    last_ended=None
    for i,event in enumerate(observations):
        if not isinstance(event,LegacyFightObservation):
            return LegacyTimelineReport('SCOPE_CONFLICT','P45_NOT_AN_OBSERVATION',i,round_no,owner)
        ev=event.evidence
        if (event.fight_id,ev.flow_digest,ev.transport_generation,ev.protocol_build)!=(fight,flow,generation,build):
            return LegacyTimelineReport('SCOPE_CONFLICT','P45_MIXED_FLOW_FIGHT_OR_BUILD',i,round_no,owner)
        cursor=(ev.packet_number,ev.message_index)
        if cursor<=last_cursor:
            return LegacyTimelineReport('ORDER_CONFLICT','P45_DUPLICATE_OR_REORDERED_SOURCE',i,round_no,owner)
        last_cursor=cursor
        if event.kind=='ROUND_OBSERVED':
            if round_no is not None and event.round_number<round_no:
                return LegacyTimelineReport('ORDER_CONFLICT','P45_ROUND_REGRESSION',i,round_no,owner)
            round_no=event.round_number
        elif event.kind=='TURN_OWNER_OBSERVED':
            if owner is not None and event.actor_id!=owner:
                return LegacyTimelineReport('ORDER_CONFLICT','P45_OWNER_SWITCH_WITHOUT_END',i,round_no,owner)
            if event.round_number is not None:
                if round_no is not None and event.round_number<round_no:
                    return LegacyTimelineReport('ORDER_CONFLICT','P45_TURN_ROUND_REGRESSION',i,round_no,owner)
                round_no=event.round_number
            owner=event.actor_id
            last_ended=None
        elif event.kind=='TURN_END_OBSERVED':
            if owner is None:
                return LegacyTimelineReport('INSUFFICIENT_EVIDENCE','P45_END_WITHOUT_PROVEN_OWNER',i,round_no,owner)
            if event.actor_id!=owner:
                return LegacyTimelineReport('ORDER_CONFLICT','P45_END_ACTOR_MISMATCH',i,round_no,owner)
            owner=None
            last_ended=event.actor_id
        # Ready is an observation, not proof of the first active turn.
    return LegacyTimelineReport('RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED',None,len(observations),round_no,owner)
