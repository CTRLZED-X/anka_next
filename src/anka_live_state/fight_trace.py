"""Derive P11 synthetic fight and turn evidence WITHOUT changing P8 projections.

R5.196 lesson: a resource observed before TURN_STARTED need not be rejected
simply because of event ordering; it may be valid in that fight. Conversely,
its freshness for *this* turn cannot be established from these fixtures.
"""
from __future__ import annotations
from anka_contracts.state import OfflineStateEvent


def trace_fight_events(events:tuple[OfflineStateEvent,...])->dict:
    if type(events) is not tuple or any(not isinstance(e,OfflineStateEvent) for e in events):
        raise TypeError('FIGHT_TRACE_FIXTURE_ONLY')
    if not events:
        return {'status':'NO_EVIDENCE','turns':0,'active_owner':None,'start_sequence':None,
                'last_resource_sequences':{},'current_turn_resource_coverage':{},
                'earlier_fight_resource_coverage':{},'actionable':False}
    # Pure research timeline with no inferred network timestamps.
    fight=None;turns=0;owner=None;turn_start=None;resources={};begun=False;ended=False
    for index,e in enumerate(events,1):
        if e.sequence!=index or (e.session_id,e.account_id,e.account_generation)!=(events[0].session_id,events[0].account_id,events[0].account_generation):
            raise ValueError('FIGHT_TRACE_SEQUENCE_INVALID')
        if e.kind=='FIGHT_STARTED':
            if begun and not ended:raise ValueError('FIGHT_TRACE_FIGHT_BOUNDARY_INVALID')
            fight=e.fight_id;begun=True;ended=False;owner=None;turn_start=None;resources={};turns=0
        elif not begun or ended or e.fight_id!=fight:
            raise ValueError('FIGHT_TRACE_EPOCH_INVALID')
        elif e.kind=='ACTOR_RESOURCE_SET':
            resources.setdefault(str(e.actor_id),{})[e.resource]=e.sequence
        elif e.kind=='TURN_STARTED':
            if owner is not None:raise ValueError('FIGHT_TRACE_OVERLAPPING_TURN')
            owner=e.actor_id;turn_start=e.sequence;turns+=1
        elif e.kind=='TURN_ENDED':
            if owner!=e.actor_id:raise ValueError('FIGHT_TRACE_TURN_OWNER_INVALID')
            owner=None;turn_start=None
        elif e.kind=='FIGHT_ENDED':
            if owner is not None:raise ValueError('FIGHT_TRACE_OVERLAPPING_TURN')
            ended=True
    latest=resources.get(str(owner),{}) if owner is not None else {}
    during=tuple(sorted(k for k,v in latest.items() if turn_start is not None and v>=turn_start))
    before=tuple(sorted(k for k,v in latest.items() if turn_start is not None and v<turn_start))
    return {'status':'SYNTHETIC_TRACE_ONLY','fight_id':fight,'turns':turns,
            'session_id':events[0].session_id,'account_id':events[0].account_id,
            'account_generation':events[0].account_generation,'last_sequence':events[-1].sequence,
            'active_owner':owner,'start_sequence':turn_start,
            'last_resource_sequences':{k:dict(v) for k,v in resources.items()},
            'current_turn_resource_coverage':{'actor_id':owner,'fields':list(during)},
            'earlier_fight_resource_coverage':{'actor_id':owner,'fields':list(before)},
            'actionable':False}
