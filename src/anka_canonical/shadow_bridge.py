"""P33 research draft -> synthetic reducer specs; NO Canonical authority.

Does not import Protocol, Live State, storage, or Application internals.
The caller may run these specs through an injected pure fixture reducer.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
from anka_contracts.canonical import CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope, ShadowEventSpec

MAX_OBSERVATIONS=4096

@dataclass(frozen=True,slots=True)
class ShadowBridgeResult:
    specs: tuple[ShadowEventSpec,...]
    reason: str | None
    observed: int
    fixture_events: int
    completed_fight: bool
    origin: str='RESEARCH_ONLY_NOT_CANONICAL'


def build_shadow_specs(drafts: Sequence[CanonicalDraft | FightResearchDraft],scope:ShadowScope) -> ShadowBridgeResult:
    """Build *ephemeral* fixture specs only if evidence is consistent and ordered.

    Actor registration is explicitly injected from a synthetic roster. It does
    not assert the actor appeared on the real server. A spell cast has no
    reducer-compatible event, so it BLOCKS instead of being silently dropped.
    """
    if not isinstance(scope,ShadowScope):raise TypeError('P33_SHADOW_SCOPE_REQUIRED')
    def blocked(reason:str, n:int, fixture:int=0):
        return ShadowBridgeResult((),reason,n,fixture,False)
    if not isinstance(drafts,(list,tuple)) or not drafts or len(drafts)>MAX_OBSERVATIONS:
        return blocked('P33_OBSERVATIONS_EMPTY_OR_EXCESSIVE',0)
    specs=[]
    initialized=False
    ended=False
    seen=set()
    last_position=None
    turn_index=-1
    active_turn=None
    fixture_count=0
    for i,item in enumerate(drafts):
        if not isinstance(item,(CanonicalDraft,FightResearchDraft)):
            return blocked('P33_RESEARCH_DRAFT_REQUIRED',i)
        expected='HISTORICAL_CANDIDATE_ONLY' if isinstance(item,CanonicalDraft) else 'RESEARCH_ONLY_NOT_CANONICAL'
        if item.authority!=expected:
            return blocked('P33_RESEARCH_AUTHORITY_INVALID',i)
        e=item.evidence
        if (e.protocol_build,e.adapter_id,e.flow_digest,e.transport_generation)!=(
            scope.protocol_build,scope.adapter_id,scope.flow_digest,scope.transport_generation):
            return blocked('P33_SOURCE_SCOPE_CHANGED',i)
        position=(e.packet_number,e.message_index)
        if last_position is not None and position<last_position:
            return blocked('P33_SOURCE_REORDERED',i)
        if ended:return blocked('P33_EVENT_AFTER_FIGHT_END',i)
        # Distinguish repeated legitimate fields within one wire message from a
        # repeated or conflicting claim for the *same* field at that position.
        claim=(position,item.kind,getattr(item,'actor_id',None),getattr(item,'resource',None))
        if claim in seen:return blocked('P33_DUPLICATE_OR_CONFLICTING_SOURCE_CLAIM',i)
        seen.add(claim)
        last_position=position
        if not initialized:
            if not isinstance(item,FightResearchDraft) or item.kind!='FIGHT_START_OBSERVED':
                return blocked('P33_FIGHT_START_REQUIRED',i)
            if item.fight_id!=scope.fight_id:
                return blocked('P33_FIGHT_ID_MISMATCH',i)
            specs.append(ShadowEventSpec('FIGHT_STARTED'))
            # Synthetic roster registration is explicit, never inferred from wire.
            specs.extend(ShadowEventSpec('ACTOR_SEEN',actor_id=a) for a in scope.roster_fixture)
            fixture_count=len(scope.roster_fixture)
            initialized=True
            continue
        actor=getattr(item,'actor_id',None)
        if isinstance(item,FightResearchDraft) and item.fight_id!=scope.fight_id:
            return blocked('P33_FIGHT_ID_MISMATCH',i)
        if actor is not None and actor not in scope.roster_fixture:
            return blocked('P33_ACTOR_NOT_IN_SYNTHETIC_ROSTER',i)
        if isinstance(item,CanonicalDraft):
            if item.kind=='ACTOR_RESOURCE_ABSOLUTE':
                specs.append(ShadowEventSpec('ACTOR_RESOURCE_SET',actor_id=actor,resource=item.resource,value=item.value))
            elif item.kind=='ACTOR_HP_ABSOLUTE':
                specs.append(ShadowEventSpec('ACTOR_HP_SET',actor_id=actor,value=item.value,maximum=item.maximum))
            elif item.kind=='ACTOR_COOLDOWN_SNAPSHOT':
                specs.append(ShadowEventSpec('ACTOR_COOLDOWNS_SET',actor_id=actor,cooldowns=item.cooldowns))
            else:return blocked('P33_UNSUPPORTED_RESOURCE_SEMANTIC',i)
        elif item.kind=='ACTOR_CELL_OBSERVED':
            specs.append(ShadowEventSpec('ACTOR_POSITION_SET',actor_id=actor,value=item.cell_id))
        elif item.kind=='TURN_START_OBSERVED':
            if active_turn is not None or item.turn_index<=turn_index:
                return blocked('P33_TURN_OVERLAP_OR_REWIND',i)
            active_turn=actor;turn_index=item.turn_index
            specs.append(ShadowEventSpec('TURN_STARTED',actor_id=actor))
        elif item.kind=='TURN_END_OBSERVED':
            if actor!=active_turn or item.turn_index!=turn_index:
                return blocked('P33_TURN_END_EPOCH_OR_OWNER_MISMATCH',i)
            active_turn=None
            specs.append(ShadowEventSpec('TURN_ENDED',actor_id=actor))
        elif item.kind=='FIGHT_END_OBSERVED':
            if active_turn is not None:return blocked('P33_FIGHT_ENDED_WITH_ACTIVE_TURN',i)
            ended=True;specs.append(ShadowEventSpec('FIGHT_ENDED'))
        elif item.kind=='SPELL_CAST_OBSERVED':
            return blocked('P33_SPELL_CAST_REDUCER_UNSUPPORTED',i)
        elif item.kind=='FIGHT_START_OBSERVED':
            return blocked('P33_DUPLICATE_FIGHT_START',i)
        else:return blocked('P33_UNSUPPORTED_FIGHT_SEMANTIC',i)
    return ShadowBridgeResult(tuple(specs),None,len(drafts),fixture_count,ended)
