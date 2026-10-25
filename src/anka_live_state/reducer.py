"""Pure deterministic P8 reducer; isolated from Capture, Protocol and SQLite.

Projections are evidence views, never execution authorizations. All data is
constructed from validated synthetic events in P8; missing facts stay None.
"""
from __future__ import annotations
from copy import deepcopy
from anka_contracts.state import OfflineStateEvent

class StateTransitionError(ValueError):pass


def apply_offline_event(previous:dict|None,event:OfflineStateEvent)->dict:
    if not isinstance(event,OfflineStateEvent):raise TypeError('STATE_FIXTURE_EVENT_REQUIRED')
    current=deepcopy(previous) if previous is not None else None
    if current is None:
        if event.kind!='FIGHT_STARTED' or event.sequence!=1:
            raise StateTransitionError('STATE_FIRST_EVENT_MUST_START_FIGHT')
        return {'schema':1,'session_id':event.session_id,'account_id':event.account_id,
                'account_generation':event.account_generation,'fight_id':event.fight_id,
                'revision':1,'last_sequence':1,'phase':'IN_FIGHT','turn_owner_id':None,
                'actors':{},'authority':'SYNTHETIC_FIXTURE_ONLY','actionable':False}
    if current.get('schema')!=1 or current.get('authority')!='SYNTHETIC_FIXTURE_ONLY' or current.get('actionable') is not False:
        raise StateTransitionError('STATE_PRIOR_PROJECTION_INVALID')
    if (event.session_id,event.account_id,event.account_generation)!=(current['session_id'],current['account_id'],current['account_generation']):
        raise StateTransitionError('STATE_ACCOUNT_GENERATION_MISMATCH')
    if event.sequence!=current['last_sequence']+1:raise StateTransitionError('STATE_SEQUENCE_GAP_OR_REORDER')
    if event.kind=='FIGHT_STARTED':
        if current['phase']!='ENDED' or event.fight_id==current['fight_id']:
            raise StateTransitionError('STATE_FIGHT_BOUNDARY_INVALID')
        current.update(fight_id=event.fight_id,phase='IN_FIGHT',turn_owner_id=None,actors={})
    else:
        if event.fight_id!=current['fight_id']:raise StateTransitionError('STATE_FIGHT_EPOCH_MISMATCH')
        if current['phase']!='IN_FIGHT':raise StateTransitionError('STATE_FIGHT_NOT_ACTIVE')
        k=event.kind;a=str(event.actor_id)
        if k=='ACTOR_SEEN':
            current['actors'].setdefault(a,{'cell_id':None,'hp':None,'max_hp':None,'AP':None,'MP':None,'RANGE':None,'cooldowns':None})
        elif k in ('ACTOR_RESOURCE_SET','ACTOR_HP_SET','ACTOR_POSITION_SET','ACTOR_COOLDOWNS_SET'):
            if a not in current['actors']:raise StateTransitionError('STATE_ACTOR_UNKNOWN')
            actor=current['actors'][a]
            if k=='ACTOR_RESOURCE_SET':actor[event.resource]=event.value
            if k=='ACTOR_HP_SET':actor.update(hp=event.value,max_hp=event.maximum)
            if k=='ACTOR_POSITION_SET':actor['cell_id']=event.value
            if k=='ACTOR_COOLDOWNS_SET':actor['cooldowns']=[[s,t] for s,t in sorted(event.cooldowns)]
        elif k=='TURN_STARTED':
            if a not in current['actors'] or current['turn_owner_id'] is not None:
                raise StateTransitionError('STATE_TURN_START_INVALID')
            current['turn_owner_id']=event.actor_id
        elif k=='TURN_ENDED':
            if current['turn_owner_id'] is None:raise StateTransitionError('STATE_TURN_END_WITHOUT_OWNER')
            if current['turn_owner_id'] != event.actor_id:raise StateTransitionError('STATE_TURN_END_OWNER_MISMATCH')
            current['turn_owner_id']=None
        elif k=='FIGHT_ENDED':
            if current['turn_owner_id'] is not None:raise StateTransitionError('STATE_FIGHT_END_WITH_TURN_OWNER')
            current['phase']='ENDED'
        else:raise StateTransitionError('STATE_KIND_UNKNOWN')
    current['revision']+=1
    current['last_sequence']=event.sequence
    current['actionable']=False
    return current


def summarize_snapshot(state:dict|None)->dict:
    if state is None:return {'status':'NO_STATE','actionable':False}
    actors=state['actors']
    missing={id:[k for k in ('hp','max_hp','AP','MP','cell_id') if info[k] is None] for id,info in actors.items()}
    return {'status':'SIMULATED_ONLY','revision':state['revision'],'fight_id':state['fight_id'],
            'phase':state['phase'],'turn_owner_id':state['turn_owner_id'],
            'actors':len(actors),'missing_fields_by_actor':missing,
            'actionable':False}
