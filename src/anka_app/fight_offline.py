"""P11 composition root for immutable multi-session synthetic diagnostics.

It is the only module that joins Canonical storage, Live State traces, and
Coordination inspection. No code path promotes these fixtures to live control.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from anka_contracts.state import OfflineStateEvent
from anka_contracts.fight_audit import AccountExpectation
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event
from anka_live_state.fight_trace import trace_fight_events
from anka_coordination.fight_audit import compare_fight_views


def _run_audit(journal:SQLiteFixtureJournal,expected:tuple[AccountExpectation,...])->dict:
    evidence=journal.audited_evidence(tuple(e.session_id for e in expected))
    views={}
    for name,item in evidence['views'].items():
        views[name]={'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
    result=compare_fight_views(expected,views,same_database_snapshot=True)
    return {'operation':'fight-audit','status':result.status,'fight':result.to_dict(),
            'journal':evidence['audit'],'live_ready':False,'physical_input_sent':False}


def fight_audit(path:Path,expected:tuple[AccountExpectation,...],*,observer=None)->dict:
    if not isinstance(path,Path):path=Path(path)
    with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as journal:
        result=_run_audit(journal,expected)
    if observer is not None:
        try:
            observer.record('coordination.synthetic_fight_audited',boundary='coordination.observational_reconciliation',
                payload={'status':result['status'],'reasons':result['fight']['reasons'],
                         'accounts':len(expected),'actionable':False})
            if result['status']=='BLOCKED_INCONSISTENT':
                artifact=observer.export_incident('SYNTHETIC_FIGHT_EVIDENCE_INCONSISTENT',
                    boundary='coordination.observational_reconciliation',
                    detail='Read-only synthetic fight audit found inconsistent or missing evidence. No physical input occurred.')
                result['incident_bundle']=str(artifact)
        except Exception:
            # Diagnostics is passive. The audit result remains meaningful even
            # if the local incident storage has failed or filled up.
            result['incident_bundle']='UNAVAILABLE_DIAGNOSTICS_SINK_FAILURE'
    return result


def fight_demo(*,observer=None)->dict:
    expected=(AccountExpectation('cra-session','cra',1,777),
              AccountExpectation('enu-session','enu',1,888))
    with TemporaryDirectory(prefix='anka-p11-fight-') as tmp:
        with SQLiteFixtureJournal(Path(tmp)/'fixture.sqlite3',reducer=apply_offline_event) as j:
            for session,account,local in (('cra-session','cra',777),('enu-session','enu',888)):
                events=[('FIGHT_STARTED',{}),('ACTOR_SEEN',{'actor_id':777}),
                        ('ACTOR_SEEN',{'actor_id':888}),('ACTOR_HP_SET',{'actor_id':local,'value':2800,'maximum':3200}),
                        ('ACTOR_RESOURCE_SET',{'actor_id':local,'resource':'AP','value':11}),
                        ('ACTOR_RESOURCE_SET',{'actor_id':local,'resource':'MP','value':5}),
                        ('TURN_STARTED',{'actor_id':777})]
                for n,(kind,kwargs) in enumerate(events,1):
                    j.append_fixture(OfflineStateEvent(f'{account}-{n}',session,account,1,'same-fight',n,kind,**kwargs))
            aligned=_run_audit(j,expected)
            # Only ENU's observer advances to a new turn. The inconsistency
            # must remain visible; never "recover" by voting or choosing one.
            j.append_fixture(OfflineStateEvent('enu-8','enu-session','enu',1,'same-fight',8,
                                                'TURN_ENDED',actor_id=777))
            j.append_fixture(OfflineStateEvent('enu-9','enu-session','enu',1,'same-fight',9,
                                                'TURN_STARTED',actor_id=888))
            conflict=_run_audit(j,expected)
    bundle=None
    if observer is not None:
        try:
            observer.record('coordination.synthetic_handoff_checked',boundary='coordination.observational_reconciliation',
                payload={'aligned_status':aligned['status'],'divergence_status':conflict['status'],
                         'failure_reasons':conflict['fight']['reasons'],'actionable':False})
            artifact=observer.export_incident('SYNTHETIC_TURN_OWNER_CONFLICT',
                boundary='coordination.observational_reconciliation',
                detail='Synthetic CRA/ENU handoff fixture: the two observers report incompatible turn owners. No live game interaction occurred.')
            bundle=str(artifact)
        except Exception:
            bundle='UNAVAILABLE_DIAGNOSTICS_SINK_FAILURE'
    return {'operation':'fight-demo','status':'SYNTHETIC_DIAGNOSTIC_ONLY',
            'aligned':aligned,'divergent_handoff':conflict,'incident_bundle':bundle,
            'live_ready':False,'physical_input_sent':False}


def parse_expectations(items:list[str])->tuple[AccountExpectation,...]:
    if not 1<=len(items)<=8:raise ValueError('FIGHT_AUDIT_EXPECTATIONS_REQUIRED')
    result=[]
    for item in items:
        fields=item.split(':')
        if len(fields)!=4:raise ValueError('FIGHT_AUDIT_EXPECTATION_FORMAT')
        try:
            generation=int(fields[2]);actor=int(fields[3])
        except ValueError as e:raise ValueError('FIGHT_AUDIT_EXPECTATION_FORMAT') from e
        result.append(AccountExpectation(fields[0],fields[1],generation,actor))
    return tuple(result)
