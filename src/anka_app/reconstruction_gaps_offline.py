"""P34 app-only composition: shadow reducer compatibility + non-mutating cast audit.

No hardware adapters, no SQLite or promotion to authoritative Canonical.
The P33 reducer keeps rejecting spell casts; this module records their
unverified meaning separately and NEVER synthesizes resource/effect changes.
"""
from __future__ import annotations
from collections import Counter
from typing import Sequence

from anka_contracts.canonical import CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_contracts.reconstruction_gaps import CoverageEntry,ReconstructionCoverageReport
from anka_app.shadow_replay_offline import run_shadow_replay

_CAVEATS={
    'SPELL_CAST_OBSERVED': ('CAST_EFFECTS_UNVERIFIED','CAST_AP_SETTLEMENT_UNVERIFIED',
                            'CAST_LIMITS_AND_COOLDOWNS_UNVERIFIED','SERVER_CAST_ACCEPTANCE_UNVERIFIED'),
    'ACTOR_CELL_OBSERVED': ('MOVEMENT_PATH_AND_MP_COST_UNVERIFIED',),
    'FIGHT_END_OBSERVED': ('FIGHT_OUTCOME_NOT_VERIFIED',),
    'TURN_START_OBSERVED': ('CROSS_FLOW_SERVER_ORDER_NOT_PROVEN',),
    'TURN_END_OBSERVED': ('CROSS_FLOW_SERVER_ORDER_NOT_PROVEN',),
}
_KINDS=('FIGHT_START_OBSERVED','ACTOR_RESOURCE_ABSOLUTE','ACTOR_HP_ABSOLUTE',
        'ACTOR_COOLDOWN_SNAPSHOT','ACTOR_CELL_OBSERVED','TURN_START_OBSERVED',
        'TURN_END_OBSERVED','SPELL_CAST_OBSERVED','FIGHT_END_OBSERVED')
_REQUIRED=('hp','max_hp','AP','MP','cell_id','cooldowns')


def audit_reconstruction_coverage(drafts:Sequence[CanonicalDraft|FightResearchDraft],
                                  scope:ShadowScope)->ReconstructionCoverageReport:
    """Audit *all* supplied observations, including casts unsupported by P33.

    Casts are tested for source, fight and turn scope. The P33 projection is
    run on the exact surviving ordered subsequence, WITHOUT cast effects.
    Therefore an accepted shadow state does not mean casts were simulated.
    """
    if not isinstance(scope,ShadowScope):raise TypeError('P34_SCOPE_REQUIRED')
    kinds=Counter(getattr(d,'kind',None) for d in drafts) if isinstance(drafts,(tuple,list)) else Counter()
    n=len(drafts) if isinstance(drafts,(tuple,list)) else 0
    coverage=tuple(CoverageEntry(k,kinds[k],k!='SPELL_CAST_OBSERVED',_CAVEATS.get(k,()))
                   for k in _KINDS)
    cast_count=kinds['SPELL_CAST_OBSERVED']
    cell_count=kinds['ACTOR_CELL_OBSERVED']
    def block(code:str,idx:int|None=None):
        return ReconstructionCoverageReport('BLOCKED_RESEARCH_ONLY',(code,),n,0,cast_count,
           cell_count,0,len(scope.roster_fixture)*len(_REQUIRED),coverage,idx)
    if not isinstance(drafts,(list,tuple)) or not 0<n<=4096:
        return block('P34_EMPTY_OR_EXCESSIVE_OBSERVATIONS')
    active=None
    turn_index=-1
    started=False
    ended=False
    seen=set()
    last_pos=None
    filtered=[]
    for i,d in enumerate(drafts):
        if not isinstance(d,(CanonicalDraft,FightResearchDraft)):
            return block('P34_RESEARCH_DRAFT_REQUIRED',i)
        evidence=d.evidence
        if (evidence.protocol_build,evidence.adapter_id,evidence.flow_digest,evidence.transport_generation)!=(
            scope.protocol_build,scope.adapter_id,scope.flow_digest,scope.transport_generation):
            return block('P34_SOURCE_SCOPE_CHANGED',i)
        pos=(evidence.packet_number,evidence.message_index)
        if last_pos is not None and pos<last_pos:
            return block('P34_SOURCE_REORDERED',i)
        last_pos=pos
        claim=(pos,d.kind,getattr(d,'actor_id',None),getattr(d,'resource',None))
        if claim in seen:return block('P34_DUPLICATE_OR_CONFLICTING_SOURCE_CLAIM',i)
        seen.add(claim)
        if ended:return block('P34_EVENT_AFTER_FIGHT_END',i)
        if isinstance(d,FightResearchDraft) and d.fight_id!=scope.fight_id:
            return block('P34_FIGHT_ID_MISMATCH',i)
        actor=getattr(d,'actor_id',None)
        if actor is not None and actor not in scope.roster_fixture:
            return block('P34_ACTOR_OUTSIDE_SYNTHETIC_ROSTER',i)
        if not started:
            if not isinstance(d,FightResearchDraft) or d.kind!='FIGHT_START_OBSERVED':
                return block('P34_FIGHT_START_REQUIRED',i)
            started=True
        elif isinstance(d,FightResearchDraft) and d.kind=='FIGHT_START_OBSERVED':
            return block('P34_DUPLICATE_FIGHT_START',i)
        if isinstance(d,FightResearchDraft):
            if d.kind=='TURN_START_OBSERVED':
                if active is not None or d.turn_index<=turn_index:
                    return block('P34_TURN_OVERLAP_OR_REWIND',i)
                active=d.actor_id;turn_index=d.turn_index
            elif d.kind=='TURN_END_OBSERVED':
                if active != d.actor_id or d.turn_index!=turn_index:
                    return block('P34_TURN_END_OWNER_OR_EPOCH_MISMATCH',i)
                active=None
            elif d.kind=='SPELL_CAST_OBSERVED':
                if active is None or d.actor_id!=active:
                    return block('P34_CAST_OUTSIDE_PROVEN_TURN',i)
                # Deliberately never send casts to a reducer that cannot apply
                # server effects. An omission here remains visible in coverage.
                continue
            elif d.kind=='FIGHT_END_OBSERVED':
                if active is not None:return block('P34_FIGHT_END_WITH_ACTIVE_TURN',i)
                ended=True
        filtered.append(d)
    shadow=run_shadow_replay(tuple(filtered),scope)
    if shadow.status=='SHADOW_BLOCKED':
        return block(shadow.reason_codes[0] if shadow.reason_codes else 'P34_PROJECTION_REJECTED')
    # Re-check actor completeness from *observations*, not from fixture defaults.
    # Absolute data observed before the next start belongs only to its current fight.
    observed_fields={a:set() for a in scope.roster_fixture}
    for d in drafts:
        a=getattr(d,'actor_id',None)
        if a not in observed_fields:continue
        if isinstance(d,CanonicalDraft):
            if d.kind=='ACTOR_HP_ABSOLUTE':observed_fields[a].update(('hp','max_hp'))
            if d.kind=='ACTOR_RESOURCE_ABSOLUTE':observed_fields[a].add(d.resource)
            if d.kind=='ACTOR_COOLDOWN_SNAPSHOT':observed_fields[a].add('cooldowns')
        elif d.kind=='ACTOR_CELL_OBSERVED':observed_fields[a].add('cell_id')
    present=sum(len(fields.intersection(_REQUIRED)) for fields in observed_fields.values())
    reasons=['P34_RESEARCH_NOT_LIVE_CERTIFIED','P34_SYNTHETIC_ROSTER_NOT_IDENTITY_EVIDENCE']
    if cast_count:reasons.extend(_CAVEATS['SPELL_CAST_OBSERVED'])
    if cell_count:reasons.extend(_CAVEATS['ACTOR_CELL_OBSERVED'])
    if kinds['FIGHT_END_OBSERVED']:reasons.append('FIGHT_OUTCOME_NOT_VERIFIED')
    if kinds['TURN_START_OBSERVED']:reasons.append('CROSS_FLOW_SERVER_ORDER_NOT_PROVEN')
    if present<len(scope.roster_fixture)*len(_REQUIRED):reasons.append('P34_ACTOR_FIELDS_MISSING')
    if shadow.status!='SHADOW_CONSISTENT_RESEARCH_ONLY':reasons.append('P34_FIGHT_END_NOT_OBSERVED')
    return ReconstructionCoverageReport(
        'GAPS_FOUND_RESEARCH_ONLY' if (cast_count or cell_count or present<len(scope.roster_fixture)*len(_REQUIRED)
                                     or kinds['FIGHT_END_OBSERVED']) else 'INCOMPLETE_RESEARCH_ONLY',
        tuple(dict.fromkeys(reasons)),n,shadow.projected_events,cast_count,cell_count,
        present,len(scope.roster_fixture)*len(_REQUIRED),coverage,final_phase=shadow.final_phase)


def reconstruction_coverage_smoke()->dict:
    """Fast setup-time positive and negative P34 checks, synthetic-only."""
    from hashlib import sha256
    from anka_contracts.canonical import EvidenceRef
    scope=ShadowScope('p34_smoke','synthetic',1,123,(111,222),
                      'offline_3.7','offline_adapter',sha256(b'p34').hexdigest(),1)
    def event(kind,n,**kwargs):
        ref=EvidenceRef(scope.protocol_build,scope.adapter_id,'Offline_Event',n,
                        scope.transport_generation,scope.flow_digest)
        return FightResearchDraft(kind,ref,scope.fight_id,**kwargs)
    begin=event('FIGHT_START_OBSERVED',1)
    turn=event('TURN_START_OBSERVED',2,actor_id=111,turn_index=0)
    cast=event('SPELL_CAST_OBSERVED',3,actor_id=111,spell_id=12,target_cell=215)
    end=event('TURN_END_OBSERVED',4,actor_id=111,turn_index=0)
    finish=event('FIGHT_END_OBSERVED',5)
    normal=audit_reconstruction_coverage((begin,turn,cast,end,finish),scope)
    rejected=audit_reconstruction_coverage((begin,cast),scope)
    if (normal.status!='GAPS_FOUND_RESEARCH_ONLY' or normal.spell_cast_observations!=1
        or 'CAST_EFFECTS_UNVERIFIED' not in normal.reason_codes
        or rejected.reason_codes!=('P34_CAST_OUTSIDE_PROVEN_TURN',)
        or normal.committed_events or normal.actionable or normal.physical_input_sent):
        raise RuntimeError('P34_COVERAGE_SMOKE_REGRESSION')
    return {'status':'PASS_RESEARCH_ONLY','cast_observations':normal.spell_cast_observations,
            'effect_gap_detected':True,'negative':rejected.reason_codes[0],
            'canonical_commits':0,'current_build_certified':False,
            'physical_input_sent':False}
