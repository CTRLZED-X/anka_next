"""P17 standalone synthetic coordination/workflow composition and evidence export."""
from __future__ import annotations
from anka_contracts.coordination_flow import PartyMember,PartyFixtureEvent
from anka_contracts.workflow_flow import SyntheticFightOutcome
from anka_coordination.party_lifecycle import replay_party
from anka_workflow.mission_research import evaluate_mission


def _member(account: str, actor: int, role: str) -> PartyMember:
    return PartyMember(account, 1, actor, role)


def _ev(seq: int, kind: str, account: str | None = None, *, fight='synthetic-fight-1', tick: int | None = None) -> PartyFixtureEvent:
    details = {'cra': (1,777), 'enu': (1,888)}
    kw = {'account_id': account, 'generation': details[account][0], 'actor_id': details[account][1]} if account else {}
    if kind in ('FIGHT_STARTED','TURN_STARTED','END_TURN_INTENDED','TURN_ENDED','FIGHT_ENDED'):
        kw['fight_id'] = fight
    return PartyFixtureEvent(seq, seq if tick is None else tick, kind, f'fixture-event-{seq}', **kw)


def coordination_demo(*, observer=None, scenario: str = 'handoff') -> dict:
    if scenario not in ('handoff','missing-end-confirmation','overlapping-owner','missing-next-owner','fight-without-win'):
        raise ValueError('P17_SCENARIO_INVALID')
    members = (_member('cra',777,'leader'),_member('enu',888,'follower'))
    history = [_ev(1,'READY','cra'),_ev(2,'READY','enu'),_ev(3,'FIGHT_STARTED'),
               _ev(4,'TURN_STARTED','cra'),_ev(5,'END_TURN_INTENDED','cra')]
    if scenario == 'overlapping-owner':
        history.append(_ev(6,'TURN_STARTED','enu'))
    elif scenario == 'missing-end-confirmation':
        history.append(_ev(6,'CHECK',tick=10))
    else:
        history.append(_ev(6,'TURN_ENDED','cra'))
        if scenario == 'missing-next-owner':
            history.append(_ev(7,'CHECK',tick=12))
        else:
            history.extend([_ev(7,'TURN_STARTED','enu'),_ev(8,'FIGHT_ENDED')])
    party = replay_party(members,tuple(history))
    outcome = (SyntheticFightOutcome('synthetic-fight-1','VICTORY','synthetic-outcome-1'),) if scenario=='handoff' else ()
    mission = evaluate_mission((party,),outcome,target_wins=1)
    if observer is not None:
        try:
            observer.record('coordination.synthetic_lifecycle_checked',boundary='coordination.synthetic_lifecycle',
                            payload={'scenario':scenario,'status':party.status,'first_failed_sequence':party.first_failed_sequence,
                                     'reasons':party.reasons,'mission_status':mission.status,'physical_input_sent':False})
            if party.status=='QUARANTINED':
                artifact=observer.export_incident(party.reasons[0],boundary='coordination.synthetic_lifecycle',
                    detail='Synthetic first-failure boundary: '+party.reasons[0]+'; no input was sent.')
            else: artifact=None
        except Exception:
            artifact='UNAVAILABLE_DIAGNOSTICS_SINK_FAILURE'
    else: artifact=None
    return {'operation':'coordination-demo','status':party.status, 'scenario':scenario,
            'coordination':party.to_dict(),'mission':mission.to_dict(),
            'incident_bundle':str(artifact) if artifact is not None else None,
            'synthetic_fixture':True,'live_ready':False,'physical_input_sent':False}
