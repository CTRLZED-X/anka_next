"""P31 deterministic *research* fight chronology; no state journal mutation.

A single TCP flow/generation can be checked for internal contradictions. Matching
this timeline does NOT prove complete capture, real server ordering across
accounts, or game-world authority. It intentionally cannot produce
OfflineStateEvent (which only accepts synthetic fixtures).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from anka_contracts.fight_semantic import FightResearchDraft

@dataclass(frozen=True, slots=True)
class FightTimelineReport:
    status: str
    reason: str | None
    observed_events: int
    turn_starts: int
    turn_ends: int
    spell_casts: int
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL',init=False)
    def __post_init__(self):
        if self.status not in ('CONSISTENT_RESEARCH_ONLY','INCOMPLETE_RESEARCH','CONTRADICTION'):
            raise ValueError('RESEARCH_TIMELINE_STATUS_INVALID')
    def to_dict(self) -> dict:
        return {'status':self.status,'reason':self.reason,
                'observed_events':self.observed_events,'turn_starts':self.turn_starts,
                'turn_ends':self.turn_ends,'spell_casts':self.spell_casts,
                'live_state_authoritative':False,'canonical_commits':0,
                'actionable':False,'physical_input_sent':False}


def replay_research_timeline(events: tuple[FightResearchDraft, ...]) -> FightTimelineReport:
    """Strict internal consistency for a single ordered research-only stream."""
    starts=ends=casts=0
    def report(status,why):
        return FightTimelineReport(status,why,len(events),starts,ends,casts)
    if not isinstance(events,tuple) or len(events)>4096 or not events:
        return report('INCOMPLETE_RESEARCH','EMPTY_OR_EXCESSIVE_RESEARCH_EVENTS')
    first=events[0]
    if not isinstance(first,FightResearchDraft):
        return report('CONTRADICTION','RESEARCH_DRAFT_REQUIRED')
    e0=first.evidence
    scope=(e0.protocol_build,e0.adapter_id,e0.flow_digest,e0.transport_generation)
    seen=set(); last=None; fight=None; active_turn=None; turn_number=-1; ended=False
    for item in events:
        if not isinstance(item,FightResearchDraft) or item.authority!='RESEARCH_ONLY_NOT_CANONICAL':
            return report('CONTRADICTION','RESEARCH_DRAFT_REQUIRED')
        ref=item.evidence
        if (ref.protocol_build,ref.adapter_id,ref.flow_digest,ref.transport_generation)!=scope:
            return report('CONTRADICTION','STREAM_SCOPE_CHANGED')
        key=(ref.packet_number,ref.message_index)
        if key in seen or (last is not None and key<=last):
            return report('CONTRADICTION','DUPLICATE_OR_OUT_OF_ORDER_SOURCE')
        seen.add(key);last=key
        if fight is None:
            if item.kind!='FIGHT_START_OBSERVED':
                return report('INCOMPLETE_RESEARCH','FIGHT_START_NOT_OBSERVED')
            fight=item.fight_id
            continue
        if item.fight_id!=fight:
            return report('CONTRADICTION','FIGHT_ID_CHANGED')
        if ended:
            return report('CONTRADICTION','EVENT_AFTER_FIGHT_END')
        if item.kind=='FIGHT_START_OBSERVED':
            return report('CONTRADICTION','DUPLICATE_FIGHT_START')
        if item.kind=='TURN_START_OBSERVED':
            if active_turn is not None or item.turn_index<=turn_number:
                return report('CONTRADICTION','TURN_OVERLAP_OR_REWIND')
            active_turn=item.actor_id
            turn_number=item.turn_index
            starts+=1
        elif item.kind=='TURN_END_OBSERVED':
            if active_turn!=item.actor_id or item.turn_index!=turn_number:
                return report('CONTRADICTION','TURN_END_OWNER_OR_EPOCH_MISMATCH')
            active_turn=None;ends+=1
        elif item.kind=='SPELL_CAST_OBSERVED':
            if item.actor_id!=active_turn:
                return report('CONTRADICTION','CAST_WITHOUT_OBSERVED_OWNER')
            casts+=1
        elif item.kind=='FIGHT_END_OBSERVED':
            ended=True
    if active_turn is not None:
        return report('INCOMPLETE_RESEARCH','TURN_END_NOT_OBSERVED')
    if not ended:
        return report('INCOMPLETE_RESEARCH','FIGHT_END_NOT_OBSERVED')
    return report('CONSISTENT_RESEARCH_ONLY',None)
