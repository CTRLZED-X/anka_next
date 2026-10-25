"""P36 offline target HP/AP/MP research with competing-evidence detection.

This is an *anti-false-causality* consumer of P34 research validation. It does
not claim a caster's spell caused a target's observed resource change.
"""
from __future__ import annotations
from hashlib import sha256
from typing import Sequence

from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_contracts.target_effect_research import (
    TargetEffectWindow, TargetEffectComparison, TargetEffectResearchReport)
from anka_app.reconstruction_gaps_offline import audit_reconstruction_coverage
from anka_app.cell_transition_evidence import observed_cell_change


def _value(draft: CanonicalDraft|FightResearchDraft, metric: str, actor: int) -> int:
    if not isinstance(draft, CanonicalDraft) or draft.actor_id!=actor:
        raise ValueError('P36_TARGET_OBSERVATION_ACTOR_INVALID')
    if metric=='HP':
        if draft.kind!='ACTOR_HP_ABSOLUTE':
            raise ValueError('P36_TARGET_METRIC_KIND_MISMATCH')
    elif draft.kind!='ACTOR_RESOURCE_ABSOLUTE' or draft.resource!=metric:
        raise ValueError('P36_TARGET_METRIC_KIND_MISMATCH')
    return draft.value


def audit_target_effect_windows(
    drafts: Sequence[CanonicalDraft|FightResearchDraft],
    scope: ShadowScope,
    windows: Sequence[TargetEffectWindow],
) -> TargetEffectResearchReport:
    if not isinstance(scope,ShadowScope):
        raise TypeError('P36_SCOPE_REQUIRED')
    if not isinstance(windows,(tuple,list)) or any(not isinstance(x,TargetEffectWindow) for x in windows):
        raise TypeError('P36_WINDOWS_REQUIRED')
    if len(windows)>128:raise ValueError('P36_TOO_MANY_WINDOWS')
    base=audit_reconstruction_coverage(drafts,scope)
    count=len(drafts) if isinstance(drafts,(list,tuple)) else 0
    n=len(windows)
    def blocked(code:str, i:int=0, prior:tuple[TargetEffectComparison,...]=()):
        return TargetEffectResearchReport('BLOCKED_RESEARCH_ONLY',(code,),count,n,prior,i if n else None)
    # P34 whole-trace invalidity is a hard block even without requested
    # observation windows; an empty query must not conceal bad source evidence.
    if base.status=='BLOCKED_RESEARCH_ONLY':
        return blocked(base.reason_codes[0])
    if not windows:
        return TargetEffectResearchReport('INCOMPLETE_RESEARCH_ONLY',
               ('P36_WINDOWS_MISSING','P36_CURRENT_BUILD_NOT_CERTIFIED'),count,0,())
    seen=set();used_after={}; comparisons=[]
    reasons=['P36_CURRENT_BUILD_NOT_CERTIFIED','P36_NO_SERVER_EFFECT_CAUSAL_PROOF',
             'P36_TARGET_DELTAS_NEVER_PROVE_SPELL_OUTCOMES']
    for i,w in enumerate(windows):
        if w.after_index>=count or (w.target_cell_index is not None and w.target_cell_index>=count):
            return blocked('P36_WINDOW_INDEX_OUTSIDE_TRACE',i,tuple(comparisons))
        key=(w.cast_index,w.target_actor_id,w.metric)
        if key in seen:return blocked('P36_DUPLICATE_TARGET_METRIC_WINDOW',i,tuple(comparisons))
        seen.add(key)
        postkey=(w.after_index,w.target_actor_id,w.metric)
        if postkey in used_after and used_after[postkey]!=w.cast_index:
            return blocked('P36_REUSED_POST_SNAPSHOT_FOR_DIFFERENT_CAST',i,tuple(comparisons))
        used_after[postkey]=w.cast_index
        cast=drafts[w.cast_index]
        if not isinstance(cast,FightResearchDraft) or cast.kind!='SPELL_CAST_OBSERVED':
            return blocked('P36_CAST_OBSERVATION_REQUIRED',i,tuple(comparisons))
        if w.target_actor_id not in scope.roster_fixture:
            return blocked('P36_TARGET_OUTSIDE_VERIFIED_RESEARCH_ROSTER',i,tuple(comparisons))
        before=drafts[w.before_index]; after=drafts[w.after_index]
        coord=lambda d:(d.evidence.packet_number,d.evidence.message_index)
        if not coord(before)<coord(cast)<coord(after):
            return blocked('P36_DISTINCT_SOURCE_COORDINATES_REQUIRED',i,tuple(comparisons))
        try:
            early=_value(before,w.metric,w.target_actor_id)
            late=_value(after,w.metric,w.target_actor_id)
        except ValueError as exc:
            return blocked(str(exc),i,tuple(comparisons))
        intervening=drafts[w.cast_index+1:w.after_index]
        if any(isinstance(d,FightResearchDraft) and d.kind in
               ('TURN_END_OBSERVED','TURN_START_OBSERVED','FIGHT_END_OBSERVED') for d in intervening):
            return blocked('P36_TARGET_AFTER_TURN_BOUNDARY',i,tuple(comparisons))
        # A before/after delta can be confounded by *another* cast (including
        # earlier than the selected cast) or another absolute target snapshot.
        between=drafts[w.before_index+1:w.after_index]
        competing_cast=any(isinstance(d,FightResearchDraft) and d.kind=='SPELL_CAST_OBSERVED'
                           and idx!=w.cast_index for idx,d in
                           enumerate(between, w.before_index+1))
        intermediate_target=any(isinstance(d,CanonicalDraft) and d.actor_id==w.target_actor_id
                     and ((w.metric=='HP' and d.kind=='ACTOR_HP_ABSOLUTE') or
                          (w.metric in ('AP','MP') and d.kind=='ACTOR_RESOURCE_ABSOLUTE' and d.resource==w.metric))
                     for d in between)
        # Even target movement in the time window can make the observed target
        # exposure ambiguous. Never infer the attack's AoE or damage from pixels.
        cell_change=observed_cell_change(drafts,actor_id=w.target_actor_id,
            before_index=w.before_index,cast_index=w.cast_index,after_index=w.after_index)
        moved=cell_change in ('DISPLACEMENT','UNANCHORED_POST_OBSERVATION')
        # P39: An observed target cell transition *before* the selected cast
        # can explain an MP delta. Require two different observed cells: one
        # same-cell refresh or first-ever cell observation is not movement.
        pre_cells=(d.cell_id for d in drafts[w.before_index:w.cast_index]
                   if isinstance(d,FightResearchDraft) and d.kind=='ACTOR_CELL_OBSERVED'
                   and d.actor_id==w.target_actor_id)
        first_cell=next(pre_cells, None)
        moved_before=(w.metric=='MP' and first_cell is not None and
                      any(cell!=first_cell for cell in pre_cells))
        location='UNKNOWN'; caveats=['P36_CAUSAL_TARGET_EFFECT_UNPROVEN','P36_TARGET_GAME_SERVER_ACCEPTANCE_UNVERIFIED']
        if w.target_cell_index is None:
            caveats.append('P36_TARGET_CELL_EVIDENCE_MISSING')
        else:
            witness=drafts[w.target_cell_index]
            if not isinstance(witness,FightResearchDraft) or witness.kind!='ACTOR_CELL_OBSERVED' or witness.actor_id!=w.target_actor_id:
                return blocked('P36_TARGET_CELL_WITNESS_INVALID',i,tuple(comparisons))
            if not coord(witness)<coord(cast):
                return blocked('P36_TARGET_CELL_WITNESS_ORDER_INVALID',i,tuple(comparisons))
            after_witness=drafts[w.target_cell_index+1:w.cast_index]
            later_cell=any(isinstance(d,FightResearchDraft) and d.kind=='ACTOR_CELL_OBSERVED'
                  and d.actor_id==w.target_actor_id for d in after_witness)
            # P39: A cell match across a completed turn cannot attest the
            # target's location at cast time, even without a later cell packet.
            witness_prior_turn=any(isinstance(d,FightResearchDraft) and
                  d.kind=='TURN_END_OBSERVED' for d in after_witness)
            if later_cell:
                location='STALE_OBSERVATION';caveats.append('P36_TARGET_CELL_WITNESS_OVERRIDDEN')
            elif witness_prior_turn:
                location='STALE_OBSERVATION'
                caveats.append('P39_TARGET_CELL_WITNESS_CROSSES_COMPLETED_TURN')
            elif witness.cell_id==cast.target_cell:
                location='MATCHED_OBSERVATION'
                caveats.append('P36_CELL_MATCH_NOT_HIT_OR_SERVER_CAUSAL_PROOF')
            else:
                location='MISMATCHED_OBSERVATION'
                caveats.append('P36_DIRECT_TARGET_CELL_NOT_MATCHED_AOE_UNKNOWN')
        # Previous-turn snapshots can be displayed as a comparison, but they
        # cannot be classified as a clean change during this cast's turn.
        # Do not reject a legitimate current-turn resource snapshot merely
        # because TURN_START was observed after that snapshot.
        prior_turn_end=any(isinstance(d,FightResearchDraft) and
            d.kind=='TURN_END_OBSERVED' for d in drafts[w.before_index+1:w.cast_index])
        if competing_cast:caveats.append('P36_COMPETING_CAST_OBSERVED')
        if intermediate_target:caveats.append('P36_INTERVENING_TARGET_ABSOLUTE_VALUE')
        if moved:caveats.append('P36_TARGET_MOVED_AFTER_CAST')
        if cell_change=='UNANCHORED_POST_OBSERVATION':
            caveats.append('P41_CELL_TRANSITION_BASELINE_MISSING')
        if moved_before:caveats.append('P39_TARGET_MOVED_BEFORE_CAST')
        if prior_turn_end:caveats.append('P38_BASELINE_CROSSES_COMPLETED_TURN')
        confounded=competing_cast or intermediate_target or moved or moved_before or prior_turn_end
        relation='AMBIGUOUS' if confounded else ('UNCHANGED' if early==late else 'CHANGED')
        comparisons.append(TargetEffectComparison(i,w.metric,relation,location,tuple(caveats),late-early))
    if any(c.relation=='AMBIGUOUS' for c in comparisons):reasons.append('P36_CONFOUNDING_OBSERVATIONS_PRESENT')
    return TargetEffectResearchReport('GAPS_FOUND_RESEARCH_ONLY',tuple(reasons),count,n,tuple(comparisons))


def target_effect_research_smoke() -> dict:
    """One bounded synthetic positive and negative case for setup; zero authority."""
    scope=ShadowScope('p36_fixture','research_account',1,123,(111,222),
        'offline_3.7','research_adapter',sha256(b'p36').hexdigest(),1)
    def ref(n):return EvidenceRef(scope.protocol_build,scope.adapter_id,'Research_Event',n,
                                scope.transport_generation,scope.flow_digest)
    drafts=(FightResearchDraft('FIGHT_START_OBSERVED',ref(1),123),
            CanonicalDraft('ACTOR_HP_ABSOLUTE',222,ref(2),value=400,maximum=400),
            FightResearchDraft('ACTOR_CELL_OBSERVED',ref(3),123,actor_id=222,cell_id=215),
            FightResearchDraft('TURN_START_OBSERVED',ref(4),123,actor_id=111,turn_index=0),
            FightResearchDraft('SPELL_CAST_OBSERVED',ref(5),123,actor_id=111,spell_id=12,target_cell=215),
            CanonicalDraft('ACTOR_HP_ABSOLUTE',222,ref(6),value=350,maximum=400),
            FightResearchDraft('TURN_END_OBSERVED',ref(7),123,actor_id=111,turn_index=0),
            FightResearchDraft('FIGHT_END_OBSERVED',ref(8),123))
    good=audit_target_effect_windows(drafts,scope,(TargetEffectWindow(1,4,5,222,'HP',2),))
    wrong=audit_target_effect_windows(drafts,scope,(TargetEffectWindow(1,3,5,222),))
    # P39: make the two new guards part of the automatic setup smoke, not
    # solely developer tests. These fixtures contain no private/live data.
    stale=(drafts[0], drafts[1], drafts[2], drafts[3], drafts[6],
           FightResearchDraft('TURN_START_OBSERVED',ref(8),123,actor_id=222,turn_index=1),
           FightResearchDraft('TURN_END_OBSERVED',ref(9),123,actor_id=222,turn_index=1),
           FightResearchDraft('TURN_START_OBSERVED',ref(10),123,actor_id=111,turn_index=2),
           FightResearchDraft('SPELL_CAST_OBSERVED',ref(11),123,actor_id=111,spell_id=12,target_cell=215),
           CanonicalDraft('ACTOR_HP_ABSOLUTE',222,ref(12),value=350,maximum=400),
           FightResearchDraft('TURN_END_OBSERVED',ref(13),123,actor_id=111,turn_index=2),
           FightResearchDraft('FIGHT_END_OBSERVED',ref(14),123))
    stale_report=audit_target_effect_windows(stale,scope,(TargetEffectWindow(1,8,9,222,'HP',2),))
    movement=(drafts[0],
             CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',111,ref(2),resource='MP',value=6),
             FightResearchDraft('ACTOR_CELL_OBSERVED',ref(3),123,actor_id=111,cell_id=213),
             FightResearchDraft('TURN_START_OBSERVED',ref(4),123,actor_id=111,turn_index=0),
             FightResearchDraft('ACTOR_CELL_OBSERVED',ref(5),123,actor_id=111,cell_id=214),
             FightResearchDraft('SPELL_CAST_OBSERVED',ref(6),123,actor_id=111,spell_id=12,target_cell=215),
             CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',111,ref(7),resource='MP',value=5),
             FightResearchDraft('TURN_END_OBSERVED',ref(8),123,actor_id=111,turn_index=0),
             FightResearchDraft('FIGHT_END_OBSERVED',ref(9),123))
    movement_report=audit_target_effect_windows(movement,scope,(TargetEffectWindow(1,5,6,111,'MP',2),))
    if (stale_report.status!='GAPS_FOUND_RESEARCH_ONLY' or
        stale_report.comparisons[0].location_relation!='STALE_OBSERVATION' or
        movement_report.status!='GAPS_FOUND_RESEARCH_ONLY' or
        movement_report.comparisons[0].relation!='AMBIGUOUS'):
        raise RuntimeError('P39_TARGET_CONTEXT_SMOKE_REGRESSION')
    if (good.status!='GAPS_FOUND_RESEARCH_ONLY' or good.comparisons[0].numeric_delta!=-50 or
        good.comparisons[0].location_relation!='MATCHED_OBSERVATION' or
        wrong.reason_codes!=('P36_CAST_OBSERVATION_REQUIRED',) or
        good.actionable or good.physical_input_sent or good.committed_events or
        'numeric_delta' in str(good.to_dict())):
        raise RuntimeError('P36_TARGET_EFFECT_RESEARCH_SMOKE_REGRESSION')
    return {'status':'PASS_RESEARCH_ONLY','comparison_count':1,
            'p39_stale_witness_guard':'PASS', 'p39_precast_mp_guard':'PASS',
            'no_server_effect_claim':True,'negative':wrong.reason_codes[0],
            'current_build_certified':False,'canonical_commits':0,
            'physical_input_sent':False}
