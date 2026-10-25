"""P19 fixture composition and GPT-friendly diagnostic output, no physical IO."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from anka_contracts.execution_flow import OfflineActionIntent
from anka_contracts.execution_simulation import OfflineWindowObservation
from anka_execution.ledger import OfflineExecutionLedger, ExecutionLedgerRejected
from anka_execution.offline_dispatch import OfflineDispatchCoordinator
from anka_execution.fake_input import OfflineFakeInputDriver, OfflineWindowFeed, OfflineDriverFailure
from anka_app.execution_offline import fixture_intent, fixture_evidence

SCENARIOS = (
    'confirmed-fixture', 'no-confirmation', 'focus-lost', 'generation-changed',
    'character-unverified', 'calibration-unverified', 'no-input', 'driver-raises-before',
    'driver-raises-after', 'crash-after-prepare', 'crash-after-boundary',
    'crash-after-fake-attempt', 'wrong-evidence', 'second-account-contention',
    'restart-no-retry',
)


def _scenario(ledger: OfflineExecutionLedger, scenario: str) -> dict:
    intent = fixture_intent('p19-fixture-action-1')
    initial = OfflineWindowObservation(intent.account_id,intent.client_id,
                                        intent.window_generation,True,True,True)
    following = initial
    driver_mode = 'simulated-input'
    fault = None
    evidence = None
    if scenario == 'confirmed-fixture':
        evidence = fixture_evidence(intent,evidence_id='p19-outcome-1')
    elif scenario == 'wrong-evidence':
        evidence = replace(fixture_evidence(intent,evidence_id='p19-outcome-1'),account_id='enu')
    elif scenario == 'focus-lost':
        following = replace(initial,foreground_verified=False)
    elif scenario == 'generation-changed':
        following = replace(initial,window_generation=2)
    elif scenario == 'character-unverified':
        initial = replace(initial,character_verified=False)
    elif scenario == 'calibration-unverified':
        initial = replace(initial,calibration_verified=False)
    elif scenario == 'no-input':
        driver_mode = 'no-input'
    elif scenario == 'driver-raises-before':
        driver_mode = 'raise-before'
    elif scenario == 'driver-raises-after':
        driver_mode = 'raise-after'
    elif scenario == 'crash-after-prepare':
        fault = 'after_prepared'
    elif scenario == 'crash-after-boundary':
        fault = 'after_boundary'
    elif scenario == 'crash-after-fake-attempt':
        fault = 'after_fake_attempt'
    driver = OfflineFakeInputDriver(driver_mode)
    runtime = OfflineDispatchCoordinator(ledger,driver,OfflineWindowFeed(initial,following))
    error = None
    report = None
    try:
        report = runtime.run(intent,evidence=evidence,fault_point=fault)
    except Exception as exc:
        # Record failure while preserving the actual persisted ledger state.
        error = str(exc) if isinstance(exc,(ValueError,RuntimeError)) else type(exc).__name__.upper()
    if scenario in ('second-account-contention', 'restart-no-retry'):
        other=replace(intent,action_id='p19-fixture-action-2',action_key='next-action',
                      account_id='enu',client_id='window-2',window_generation=2,actor_id=888)
        win2=OfflineWindowObservation('enu','window-2',2,True,True,True)
        restarted=OfflineExecutionLedger(ledger.path) if scenario=='restart-no-retry' else ledger
        second_runtime=OfflineDispatchCoordinator(restarted,OfflineFakeInputDriver(),
                                                  OfflineWindowFeed(win2,win2))
        # Exercise actual P19 orchestration, not just the P18 ledger primitive.
        try:
            second=second_runtime.run(other)
            error=second.reason
        except ExecutionLedgerRejected as exc:
            error=str(exc)
        if scenario=='restart-no-retry':
            try:
                OfflineDispatchCoordinator(OfflineExecutionLedger(ledger.path),
                     OfflineFakeInputDriver(),OfflineWindowFeed(initial,initial)).run(intent)
                error='P19_DUPLICATE_NOT_DETECTED'
            except ExecutionLedgerRejected as exc:
                error=error+'+'+str(exc)
    audits=ledger.audit_all()
    unresolved=[a.action_id for a in audits if a.status=='DISPATCH_UNCERTAIN']
    result={'operation':'execution-sim-demo','scenario':scenario,
            'status':'BLOCKED_UNCERTAIN' if unresolved else 'RESEARCH_ONLY',
            'actions':[a.to_dict() for a in audits],
            'dispatch_report':report.to_dict() if report else None,
            'driver_invocations':driver.attempt_count,
            'observed_error':error,
            'first_failure_boundary':('execution.preflight' if report and report.boundary=='PRE_DISPATCH' else
                                      'execution.dispatch_or_settlement' if unresolved else 'none'),
            'uncertain_action_ids':unresolved,
            'synthetic_only':True,'physical_input_sent':False,'live_ready':False}
    return result


def execution_sim_demo(*, observer=None, scenario: str='no-confirmation') -> dict:
    if scenario not in SCENARIOS: raise ValueError('P19_DEMO_SCENARIO_INVALID')
    if observer is None:
        with TemporaryDirectory(prefix='anka-p19-') as tmp:
            return _scenario(OfflineExecutionLedger(Path(tmp)/'actions.sqlite3'),scenario)
    journal=observer.folder/'p19_simulated_driver.sqlite3'
    result=_scenario(OfflineExecutionLedger(journal),scenario)
    result['journal_path']=str(journal)
    try:
        observer.record('execution.p19_simulation_completed',boundary='execution.fake_driver',
            severity='ERROR' if result['status']=='BLOCKED_UNCERTAIN' else 'INFO',
            payload={'scenario':scenario,'status':result['status'],
                     'driver_invocations':result['driver_invocations'],
                     'observed_error':result['observed_error'],
                     'first_failure_boundary':result['first_failure_boundary'],
                     'failure_reason':(result['dispatch_report']['reason'] if result['dispatch_report']
                                       else result['observed_error']),
                     'uncertain_action_ids':result['uncertain_action_ids'],
                     'actions':[{'id':a['action_id'],'status':a['status'],
                                 'event_count':a['event_count']} for a in result['actions']],
                     'physical_input_sent':False})
        if result['status']=='BLOCKED_UNCERTAIN':
            bundle=observer.export_incident('P19_UNCERTAIN_FAKE_DISPATCH',
                boundary='execution.fake_driver',
                detail='Offline fake driver: unresolved dispatch. No physical IO. Do not retry an uncertain action.')
            result['incident_bundle']=str(bundle)
    except Exception:
        result['incident_bundle']='UNAVAILABLE_OBSERVABILITY_FAILURE'
    return result
