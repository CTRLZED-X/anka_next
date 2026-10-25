"""P33 composition: independent research bridge -> pure synthetic reducer.

No SQLite connection, real device driver, Canonical admission, or authorization.
"""
from __future__ import annotations
from typing import Sequence
from anka_contracts.canonical import CanonicalDraft
from anka_contracts.fight_semantic import FightResearchDraft
from anka_contracts.shadow_replay import ShadowScope, ShadowReplayReport
from anka_contracts.state import OfflineStateEvent
from anka_canonical.shadow_bridge import build_shadow_specs
from anka_live_state.reducer import apply_offline_event,StateTransitionError


def run_shadow_replay(drafts:Sequence[CanonicalDraft|FightResearchDraft],scope:ShadowScope)->ShadowReplayReport:
    bridge=build_shadow_specs(drafts,scope)
    if bridge.reason:
        return ShadowReplayReport('SHADOW_BLOCKED',(bridge.reason,),bridge.observed,bridge.fixture_events,0,None)
    state=None
    for idx,spec in enumerate(bridge.specs,1):
        try:
            event=OfflineStateEvent(event_id=f'fixture_shadow_{idx}',session_id=scope.session_id,
                account_id=scope.account_id,account_generation=scope.account_generation,
                fight_id=str(scope.fight_id),sequence=idx,kind=spec.kind,actor_id=spec.actor_id,
                resource=spec.resource,value=spec.value,maximum=spec.maximum,cooldowns=spec.cooldowns)
            state=apply_offline_event(state,event)
        except (StateTransitionError,ValueError,TypeError,KeyError) as exc:
            # Only emit stable known error codes: no source content or player data.
            code=str(exc)
            if not (code.startswith('STATE_') and len(code)<120):code='P33_SYNTHETIC_PROJECTION_REJECTED'
            return ShadowReplayReport('SHADOW_BLOCKED',(code,),bridge.observed,
                                      bridge.fixture_events,idx-1,None)
    completed=bridge.completed_fight and state is not None and state.get('phase')=='ENDED'
    return ShadowReplayReport(
        'SHADOW_CONSISTENT_RESEARCH_ONLY' if completed else 'SHADOW_INCOMPLETE_RESEARCH',
        ('P33_SYNTHETIC_ROSTER_NOT_LIVE_EVIDENCE',
         'P33_SERVER_AND_CURRENT_BUILD_NOT_CERTIFIED') + (() if completed else ('P33_FIGHT_END_NOT_OBSERVED',)),
        bridge.observed,bridge.fixture_events,len(bridge.specs),state.get('phase') if state else None)


def shadow_bridge_smoke() -> dict:
    """Tiny setup-time positive and negative contract check (no OS input)."""
    from hashlib import sha256
    from anka_contracts.canonical import EvidenceRef, CanonicalDraft
    from anka_contracts.fight_semantic import FightResearchDraft
    scope = ShadowScope('smoke', 'fixture', 1, 123, (111, 222),
                        'offline_3.7', 'offline_adapter', sha256(b'fixture').hexdigest(), 1)
    def ref(i):
        return EvidenceRef(scope.protocol_build,scope.adapter_id,'Offline_Event',i,1,scope.flow_digest)
    base = (FightResearchDraft('FIGHT_START_OBSERVED',ref(1),123),
            CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',111,ref(2),resource='AP',value=10),
            FightResearchDraft('TURN_START_OBSERVED',ref(3),123,actor_id=111,turn_index=0),
            FightResearchDraft('TURN_END_OBSERVED',ref(4),123,actor_id=111,turn_index=0),
            FightResearchDraft('FIGHT_END_OBSERVED',ref(5),123))
    good=run_shadow_replay(base,scope)
    bad=run_shadow_replay((base[0],base[2],
        FightResearchDraft('TURN_END_OBSERVED',ref(4),123,actor_id=222,turn_index=0)),scope)
    if (good.status!='SHADOW_CONSISTENT_RESEARCH_ONLY' or
        bad.status!='SHADOW_BLOCKED' or
        bad.reason_codes!=('P33_TURN_END_EPOCH_OR_OWNER_MISMATCH',) or
        good.committed_events or good.actionable or bad.committed_events):
        raise RuntimeError('P33_SHADOW_BRIDGE_REGRESSION')
    return {'status':'PASS_SYNTHETIC_ONLY','positive':good.status,
            'negative':bad.reason_codes[0],'canonical_commits':0,
            'current_build_certified':False,'physical_input_sent':False}
