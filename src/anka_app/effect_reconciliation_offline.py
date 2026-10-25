"""P35: precise before/action/after evidence-link research; no inferred effects.

Runs P34's existing full provenance/turn checks before assessing any window.
No database writes, protocol activation, Game Kernel changes or input calls.
"""
from __future__ import annotations
from hashlib import sha256
from typing import Sequence

from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.effect_reconciliation import (
    ObservationWindow, ObservationComparison, EffectReconciliationReport)
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope
from anka_app.reconstruction_gaps_offline import audit_reconstruction_coverage
from anka_app.cell_transition_evidence import observed_cell_change


def _metric(draft: CanonicalDraft | FightResearchDraft, metric: str, actor: int):
    """Return an observed absolute value, never an inferred expenditure."""
    if getattr(draft, 'actor_id', None) != actor:
        raise ValueError('P35_BEFORE_AFTER_ACTOR_MISMATCH')
    if metric in ('AP','MP','RANGE'):
        if not isinstance(draft,CanonicalDraft) or draft.kind!='ACTOR_RESOURCE_ABSOLUTE' or draft.resource!=metric:
            raise ValueError('P35_RESOURCE_KIND_MISMATCH')
        return draft.value
    if metric=='HP':
        if not isinstance(draft,CanonicalDraft) or draft.kind!='ACTOR_HP_ABSOLUTE':
            raise ValueError('P35_HP_KIND_MISMATCH')
        return draft.value, draft.maximum
    if metric=='COOLDOWN':
        if not isinstance(draft,CanonicalDraft) or draft.kind!='ACTOR_COOLDOWN_SNAPSHOT':
            raise ValueError('P35_COOLDOWN_KIND_MISMATCH')
        return draft.cooldowns
    if not isinstance(draft,FightResearchDraft) or draft.kind!='ACTOR_CELL_OBSERVED':
        raise ValueError('P35_CELL_KIND_MISMATCH')
    return draft.cell_id


def audit_effect_windows(
    drafts: Sequence[CanonicalDraft | FightResearchDraft],
    scope: ShadowScope,
    windows: Sequence[ObservationWindow],
) -> EffectReconciliationReport:
    if not isinstance(scope,ShadowScope):
        raise TypeError('P35_SCOPE_REQUIRED')
    if not isinstance(windows,(tuple,list)) or any(not isinstance(w,ObservationWindow) for w in windows):
        raise TypeError('P35_WINDOWS_REQUIRED')
    if len(windows)>128:
        raise ValueError('P35_TOO_MANY_WINDOWS')
    # Guard the entire trace before reading *any* before/after values.
    base=audit_reconstruction_coverage(drafts,scope)
    count=len(drafts) if isinstance(drafts,(tuple,list)) else 0
    n=len(windows)
    def blocked(code:str,index:int|None=None,comp:tuple[ObservationComparison,...]=()):
        return EffectReconciliationReport('BLOCKED_RESEARCH_ONLY',(code,),count,n,comp,index)
    if base.status=='BLOCKED_RESEARCH_ONLY':
        return blocked(base.reason_codes[0],0 if n else None)
    if not windows:
        return EffectReconciliationReport('INCOMPLETE_RESEARCH_ONLY',
              ('P35_EXPLICIT_WINDOWS_MISSING','P35_CURRENT_BUILD_NOT_CERTIFIED'),count,0,())
    seen=set()
    used_posts={}
    comparisons=[]
    reasons=['P35_CURRENT_BUILD_NOT_CERTIFIED','P35_NO_SERVER_CAUSAL_SETTLEMENT',
             'P35_SNAPSHOT_DELTAS_DO_NOT_PROVE_CAST_OUTCOMES']
    for i,w in enumerate(windows):
        if w.after_index>=count:
            return blocked('P35_WINDOW_INDEX_OUTSIDE_TRACE',i,tuple(comparisons))
        key=(w.action_index,w.metric)
        if key in seen:
            return blocked('P35_DUPLICATE_ACTION_METRIC_LINK',i,tuple(comparisons))
        seen.add(key)
        action=drafts[w.action_index]
        before=drafts[w.before_index]
        after=drafts[w.after_index]
        if not isinstance(action,FightResearchDraft) or action.kind!='SPELL_CAST_OBSERVED':
            return blocked('P35_ACTION_MUST_BE_SPELL_OBSERVATION',i,tuple(comparisons))
        # Even if list indices increase, different fields from one wire message
        # cannot be treated as temporally ordered evidence.
        coords=lambda d:(d.evidence.packet_number,d.evidence.message_index)
        if not coords(before)<coords(action)<coords(after):
            return blocked('P35_DISTINCT_ORDERED_SOURCE_COORDINATES_REQUIRED',i,tuple(comparisons))
        # The same absolute observation cannot serve as the settlement of two casts.
        after_key=(w.after_index,w.metric)
        if after_key in used_posts and used_posts[after_key]!=w.action_index:
            return blocked('P35_REUSED_POST_SNAPSHOT_FOR_DIFFERENT_ACTION',i,tuple(comparisons))
        used_posts[after_key]=w.action_index
        try:
            earlier=_metric(before,w.metric,action.actor_id)
            later=_metric(after,w.metric,action.actor_id)
        except ValueError as exc:
            return blocked(str(exc),i,tuple(comparisons))
        # A post observation after the action's turn is too late to even describe
        # an in-turn window. A BEFORE snapshot may predate TURN_START legitimately.
        intervening=drafts[w.action_index+1:w.after_index]
        if any(isinstance(d,FightResearchDraft) and d.kind in (
            'TURN_END_OBSERVED','TURN_START_OBSERVED','FIGHT_END_OBSERVED') for d in intervening):
            return blocked('P35_POST_SNAPSHOT_OUTSIDE_ACTION_TURN',i,tuple(comparisons))
        between=drafts[w.before_index+1:w.after_index]
        other_casts=sum(isinstance(d,FightResearchDraft) and d.kind=='SPELL_CAST_OBSERVED'
                        and d.actor_id==action.actor_id for d in between if d is not action)
        # A second absolute observation before/after this cast can explain the
        # net resource difference without any spell effect. Do not present the
        # delta as an uncomplicated CHANGED/UNCHANGED cast window.
        intermediate_absolute=any(
            (isinstance(d,CanonicalDraft) and d.actor_id==action.actor_id and (
                (w.metric in ('AP','MP','RANGE') and d.kind=='ACTOR_RESOURCE_ABSOLUTE' and d.resource==w.metric) or
                (w.metric=='HP' and d.kind=='ACTOR_HP_ABSOLUTE') or
                (w.metric=='COOLDOWN' and d.kind=='ACTOR_COOLDOWN_SNAPSHOT'))) or
            (w.metric=='CELL' and isinstance(d,FightResearchDraft) and
             d.kind=='ACTOR_CELL_OBSERVED' and d.actor_id==action.actor_id)
            for d in between)
        # A baseline observed in the previous completed turn is not a current
        # turn baseline. A TURN_START before CAST is permitted: AP/MP often
        # arrives before the first TURN_START of the same active turn.
        prior_turn_end=any(isinstance(d,FightResearchDraft) and
            d.kind=='TURN_END_OBSERVED' for d in drafts[w.before_index+1:w.action_index])
        # A same-cell update is a position refresh, not an observed move.
        # If a post-cast cell is observed without a pre-cast anchor, the
        # movement question is unresolved (not safely proven absent).
        cell_change=(observed_cell_change(drafts,actor_id=action.actor_id,
            before_index=w.before_index,cast_index=w.action_index,
            after_index=w.after_index) if w.metric=='MP' else 'NONE')
        movement_observed=cell_change in ('DISPLACEMENT','UNANCHORED_POST_OBSERVATION','PRE_ONLY')
        caveats=['P35_NO_INDEPENDENT_SERVER_CAUSAL_PROOF']
        if other_casts:
            caveats.append('P35_MULTIPLE_CASTS_IN_OBSERVATION_WINDOW')
        if intermediate_absolute:
            caveats.append('P38_INTERVENING_ACTOR_METRIC_OBSERVATION')
        if prior_turn_end:
            caveats.append('P38_BASELINE_CROSSES_COMPLETED_TURN')
        if movement_observed:
            caveats.append('P38_MP_WINDOW_CONTAINS_ACTOR_CELL_OBSERVATION')
        if cell_change=='UNANCHORED_POST_OBSERVATION':
            caveats.append('P41_CELL_TRANSITION_BASELINE_MISSING')
        if w.metric=='CELL':
            caveats.append('P35_PATH_AND_MP_COST_UNKNOWN')
        if w.metric=='HP':
            caveats.append('P35_HP_CHANGE_SOURCE_UNKNOWN')
        if w.metric=='COOLDOWN':
            caveats.append('P35_COOLDOWN_CHRONOLOGY_UNVERIFIED')
        if w.metric in ('AP','MP','RANGE'):
            caveats.append('P35_RESOURCE_CHANGE_SOURCE_UNKNOWN')
        numeric_delta=(later-earlier if w.metric in ('AP','MP','RANGE','CELL') else
                      later[0]-earlier[0] if w.metric=='HP' else None)
        relation='AMBIGUOUS' if (other_casts or intermediate_absolute or prior_turn_end or movement_observed) else ('UNCHANGED' if earlier==later else 'CHANGED')
        comparisons.append(ObservationComparison(i,w.metric,relation,tuple(caveats),numeric_delta))
    if any('P35_MULTIPLE_CASTS_IN_OBSERVATION_WINDOW' in c.caveats for c in comparisons):
        reasons.append('P35_INTERVENING_CAST_MAKES_DELTA_AMBIGUOUS')
    if any(c.relation=='AMBIGUOUS' for c in comparisons):
        reasons.append('P38_OBSERVATION_WINDOW_CONFOUNDED')
    return EffectReconciliationReport('GAPS_FOUND_RESEARCH_ONLY',tuple(reasons),count,n,tuple(comparisons))


def effect_reconciliation_smoke() -> dict:
    """Tiny setup-time positive/negative P35 contract assertions."""
    scope=ShadowScope('p35_fixture','fixture_account',1,123,(111,222),
        'offline_3.7','offline_adapter',sha256(b'p35').hexdigest(),1)
    def ref(n):
        return EvidenceRef(scope.protocol_build,scope.adapter_id,'Offline_Event',n,
                           scope.transport_generation,scope.flow_digest)
    draft=(FightResearchDraft('FIGHT_START_OBSERVED',ref(1),123),
           CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',111,ref(2),resource='AP',value=11),
           FightResearchDraft('TURN_START_OBSERVED',ref(3),123,actor_id=111,turn_index=0),
           FightResearchDraft('SPELL_CAST_OBSERVED',ref(4),123,actor_id=111,spell_id=12,target_cell=215),
           CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',111,ref(5),resource='AP',value=8),
           FightResearchDraft('TURN_END_OBSERVED',ref(6),123,actor_id=111,turn_index=0),
           FightResearchDraft('FIGHT_END_OBSERVED',ref(7),123))
    good=audit_effect_windows(draft,scope,(ObservationWindow(1,3,4,'AP'),))
    bad=audit_effect_windows(draft,scope,(ObservationWindow(1,3,5,'AP'),))
    if (good.status!='GAPS_FOUND_RESEARCH_ONLY' or len(good.comparisons)!=1 or
        good.comparisons[0].numeric_delta!=-3 or good.comparisons[0].relation!='CHANGED' or
        bad.reason_codes!=('P35_RESOURCE_KIND_MISMATCH',) or
        good.actionable or good.physical_input_sent or good.committed_events):
        raise RuntimeError('P35_EFFECT_RECONCILIATION_SMOKE_REGRESSION')
    return {'status':'PASS_RESEARCH_ONLY','windows_checked':good.windows_checked,
            'negative_reason':bad.reason_codes[0], 'current_build_certified':False,
            'physical_input_sent':False,'canonical_commits':0}
