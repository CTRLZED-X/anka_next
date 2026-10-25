"""P18 app-level composition: synthetic fixtures only, no game input."""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from anka_contracts.execution_flow import OfflineActionIntent, OfflineOutcomeEvidence
from anka_execution.ledger import OfflineExecutionLedger,ExecutionLedgerRejected
from anka_execution.settlement import ExecutionTransitionRejected


def fixture_intent(action_id: str = 'p18-fixture-action-1') -> OfflineActionIntent:
    return OfflineActionIntent(action_id=action_id, action_key='turn1-end',session_id='synthetic-session',
        account_id='cra',client_id='window-1',window_generation=1,fight_id='synthetic-fight',
        turn_id='turn-1',actor_id=777,state_revision=7,kind='END_TURN')


def fixture_evidence(intent: OfflineActionIntent, outcome: str = 'ACCEPTED', *, evidence_id='p18-fixture-evidence-1') -> OfflineOutcomeEvidence:
    return OfflineOutcomeEvidence(evidence_id=evidence_id,action_id=intent.action_id,
        session_id=intent.session_id,account_id=intent.account_id,client_id=intent.client_id,
        window_generation=intent.window_generation,fight_id=intent.fight_id,
        turn_id=intent.turn_id,actor_id=intent.actor_id,observed_revision=intent.state_revision+1,
        outcome=outcome)


def _demo(ledger: OfflineExecutionLedger, scenario: str) -> dict:
    intent=fixture_intent()
    ledger.prepare(intent)
    issue=None
    if scenario=='cancelled':
        ledger.cancel_before_dispatch(intent.action_id)
    else:
        ledger.mark_dispatch_boundary(intent.action_id)
        if scenario=='accepted-fixture':
            ledger.record_outcome(fixture_evidence(intent))
        elif scenario=='rejected-fixture':
            ledger.record_outcome(fixture_evidence(intent,'REJECTED'))
        elif scenario=='inconclusive':
            ledger.record_outcome(fixture_evidence(intent,'INCONCLUSIVE'))
        elif scenario=='duplicate-dispatch':
            try:ledger.mark_dispatch_boundary(intent.action_id)
            except (ExecutionLedgerRejected, ExecutionTransitionRejected) as exc:issue=str(exc)
        elif scenario=='wrong-evidence':
            from dataclasses import replace
            try:ledger.record_outcome(replace(fixture_evidence(intent),account_id='enu'))
            except (ExecutionLedgerRejected, ExecutionTransitionRejected) as exc:issue=str(exc)
    result=ledger.audit_all()[0].to_dict()
    status='BLOCKED_UNCERTAIN' if result['status']=='DISPATCH_UNCERTAIN' else 'RESEARCH_ONLY'
    return {'operation':'execution-demo','scenario':scenario,'status':status,'action':result,
            'rejection_code':issue,'physical_input_sent':False,'live_ready':False}


def execution_demo(*, observer=None, scenario='uncertain-crash') -> dict:
    cases=('accepted-fixture','rejected-fixture','uncertain-crash','inconclusive',
           'duplicate-dispatch','wrong-evidence','cancelled')
    if scenario not in cases:
        raise ExecutionLedgerRejected('P18_DEMO_SCENARIO_INVALID')
    # Keep a diagnostic journal under the run evidence directory when available.
    if observer is None:
        with TemporaryDirectory(prefix='anka-p18-') as folder:
            result=_demo(OfflineExecutionLedger(Path(folder)/'actions.sqlite3'),scenario)
    else:
        journal=observer.folder/'p18_synthetic_action_ledger.sqlite3'
        result=_demo(OfflineExecutionLedger(journal),scenario)
        result['journal_path']=str(journal)
        try:
            observer.record('execution.synthetic_ledger_audited',boundary='execution.offline_settlement',
                payload={'scenario':scenario,'status':result['status'],
                         'action_status':result['action']['status'],
                         'rejection_code':result['rejection_code'], 'action_id':result['action']['action_id'],
                         'event_count':result['action']['event_count'],
                         'evidence_ids':result['action']['evidence_ids'],
                         'reason':result['action']['reason'], 'physical_input_sent':False})
            if result['status']=='BLOCKED_UNCERTAIN':
                bundle=observer.export_incident('P18_UNCERTAIN_SEND_NO_RETRY',
                    boundary='execution.offline_settlement',
                    detail='Synthetic dispatch boundary recorded, no physical input emitted; cannot automatically retry.')
                result['incident_bundle']=str(bundle)
        except Exception:result['incident_bundle']='UNAVAILABLE_OBSERVABILITY_FAILURE'
    return result


def execution_audit(path: Path, *, observer=None) -> dict:
    ledger=OfflineExecutionLedger(path,read_only=True)
    reports=ledger.audit_all()
    uncertain=[r.action_id for r in reports if r.status=='DISPATCH_UNCERTAIN']
    result={'operation':'execution-audit','status':'BLOCKED_UNCERTAIN' if uncertain else 'RESEARCH_ONLY',
            'actions':[r.to_dict() for r in reports], 'uncertain_action_ids':uncertain,
            'synthetic_only':True,'live_ready':False,'physical_input_sent':False}
    if observer is not None:
        try:
            observer.record('execution.synthetic_audit_completed',boundary='execution.offline_audit',
                payload={'total_actions':len(reports),'uncertain_count':len(uncertain),
                         'uncertain_action_ids':uncertain,'status':result['status']})
            if uncertain:
                artifact=observer.export_incident('P18_UNCERTAIN_SEND_NO_RETRY',boundary='execution.offline_audit',
                    detail='Offline journal contains uncertain fixture intents; no automatic retry is safe.')
                result['incident_bundle']=str(artifact)
        except Exception:result['incident_bundle']='UNAVAILABLE_OBSERVABILITY_FAILURE'
    return result
