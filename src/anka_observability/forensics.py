"""Passive causal analysis over already-recorded diagnostic events.

The analyzer never reads or mutates gameplay state and never grants authority.  It
only compares observed evidence against an explicit expected boundary chain.
"""
from __future__ import annotations
from dataclasses import dataclass
from uuid import uuid4
from typing import Iterable

from anka_contracts.diagnostics import (
    BoundaryExpectation, DiagnosticEvent, DiagnosticFinding, OperationTraceSpec,
)

SECTION_BY_OWNER = {
    'anka_capture': 'capture',
    'anka_protocol': 'protocol',
    'anka_canonical': 'canonical',
    'anka_live_state': 'live_state',
    'anka_coordination': 'coordination',
    'anka_decision': 'decision',
    'anka_execution': 'execution',
    'anka_workflow': 'workflow',
    'anka_client': 'identity',
    'anka_observability': 'observability',
    'anka_app': 'bootstrap',
}

TERMINAL_SEVERITIES = frozenset({'ERROR','CRITICAL','SAFETY'})


def _as_event(obj: DiagnosticEvent | dict) -> DiagnosticEvent:
    return obj if isinstance(obj, DiagnosticEvent) else DiagnosticEvent.from_dict(obj)


def evidence_matrix(events: Iterable[DiagnosticEvent | dict], *, dropped: int = 0,
                    observer_errors: Iterable[str] = ()) -> dict[str, str]:
    """Infer only which diagnostic sections have actual recorded evidence.

    PRESENT means the observer has at least one event from that owner/section; it
    does *not* mean the underlying gameplay fact is authoritative.
    """
    sections = {
        'bootstrap':'MISSING','configuration':'MISSING','identity':'MISSING',
        'capture':'MISSING','protocol':'MISSING','canonical':'MISSING',
        'live_state':'MISSING','coordination':'MISSING','decision':'MISSING',
        'execution':'MISSING','outcome':'MISSING','workflow':'MISSING',
        'observability':'PRESENT',
    }
    for raw in events:
        event = _as_event(raw)
        section = SECTION_BY_OWNER.get(event.owner_system or '')
        if section:
            sections[section] = 'PRESENT'
        name = event.event_name
        if name.startswith('setup.') or name.startswith('start.') or name.startswith('bootstrap.'):
            sections['bootstrap'] = 'PRESENT'
        if name.startswith('config.') or name.startswith('configuration.'):
            sections['configuration'] = 'PRESENT'
        if name.startswith('client.'):
            # A client diagnostic event proves that identity work was observed,
            # not that identity itself was established.  The read-only client
            # inspection publishes per-account binding states; any BLOCKED/PENDING
            # or scan error must remain PARTIAL so incident bundles cannot turn
            # "we inspected identity" into "identity is proven".
            states = event.payload.get('account_states')
            scan_errors = event.payload.get('scan_errors')
            if isinstance(states, (list, tuple)):
                complete = bool(states) and all(x == 'IDENTITY_MATCHED' for x in states) and not scan_errors
                if complete:
                    if sections['identity'] == 'MISSING':
                        sections['identity'] = 'PRESENT'
                else:
                    sections['identity'] = 'PARTIAL'
            elif event.payload.get('reasons') or scan_errors:
                sections['identity'] = 'PARTIAL'
            elif sections['identity'] == 'MISSING':
                sections['identity'] = 'PRESENT'
        if name.startswith('execution.outcome') or name.startswith('outcome.') or event.severity == 'SETTLEMENT':
            sections['outcome'] = 'PRESENT'
    if dropped:
        sections['observability'] = 'PARTIAL'
    if tuple(observer_errors):
        sections['observability'] = 'PARTIAL'
    return sections


@dataclass(frozen=True, slots=True)
class TraceAnalysis:
    operation: str
    finding: DiagnosticFinding | None
    boundary_graph: tuple[dict, ...]
    matched_event_ids: tuple[str, ...]


class FirstDivergenceAnalyzer:
    """Find the earliest missing/contradictory edge in a declared operation trace.

    When a trace declares correlation keys, an event from another account/action/
    batch cannot satisfy a later edge merely because its semantic name matches.
    """

    @staticmethod
    def _correlation_value(event: DiagnosticEvent, key: str):
        if key.startswith('payload.'):
            return event.payload.get(key.split('.',1)[1])
        return getattr(event,key,None)

    def analyze(self, spec: OperationTraceSpec, events: Iterable[DiagnosticEvent | dict], *,
                fallback_failure_code: str = 'EVIDENCE_GAP',
                control_state: str = 'UNKNOWN') -> TraceAnalysis:
        ordered = sorted((_as_event(e) for e in events), key=lambda e: (e.producer_seq, e.monotonic_ns, e.event_id))
        cursor = 0
        matched: list[str] = []
        graph: list[dict] = []
        first_failure: DiagnosticFinding | None = None
        correlation: dict[str, object] = {}

        def compatible(event: DiagnosticEvent) -> bool:
            for key,value in correlation.items():
                if self._correlation_value(event,key) != value:
                    return False
            return True

        for expectation in spec.expectations:
            match_index = None
            for idx in range(cursor, len(ordered)):
                event = ordered[idx]
                if (event.event_name == expectation.event_name
                        and event.owner_system == expectation.owner_system
                        and event.boundary == expectation.boundary
                        and compatible(event)):
                    match_index = idx
                    break
            if match_index is not None:
                event = ordered[match_index]
                for key in spec.correlation_keys:
                    value=self._correlation_value(event,key)
                    if key not in correlation and value is not None:
                        correlation[key]=value
                matched.append(event.event_id)
                graph.append({
                    'event_name': expectation.event_name,'boundary': expectation.boundary,
                    'owner_system': expectation.owner_system,'status': 'OBSERVED',
                    'event_id': event.event_id,'correlation':dict(correlation),
                })
                cursor = match_index + 1
                continue

            failures = [e for e in ordered[cursor:] if e.severity in TERMINAL_SEVERITIES and compatible(e)]
            same_boundary = [e for e in failures if e.boundary == expectation.boundary]
            support = same_boundary or failures[:3]
            codes = tuple(dict.fromkeys(e.failure_code for e in support if e.failure_code))
            failure_code = (same_boundary[0].failure_code if same_boundary and same_boundary[0].failure_code else fallback_failure_code)
            confidence = 'HIGH' if same_boundary else ('MEDIUM' if failures else 'UNDETERMINED')
            graph.append({
                'event_name': expectation.event_name,'boundary': expectation.boundary,
                'owner_system': expectation.owner_system,'status': 'MISSING','event_id': None,
                'correlation':dict(correlation),
            })
            for later in spec.expectations[len(graph):]:
                graph.append({'event_name':later.event_name,'boundary':later.boundary,'owner_system':later.owner_system,
                              'status':'NOT_REACHED','event_id':None,'correlation':dict(correlation)})
            first_failure = DiagnosticFinding(
                finding_id='finding-'+uuid4().hex,failure_code=failure_code,
                first_divergent_boundary=expectation.boundary,suspected_owner=expectation.owner_system,
                confidence=confidence,supporting_evidence_ids=tuple(e.event_id for e in support),
                contradicting_evidence_ids=(),missing_evidence=(expectation.event_name,),
                control_state=control_state,
                recommended_next_test=f'Collect authoritative evidence for {expectation.event_name} at {expectation.boundary} using correlation {correlation or "unbound"}.',
                candidate_causes=codes,
            )
            break

        return TraceAnalysis(spec.operation, first_failure, tuple(graph), tuple(matched))



def action_lifecycle_report(events: Iterable[DiagnosticEvent | dict], *, limit: int = 32) -> dict:
    """Build a bounded per-action forensic view without claiming causation.

    The report answers the practical postmortem questions that matter most:
    was there a plan, was it authorized, did Execution cross the input boundary,
    did the durable outcome settle, and what Protocol/Canonical/Live-State evidence
    appeared nearby for the same account/fight.  Nearby semantic evidence is
    explicitly contextual only; it is never promoted into an action outcome proof.
    """
    ordered=sorted((_as_event(e) for e in events),key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
    by_action:dict[str,list[DiagnosticEvent]]={}
    for e in ordered:
        if isinstance(e.action_id,str) and e.action_id.startswith('action-'):
            by_action.setdefault(e.action_id,[]).append(e)
    all_ordered_actions=sorted(by_action.items(),key=lambda kv:max(e.producer_seq for e in kv[1]))
    limit=max(1,limit)

    def priority_action(items:list[DiagnosticEvent])->bool:
        settled=any(e.event_name=='execution.outcome_settled' for e in items)
        crossed_send=any(e.event_name in ('execution.send_started','execution.input_sent','execution.input_may_have_sent','execution.exception_after_send_started') for e in items)
        explicit_risk=any(e.severity in TERMINAL_SEVERITIES or e.failure_code or e.physical_input_state=='MAY_HAVE_SENT'
                          or e.event_name=='execution.outcome_terminal_unresolved' for e in items)
        return explicit_risk or (crossed_send and not settled)

    priority_actions=[row for row in all_ordered_actions if priority_action(row[1])]
    selected_ids:set[str]=set()
    if len(priority_actions)<=limit:
        selected_ids.update(action_id for action_id,_ in priority_actions)
    else:
        # When even the bounded priority lane is saturated, preserve both the
        # earliest anomalies (possible root divergence) and the latest anomalies
        # (current terminal state) instead of blindly keeping one end only.
        first_count=max(1,limit//2)
        for action_id,_ in priority_actions[:first_count]:selected_ids.add(action_id)
        for action_id,_ in priority_actions[-(limit-first_count):]:selected_ids.add(action_id)
    for action_id,_ in reversed(all_ordered_actions):
        if len(selected_ids)>=limit:break
        selected_ids.add(action_id)
    ordered_actions=[row for row in all_ordered_actions if row[0] in selected_ids]
    total_action_count=len(all_ordered_actions)
    priority_action_count=len(priority_actions)
    included_priority_count=sum(1 for action_id,_ in priority_actions if action_id in selected_ids)
    rows=[]
    for action_id,items in ordered_actions:
        items=sorted(items,key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
        request=next((e for e in items if e.event_name=='workflow.action_requested'),None)
        account=(request.account_id if request else next((e.account_id for e in items if e.account_id),None))
        fight_epoch=(request.fight_epoch if request else next((e.fight_epoch for e in items if e.fight_epoch is not None),None))
        turn_epoch=(request.turn_epoch if request else next((e.turn_epoch for e in items if e.turn_epoch is not None),None))
        scope=(request.payload.get('scope') if request else None)
        kind=(request.payload.get('kind') if request else None)
        plan_id=(request.payload.get('plan_id') if request else None)
        trace_id=(request.trace_id if request else next((e.trace_id for e in items if e.trace_id),None))
        decision=None
        if plan_id is not None and request is not None:
            decision=next((e for e in reversed(ordered) if e.producer_seq<=request.producer_seq
                           and e.event_name=='decision.plan_result' and e.account_id==account
                           and e.payload.get('plan_id')==plan_id),None)
        admissions=[e for e in items if e.event_name=='execution.admitted']
        starts=[e for e in items if e.event_name=='execution.send_started']
        pre_send_terminal_events=[e for e in items if e.event_name in (
            'execution.rejected','execution.ledger_prepare_rejected','execution.input_lease_rejected',
            'execution.final_guard_rejected','execution.exception_before_send')]
        if not starts:
            pre_send_terminal_events.extend(e for e in items if e.event_name=='execution.safety_fault'
                                            and e.boundary=='execution.input_arbitration'
                                            and e.physical_input_state!='MAY_HAVE_SENT')
        send_results=[e for e in items if e.event_name in ('execution.input_sent','execution.input_not_sent','execution.input_may_have_sent','execution.exception_after_send_started')]
        settlements=[e for e in items if e.event_name=='execution.outcome_settled']
        terminal_unresolveds=[e for e in items if e.event_name=='execution.outcome_terminal_unresolved']
        admitted=admissions[0] if admissions else None
        started=starts[0] if starts else None
        pre_send_terminal=pre_send_terminal_events[-1] if pre_send_terminal_events else None
        sent=send_results[0] if send_results else None
        settled=settlements[-1] if settlements else None
        dispatch=next((e for e in reversed(items) if e.event_name=='workflow.action_dispatch_result'),None)
        conflicts=[]
        for e in items:
            if account is not None and e.account_id is not None and e.account_id!=account:conflicts.append(e.event_id+':ACCOUNT')
            if fight_epoch is not None and e.fight_epoch is not None and e.fight_epoch!=fight_epoch:conflicts.append(e.event_id+':FIGHT_EPOCH')
            if turn_epoch is not None and e.turn_epoch is not None and e.turn_epoch!=turn_epoch:conflicts.append(e.event_id+':TURN_EPOCH')
        terminal_unresolved=terminal_unresolveds[-1] if terminal_unresolveds else None
        may_have_sent=next((e for e in reversed(items) if e.physical_input_state=='MAY_HAVE_SENT'
                            or e.event_name in ('execution.input_may_have_sent','execution.exception_after_send_started')),None)
        lifecycle_anomalies=[]
        hard_conflicts=[]
        if len(admissions)>1:lifecycle_anomalies.append('MULTIPLE_EXECUTION_ADMISSIONS')
        if len(starts)>1:lifecycle_anomalies.append('MULTIPLE_SEND_STARTED')
        if len(send_results)>1:
            lifecycle_anomalies.append('MULTIPLE_SEND_RESULTS')
            if len({e.event_name for e in send_results})>1:hard_conflicts.append('CONFLICTING_SEND_RESULTS')
        if len(settlements)>1:lifecycle_anomalies.append('MULTIPLE_SETTLEMENTS')
        if len(terminal_unresolveds)>1:lifecycle_anomalies.append('MULTIPLE_TERMINAL_UNRESOLVED')
        if len(pre_send_terminal_events)>1:lifecycle_anomalies.append('MULTIPLE_PRE_SEND_TERMINALS')
        if pre_send_terminal_events and (starts or send_results):hard_conflicts.append('PRE_SEND_TERMINAL_WITH_SEND')
        # Missing earlier lifecycle edges are not themselves contradictions in a
        # bounded incident: the recorder may have omitted them. Only positive,
        # mutually incompatible included evidence is allowed to create a hard
        # contradiction classification.
        if settlements and terminal_unresolveds:hard_conflicts.append('CONFLICTING_TERMINAL_OUTCOMES')
        attempt_ids={e.attempt_id for e in starts+send_results+settlements+terminal_unresolveds if e.attempt_id is not None}
        if len(attempt_ids)>1:hard_conflicts.append('ATTEMPT_ID_CONFLICT')
        if conflicts:hard_conflicts.append('CORRELATION_CONFLICT')
        lifecycle_anomalies=sorted(dict.fromkeys(lifecycle_anomalies+hard_conflicts))
        hard_conflicts=sorted(dict.fromkeys(hard_conflicts))
        if hard_conflicts:state='CONTRADICTORY_EVIDENCE'
        elif settled is not None:state='SETTLED'
        elif terminal_unresolved is not None:state='TERMINAL_UNRESOLVED'
        elif may_have_sent is not None:state='MAY_HAVE_SENT_UNRESOLVED'
        elif sent is not None and sent.event_name=='execution.input_not_sent':state='NOT_SENT'
        elif sent is not None:state='SENT_AWAITING_OUTCOME'
        elif pre_send_terminal is not None:state='NOT_SENT'
        elif started is not None:state='SEND_STARTED_NO_FINAL_SEND_RECORD'
        elif admitted is not None:state='ADMITTED_NOT_SENT'
        else:state='REQUESTED_OR_PARTIAL'
        lower=(started.producer_seq if started else (admitted.producer_seq if admitted else items[0].producer_seq))
        if settled is not None:
            upper=settled.producer_seq;context_window_end='SETTLEMENT'
        else:
            next_request=next((e for e in ordered if e.producer_seq>items[-1].producer_seq
                               and e.event_name=='workflow.action_requested'
                               and (account is None or e.account_id==account)),None)
            if next_request is not None:
                upper=max(lower,next_request.producer_seq-1);context_window_end='NEXT_SAME_ACCOUNT_ACTION'
            else:
                upper=(ordered[-1].producer_seq if ordered else items[-1].producer_seq);context_window_end='INCIDENT_END'
        nearby=[]
        for e in ordered:
            if e.producer_seq<lower or e.producer_seq>upper:continue
            if e.owner_system not in ('anka_protocol','anka_canonical','anka_live_state'):continue
            if account is not None and e.account_id not in (None,account):continue
            if fight_epoch is not None and e.fight_epoch not in (None,fight_epoch):continue
            nearby.append({'event_id':e.event_id,'event_name':e.event_name,'owner_system':e.owner_system,
                           'boundary':e.boundary,'producer_seq':e.producer_seq,'evidence_class':e.evidence_class})
            if len(nearby)>=20:break
        pre_send_stage={
            'execution.rejected':'ADMISSION','execution.ledger_prepare_rejected':'DURABLE_PREPARE',
            'execution.input_lease_rejected':'INPUT_ARBITRATION','execution.final_guard_rejected':'FINAL_GUARD',
            'execution.exception_before_send':'EXCEPTION_BEFORE_SEND','execution.safety_fault':'INPUT_ARBITRATION',
        }.get(pre_send_terminal.event_name) if pre_send_terminal is not None else None
        rows.append({
            'action_id':action_id,'account_id':account,'fight_epoch':fight_epoch,'turn_epoch':turn_epoch,
            'trace_id':trace_id,'plan_id':plan_id,'decision_event_id':decision.event_id if decision else None,
            'scope':scope,'kind':kind,'state':state,'correlation_conflicts':conflicts,
            'lifecycle_anomalies':lifecycle_anomalies,
            'hard_conflicts':hard_conflicts,
            'attempt_ids':sorted(attempt_ids),
            'settlement_status':settled.payload.get('status') if settled else None,
            'settlement_reason':settled.payload.get('reason') if settled else None,
            'settlement_evidence_id':settled.payload.get('evidence_id') if settled else None,
            'not_sent_stage':pre_send_stage,
            'not_sent_event_id':pre_send_terminal.event_id if pre_send_terminal is not None else None,
            'not_sent_event_name':pre_send_terminal.event_name if pre_send_terminal is not None else None,
            'not_sent_boundary':pre_send_terminal.boundary if pre_send_terminal is not None else None,
            'not_sent_failure_code':pre_send_terminal.failure_code if pre_send_terminal is not None else None,
            'dispatch_outcome_status':dispatch.payload.get('outcome_status') if dispatch else None,
            'dispatch_outcome_reason':dispatch.payload.get('outcome_reason') if dispatch else None,
            'event_ids':[e.event_id for e in items],
            'physical_input_states':[e.physical_input_state for e in items if e.physical_input_state],
            'failure_codes':[e.failure_code for e in items if e.failure_code],
            'nearby_semantic_context':nearby,'semantic_context_window_end':context_window_end,
            'nearby_semantic_context_is_causal_proof':False,
        })
    # Pre-action causal index: Decision and authorization can terminate before
    # Workflow creates an action_id.  Without this lane, a "nothing happened"
    # incident can look like a missing action even when the planner deliberately
    # waited or Coordination denied the plan before Execution admission.
    pre_action_all=[]
    decision_results=[e for e in ordered if e.event_name=='decision.plan_result']
    for index,decision_event in enumerate(decision_results):
        disposition=decision_event.payload.get('disposition')
        disposition=disposition if isinstance(disposition,str) else 'UNKNOWN'
        plan_id=decision_event.payload.get('plan_id')
        plan_id=plan_id if isinstance(plan_id,str) else None

        # WorkflowTurnController handles one planner result synchronously. Bound
        # downstream matching to the next Decision result for the same account so
        # a later attempt cannot be borrowed to make this attempt look healthy.
        next_same_account_seq=None
        for later_decision in decision_results[index+1:]:
            if later_decision.account_id==decision_event.account_id:
                next_same_account_seq=later_decision.producer_seq
                break

        def same_attempt_window(event:DiagnosticEvent)->bool:
            if event.producer_seq<=decision_event.producer_seq:return False
            if next_same_account_seq is not None and event.producer_seq>=next_same_account_seq:return False
            if decision_event.account_id is not None and event.account_id not in (None,decision_event.account_id):return False
            if decision_event.fight_epoch is not None and event.fight_epoch not in (None,decision_event.fight_epoch):return False
            if decision_event.turn_epoch is not None and event.turn_epoch not in (None,decision_event.turn_epoch):return False
            return True

        downstream=None
        state=('DECISION_'+disposition if disposition in ('WAIT','NO_ACTION','FAULT') else 'DECISION_RESULT_UNKNOWN')
        if disposition=='PLAN':
            candidates=[]
            if plan_id is not None:
                for event in ordered:
                    if not same_attempt_window(event):continue
                    if event.event_name=='workflow.action_authorization_blocked' and event.payload.get('plan_id')==plan_id:
                        candidates.append(event)
                    elif event.event_name=='workflow.action_requested' and event.payload.get('plan_id')==plan_id:
                        candidates.append(event)
            if candidates:
                downstream=min(candidates,key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
                state=('AUTHORIZATION_BLOCKED' if downstream.event_name=='workflow.action_authorization_blocked'
                       else 'ACTION_REQUESTED')
            else:
                state='PLAN_WITHOUT_WORKFLOW_OUTCOME'

        reason=(downstream.payload.get('reason') if downstream is not None else decision_event.payload.get('reason'))
        if reason is None and downstream is not None:reason=downstream.failure_code
        downstream_payload=(downstream.payload if downstream is not None else {})
        event_ids=[decision_event.event_id]
        if downstream is not None:event_ids.append(downstream.event_id)
        required_evidence=decision_event.payload.get('required_evidence',[])
        if not isinstance(required_evidence,list):required_evidence=[]
        pre_action_all.append({
            'state':state,'account_id':decision_event.account_id,'fight_epoch':decision_event.fight_epoch,
            'turn_epoch':decision_event.turn_epoch,'frame_id':decision_event.payload.get('frame_id'),
            'plan_id':plan_id,'disposition':disposition,'reason':reason,
            'failure_code':(downstream.failure_code if downstream is not None else decision_event.failure_code),
            'scope':downstream_payload.get('scope'),'kind':downstream_payload.get('kind',decision_event.payload.get('kind')),
            'action_id':downstream.action_id if downstream is not None else None,
            'trace_id':downstream.trace_id if downstream is not None else None,
            'decision_event_id':decision_event.event_id,
            'downstream_event_id':downstream.event_id if downstream is not None else None,
            'required_evidence':list(required_evidence),'event_ids':event_ids,
            'producer_seq':decision_event.producer_seq,
        })

    # Failure/no-progress rows outrank routine ACTION_REQUESTED rows. Then fill
    # remaining capacity with the newest ordinary attempts. Omissions are explicit.
    selected_pre=[]
    selected_pre_ids=set()
    for row in reversed([x for x in pre_action_all if x['state']!='ACTION_REQUESTED']):
        if len(selected_pre)>=limit:break
        selected_pre.append(row);selected_pre_ids.add(row['decision_event_id'])
    for row in reversed(pre_action_all):
        if len(selected_pre)>=limit:break
        if row['decision_event_id'] in selected_pre_ids:continue
        selected_pre.append(row);selected_pre_ids.add(row['decision_event_id'])
    pre_action_outcomes=sorted(selected_pre,key=lambda row:(row['producer_seq'],row['decision_event_id']))

    blockers=[]
    for e in ordered:
        if e.event_name=='workflow.action_authorization_blocked':
            blockers.append({'event_id':e.event_id,'account_id':e.account_id,'fight_epoch':e.fight_epoch,
                             'turn_epoch':e.turn_epoch,'failure_code':e.failure_code,'payload':dict(e.payload)})
    contradictory_action_count=sum(1 for row in rows if row.get('state')=='CONTRADICTORY_EVIDENCE')
    return {'schema_version':1,'actions':rows,'total_action_count':total_action_count,
            'actions_omitted':max(0,total_action_count-len(rows)),
            'contradictory_action_count':contradictory_action_count,
            'priority_action_count':priority_action_count,'priority_actions_included':included_priority_count,
            'priority_actions_omitted':max(0,priority_action_count-included_priority_count),
            'selection_policy':'RISK_FIRST_THEN_RECENT',
            'pre_action_outcomes':pre_action_outcomes,'total_pre_action_outcome_count':len(pre_action_all),
            'pre_action_outcomes_omitted':max(0,len(pre_action_all)-len(pre_action_outcomes)),
            'authorization_blockers':blockers[-32:],'total_authorization_blocker_count':len(blockers),
            'authorization_blockers_omitted':max(0,len(blockers)-min(len(blockers),32)),
            'note':'Decision and authorization outcomes are indexed even when no action_id exists. Nearby Protocol/Canonical/Live-State rows are timing/scope context only, never automatic action-outcome proof. High-risk/unresolved actions are retained before recent normal actions; bounded omissions are counted explicitly.'}


_MAJOR_WORKFLOW_TRANSITIONS=(
    ('CREATED','PREFLIGHT'),('PREFLIGHT','WORLD'),('WORLD','ENCOUNTER_SELECTED'),
    ('ENCOUNTER_SELECTED','FIGHT_ENTRY'),('FIGHT_ENTRY','PARTY_JOIN'),
    ('PARTY_JOIN','PLACEMENT'),('PLACEMENT','READY'),('READY','FIGHT_ACTIVE'),
    ('FIGHT_ACTIVE','FIGHT_END_RECONCILIATION'),
    ('FIGHT_END_RECONCILIATION','WORLD_REENTRY'),
)
_FINAL_REENTRY_TARGETS=frozenset({'WORLD','COMPLETED','STOPPED'})


def workflow_lifecycle_report(events:Iterable[DiagnosticEvent|dict])->dict:
    """Describe the latest mission/fight lifecycle using real Workflow authority events.

    This is a progress index, not a root-cause assertion. A run exported while a
    fight is legitimately in progress is ``IN_PROGRESS`` rather than "failed".
    Explicit Workflow blocked/rejected evidence is surfaced separately.
    """
    ordered=sorted((_as_event(e) for e in events),key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
    transitions=[]
    for e in ordered:
        if e.event_name!='workflow.phase_changed' or e.owner_system!='anka_workflow':continue
        old=e.payload.get('from_phase');new=e.payload.get('to_phase')
        if not isinstance(old,str) or not isinstance(new,str):continue
        if old==new:continue
        transitions.append({'event_id':e.event_id,'producer_seq':e.producer_seq,'fight_epoch':e.fight_epoch,
                            'from_phase':old,'to_phase':new,'reason':e.payload.get('reason')})
    if not transitions:
        return {'schema_version':1,'status':'NOT_APPLICABLE','current_phase':None,'latest_fight_epoch':None,
                'transitions':[],'next_expected_transition':None,'blocking_event':None,'matched_event_ids':[],
                'note':'No authoritative Workflow phase transition was included in the bounded incident timeline.'}

    # Focus the detailed cycle view on the newest selected encounter.  Earlier
    # bootstrap/world transitions remain available in the primary timeline.
    starts=[i for i,row in enumerate(transitions) if row['from_phase']=='WORLD' and row['to_phase']=='ENCOUNTER_SELECTED']
    cycle=transitions[starts[-1]:] if starts else transitions
    latest_fight_epoch=max((row['fight_epoch'] for row in cycle if isinstance(row['fight_epoch'],int) and row['fight_epoch']>0),default=None)
    current=cycle[-1]['to_phase']
    blocking=None;rejected_signal=None
    cycle_start_seq=cycle[0]['producer_seq']
    for e in ordered:
        if e.producer_seq<cycle_start_seq:continue
        if e.event_name=='workflow.signal_rejected':
            rejected_signal={'event_id':e.event_id,'event_name':e.event_name,'failure_code':e.failure_code,
                             'boundary':e.boundary,'producer_seq':e.producer_seq}
        elif e.event_name=='workflow.blocked':
            blocking={'event_id':e.event_id,'event_name':e.event_name,'failure_code':e.failure_code,
                      'boundary':e.boundary,'producer_seq':e.producer_seq}

    # Validate the major path in order while allowing action-fence self
    # transitions to exist outside this filtered list.
    expected=list(_MAJOR_WORKFLOW_TRANSITIONS[2:] if starts else _MAJOR_WORKFLOW_TRANSITIONS)
    matched=[];cursor=0;next_expected=None;contradiction=None
    for old,new in expected:
        found=None
        for i in range(cursor,len(cycle)):
            row=cycle[i]
            if row['from_phase']==old and row['to_phase']==new:
                found=i;break
            # A different major phase departure from the phase we expected is a
            # real state-machine contradiction in the included evidence.
            if row['from_phase']==old and row['to_phase']!=old:
                contradiction={'event_id':row['event_id'],'expected_from':old,'expected_to':new,
                               'observed_to':row['to_phase']}
                break
        if contradiction is not None:break
        if found is None:
            # Re-entry has multiple legitimate terminal targets and is checked
            # after the fixed sequence below.
            next_expected={'from_phase':old,'to_phase':new}
            break
        matched.append(cycle[found]['event_id']);cursor=found+1

    reentry=next((row for row in cycle[cursor:] if row['from_phase']=='WORLD_REENTRY' and row['to_phase'] in _FINAL_REENTRY_TARGETS),None)
    if current in _FINAL_REENTRY_TARGETS and reentry is not None:
        matched.append(reentry['event_id']);next_expected=None
    elif next_expected is None and current=='WORLD_REENTRY':
        next_expected={'from_phase':'WORLD_REENTRY','to_phase':'WORLD|COMPLETED|STOPPED'}

    if contradiction is not None:status='CONTRADICTORY'
    elif current=='BLOCKED' or blocking is not None:status='BLOCKED'
    elif reentry is not None:status='COMPLETE_CYCLE'
    else:status='IN_PROGRESS'
    return {'schema_version':1,'status':status,'current_phase':current,'latest_fight_epoch':latest_fight_epoch,
            'transitions':cycle,'next_expected_transition':next_expected,'blocking_event':blocking,
            'rejected_signal':rejected_signal,'contradiction':contradiction,'matched_event_ids':matched,
            'note':'Rejected Workflow signals are surfaced as non-terminal diagnostic context. BLOCKED requires an authoritative blocked phase/event; IN_PROGRESS alone is not a failure claim.'}


def turn_handoff_report(events:Iterable[DiagnosticEvent|dict])->dict:
    """Reconstruct the newest END_TURN attempt and next-owner proof."""
    ordered=sorted((_as_event(e) for e in events),key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
    requests=[e for e in ordered if e.event_name=='workflow.action_requested' and e.payload.get('kind')=='END_TURN'
              and isinstance(e.action_id,str)]
    if not requests:
        return {'schema_version':1,'status':'NOT_APPLICABLE','action_id':None,'event_ids':[],
                'next_owner_event_id':None,'next_owner_account_id':None,
                'note':'No END_TURN action request was included in the bounded incident timeline.'}
    req=requests[-1];items=[e for e in ordered if e.action_id==req.action_id and e.producer_seq>=req.producer_seq]
    admitted=next((e for e in items if e.event_name=='execution.admitted'),None)
    starts=[e for e in items if e.event_name=='execution.send_started']
    send_results=[e for e in items if e.event_name in ('execution.input_sent','execution.input_may_have_sent','execution.input_not_sent','execution.exception_after_send_started')]
    settlements=[e for e in items if e.event_name=='execution.outcome_settled']
    unresolveds=[e for e in items if e.event_name in ('execution.outcome_terminal_unresolved','execution.outcome_missing')]
    pre_send_terminals=[e for e in items if e.event_name in (
        'execution.rejected','execution.ledger_prepare_rejected','execution.input_lease_rejected',
        'execution.final_guard_rejected','execution.exception_before_send')]
    sent=send_results[0] if send_results else None
    settled=settlements[-1] if settlements else None
    unresolved=unresolveds[-1] if unresolveds else None
    hard_conflicts=[]
    if len({e.event_name for e in send_results})>1:hard_conflicts.append('CONFLICTING_SEND_RESULTS')
    if settlements and unresolveds:hard_conflicts.append('CONFLICTING_TERMINAL_OUTCOMES')
    attempts={e.attempt_id for e in starts+send_results+settlements+unresolveds if e.attempt_id is not None}
    if len(attempts)>1:hard_conflicts.append('ATTEMPT_ID_CONFLICT')
    if pre_send_terminals and (starts or send_results):hard_conflicts.append('PRE_SEND_TERMINAL_WITH_SEND')
    hard_conflicts=sorted(dict.fromkeys(hard_conflicts))
    next_owner=None
    for e in ordered:
        if e.producer_seq<=req.producer_seq or e.event_name!='coordination.turn_owner_proved':continue
        if req.fight_epoch is not None and e.fight_epoch!=req.fight_epoch:continue
        if req.turn_epoch is not None and (e.turn_epoch is None or e.turn_epoch<=req.turn_epoch):continue
        # The first authoritative newer party-owner proof is the handoff result.
        # Do not skip a same-account reappearance and borrow a later different
        # owner, which would hide a missing/incorrect immediate party handoff.
        next_owner=e;break
    refs=[e.event_id for e in (req,admitted,sent,settled,unresolved,next_owner) if e is not None]
    same_owner_reproved=(next_owner is not None and req.account_id is not None and next_owner.account_id==req.account_id)
    if hard_conflicts:status='CONTRADICTORY_ACTION_EVIDENCE'
    elif unresolved is not None:status='OUTCOME_UNRESOLVED'
    elif admitted is None:status='REQUEST_NOT_ADMITTED'
    elif sent is None:status='ADMITTED_NO_SEND_EVIDENCE'
    elif sent.event_name=='execution.input_not_sent':status='NOT_SENT'
    elif settled is None and next_owner is None:status='SENT_AWAITING_SETTLEMENT_AND_NEXT_OWNER'
    elif same_owner_reproved and settled is None:status='SAME_OWNER_REPROVED_AWAITING_SETTLEMENT'
    elif same_owner_reproved:status='SETTLED_SAME_OWNER_REPROVED'
    elif settled is None:status='NEXT_OWNER_PROVED_AWAITING_SETTLEMENT'
    elif next_owner is None:status='SETTLED_NEXT_OWNER_MISSING'
    else:status='COMPLETE'
    return {'schema_version':1,'status':status,'action_id':req.action_id,'account_id':req.account_id,
            'fight_epoch':req.fight_epoch,'turn_epoch':req.turn_epoch,'event_ids':refs,
            'send_event_id':sent.event_id if sent else None,'settlement_event_id':settled.event_id if settled else None,
            'next_owner_event_id':next_owner.event_id if next_owner else None,
            'next_owner_account_id':next_owner.account_id if next_owner else None,
            'next_turn_epoch':next_owner.turn_epoch if next_owner else None,'hard_conflicts':hard_conflicts,
            'physical_input_state':max((e.physical_input_state for e in items if e.physical_input_state),default='UNKNOWN',
                                       key=lambda s:{'NOT_SENT':0,'UNKNOWN':1,'SEND_STARTED':2,'SENT':3,'MAY_HAVE_SENT':4}.get(s,-1)),
            'note':'The first authoritative newer party-owner proof in the same fight is used; same-account reappearance is explicit and later owners cannot be borrowed. This is diagnostic evidence only.'}

READY_TRACE = OperationTraceSpec('READY', (
    # Requested intent alone is not proof that any input was sent.
    BoundaryExpectation(
        'ready.requested','workflow.ready_request','anka_workflow','workflow'),
    BoundaryExpectation(
        'execution.admitted','execution.pre_input_authorization','anka_execution','execution'),
    BoundaryExpectation(
        'execution.input_sent','execution.external_boundary','anka_execution','execution'),
    BoundaryExpectation(
        'protocol.ready_observed','protocol.ready_observation','anka_protocol','protocol'),
    BoundaryExpectation(
        'coordination.ready_barrier_satisfied','coordination.ready_barrier','anka_coordination','coordination'),
    BoundaryExpectation(
        'coordination.turn_owner_proved','coordination.first_turn','anka_coordination','coordination'),
    BoundaryExpectation(
        'decision.frame_created','decision.frame','anka_decision','decision'),
))

@dataclass(frozen=True, slots=True)
class PartyReadyAnalysis:
    """Two-or-more-account READY reconstruction without cross-account borrowing."""
    finding: DiagnosticFinding | None
    account_graphs: tuple[dict, ...]
    shared_graph: tuple[dict, ...]
    matched_event_ids: tuple[str, ...]


class PartyReadyAnalyzer:
    """Reconstruct READY per account first, then prove the shared party barrier.

    A CRA server acknowledgement can never satisfy ENU's READY path.  Likewise a
    Canonical commit from another Protocol batch cannot close a per-account edge.
    """
    _ACCOUNT_STEPS=(
        ('ready.requested','workflow.ready_request','anka_workflow'),
        ('execution.admitted','execution.pre_input_authorization','anka_execution'),
        ('execution.input_sent','execution.external_boundary','anka_execution'),
        ('protocol.ready_observed','protocol.ready_observation','anka_protocol'),
        ('canonical.ready_committed','canonical.ready_commit','anka_canonical'),
    )
    _SHARED_STEPS=(
        ('coordination.ready_barrier_satisfied','coordination.ready_barrier','anka_coordination'),
        ('coordination.turn_owner_proved','coordination.first_turn','anka_coordination'),
        ('decision.frame_created','decision.frame','anka_decision'),
    )

    @staticmethod
    def _finding(event_name:str,boundary:str,owner:str,*,account_id:str|None,events:list[DiagnosticEvent],cursor:int,control_state:str)->DiagnosticFinding:
        relevant=[e for e in events[cursor:] if e.severity in TERMINAL_SEVERITIES and (account_id is None or e.account_id in (None,account_id))][:3]
        same=[e for e in relevant if e.boundary==boundary]
        support=same or relevant
        code=(same[0].failure_code if same and same[0].failure_code else 'READY_EVIDENCE_GAP')
        suffix=f' for {account_id}' if account_id else ''
        return DiagnosticFinding(
            'finding-'+uuid4().hex,code,boundary,owner,'HIGH' if same else ('MEDIUM' if support else 'UNDETERMINED'),
            tuple(e.event_id for e in support),(),(event_name,),control_state,
            f'Collect authoritative {event_name}{suffix}; do not infer it from another account or UI state.',
            tuple(dict.fromkeys(e.failure_code for e in support if e.failure_code)),
        )

    def analyze(self,events:Iterable[DiagnosticEvent|dict],required_accounts:tuple[str,...],*,control_state:str='UNKNOWN')->PartyReadyAnalysis:
        ordered=sorted((_as_event(e) for e in events),key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
        accounts=tuple(dict.fromkeys(required_accounts))
        if len(accounts)<2 or any(type(a) is not str or not a.startswith('acct-') for a in accounts):
            raise ValueError('READY_PARTY_REQUIRED_ACCOUNTS_INVALID')
        # Diagnose the newest READY attempt represented in the bounded evidence.
        # Otherwise a complete fight N can hide an incomplete fight N+1 in the same
        # long-running recorder.  All per-account and shared edges below are bound
        # to this exact fight epoch.
        ready_requests=[(i,e) for i,e in enumerate(ordered) if e.event_name=='ready.requested' and e.account_id in accounts]
        latest_ready=ready_requests[-1] if ready_requests else None
        # Never fall back to an older healthy epoch if the newest READY request
        # itself lost its epoch correlation.  That would turn malformed current
        # evidence into a false historical success.
        if latest_ready is not None and latest_ready[1].fight_epoch is None:
            idx,event=latest_ready
            finding=self._finding('ready.requested.fight_epoch','workflow.ready_request','anka_workflow',
                                  account_id=event.account_id,events=ordered,cursor=idx,control_state=control_state)
            graphs=tuple({
                'account_id':account,'fight_epoch':None,
                'edges':({'account_id':account,'fight_epoch':None,'event_name':'ready.requested',
                          'boundary':'workflow.ready_request','owner_system':'anka_workflow',
                          'status':'INVALID_CORRELATION' if account==event.account_id else 'NOT_REACHED',
                          'event_id':event.event_id if account==event.account_id else None,
                          'action_id':event.action_id if account==event.account_id else None,'batch_span_id':None},)
            } for account in accounts)
            return PartyReadyAnalysis(finding,graphs,(),(event.event_id,))
        target_fight_epoch=(latest_ready[1].fight_epoch if latest_ready is not None else None)
        graphs=[];matched=[];last_seq=0;finding=None
        for account in accounts:
            action_id=None;batch_span=None;edges=[]
            request_candidates=[(i,e) for i,e in ready_requests if e.account_id==account
                                and (target_fight_epoch is None or e.fight_epoch==target_fight_epoch)]
            request_pair=request_candidates[-1] if request_candidates else None
            cursor=(request_pair[0] if request_pair is not None else 0)
            for event_name,boundary,owner in self._ACCOUNT_STEPS:
                idx=None
                if event_name=='ready.requested' and request_pair is not None:
                    idx=request_pair[0]
                else:
                    for i in range(cursor,len(ordered)):
                        e=ordered[i]
                        if e.event_name!=event_name or e.boundary!=boundary or e.owner_system!=owner or e.account_id!=account:continue
                        if target_fight_epoch is not None and e.fight_epoch!=target_fight_epoch:continue
                        if action_id is not None and event_name in ('execution.admitted','execution.input_sent') and e.action_id!=action_id:continue
                        if batch_span is not None and event_name=='canonical.ready_committed' and e.payload.get('batch_span_id')!=batch_span:continue
                        idx=i;break
                if idx is None:
                    edges.append({'account_id':account,'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,'owner_system':owner,'status':'MISSING','event_id':None,'action_id':action_id,'batch_span_id':batch_span})
                    if finding is None:finding=self._finding(event_name,boundary,owner,account_id=account,events=ordered,cursor=cursor,control_state=control_state)
                    break
                e=ordered[idx]
                if event_name=='ready.requested':
                    action_id=e.action_id
                    if action_id is None or e.fight_epoch is None:
                        edges.append({'account_id':account,'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,'owner_system':owner,'status':'INVALID_CORRELATION','event_id':e.event_id,'action_id':action_id,'batch_span_id':None})
                        missing='ready.requested.action_id' if action_id is None else 'ready.requested.fight_epoch'
                        if finding is None:finding=self._finding(missing,boundary,owner,account_id=account,events=ordered,cursor=idx,control_state=control_state)
                        break
                if event_name=='protocol.ready_observed':
                    candidate_batch=e.payload.get('batch_span_id')
                    if not isinstance(candidate_batch,str) or not candidate_batch:
                        matched.append(e.event_id);last_seq=max(last_seq,e.producer_seq);cursor=idx+1
                        edges.append({'account_id':account,'fight_epoch':target_fight_epoch,'event_name':event_name,
                                      'boundary':boundary,'owner_system':owner,'status':'INVALID_CORRELATION',
                                      'event_id':e.event_id,'action_id':action_id,'batch_span_id':None})
                        if finding is None:
                            finding=self._finding('protocol.ready_observed.batch_span_id',boundary,owner,
                                                  account_id=account,events=ordered,cursor=idx,control_state=control_state)
                        break
                    batch_span=candidate_batch
                matched.append(e.event_id);last_seq=max(last_seq,e.producer_seq);cursor=idx+1
                edges.append({'account_id':account,'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,'owner_system':owner,'status':'OBSERVED','event_id':e.event_id,'action_id':action_id,'batch_span_id':batch_span})
            graphs.append({'account_id':account,'fight_epoch':target_fight_epoch,'edges':edges})
            if finding is not None:break

        shared=[]
        if finding is None:
            cursor=0
            while cursor<len(ordered) and ordered[cursor].producer_seq<=last_seq:cursor+=1
            owner_account=None
            for event_name,boundary,owner in self._SHARED_STEPS:
                idx=None;invalid_correlation=None
                for i in range(cursor,len(ordered)):
                    e=ordered[i]
                    if e.event_name!=event_name or e.boundary!=boundary or e.owner_system!=owner:continue
                    if target_fight_epoch is not None and e.fight_epoch!=target_fight_epoch:continue
                    if event_name=='coordination.ready_barrier_satisfied':
                        required=e.payload.get('required_accounts')
                        if not isinstance(required,(list,tuple)) or set(required)!=set(accounts):
                            idx=i;invalid_correlation='required_accounts';break
                    if event_name=='decision.frame_created' and owner_account is not None and e.account_id!=owner_account:continue
                    idx=i;break
                if idx is None:
                    shared.append({'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,'owner_system':owner,'status':'MISSING','event_id':None})
                    finding=self._finding(event_name,boundary,owner,account_id=None,events=ordered,cursor=cursor,control_state=control_state)
                    break
                e=ordered[idx]
                if invalid_correlation is not None:
                    matched.append(e.event_id);cursor=idx+1
                    shared.append({'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,
                                   'owner_system':owner,'status':'INVALID_CORRELATION','event_id':e.event_id,
                                   'invalid_field':invalid_correlation})
                    finding=self._finding(event_name+'.'+invalid_correlation,boundary,owner,
                                          account_id=None,events=ordered,cursor=idx,control_state=control_state)
                    break
                if event_name=='coordination.turn_owner_proved':
                    owner_account=e.account_id
                    if owner_account not in accounts:
                        matched.append(e.event_id);cursor=idx+1
                        shared.append({'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,
                                       'owner_system':owner,'status':'INVALID_CORRELATION','event_id':e.event_id,
                                       'owner_account_id':owner_account,'invalid_field':'owner_account_id'})
                        finding=self._finding(event_name+'.owner_account_id',boundary,owner,
                                              account_id=None,events=ordered,cursor=idx,control_state=control_state)
                        break
                matched.append(e.event_id);cursor=idx+1
                shared.append({'fight_epoch':target_fight_epoch,'event_name':event_name,'boundary':boundary,'owner_system':owner,'status':'OBSERVED','event_id':e.event_id,'owner_account_id':owner_account})
        return PartyReadyAnalysis(finding,tuple(graphs),tuple(shared),tuple(dict.fromkeys(matched)))

# Historical incident signatures are diagnostic hints only.  A match means the
# current bounded evidence shares observable symptoms/boundaries with an older
# failure family; it is never automatic proof of the old root cause.
_HISTORICAL_SIGNATURES=(
    ('R5.142_ACTION_CONTRACT_REPLAN','malformed action contract / same-frame replanning',
     (('ACTION_CONTRACT','MALFORMED','PLAN_REJECTED'),('REPLAN','REPEATED_ACTION','ACTION_KEY'))),
    ('R5.151_LATE_CONFIRMATION_GLOBAL_DISARM','late confirmation amplified into global disarm',
     (('MAY_HAVE_SENT','SENT_UNCONFIRMED','OUTCOME_MISSING'),('DISARM','AUTHORITY','UNRESOLVED'))),
    ('R5.195_STATIC_PLACEMENT_GEOMETRY','stale/static placement geometry',
     (('PLACEMENT',),('GEOMETRY','WALKABLE','TARGET_CELL','PROJECTION'))),
    ('R5.196_RESOURCE_FRESHNESS','wrong AP/MP/resource freshness floor',
     (('RESOURCE','AP','MP'),('STALE','FRESHNESS','CURSOR','PROOF'))),
    ('R5.197_PROCESS_LISTENER_OWNERSHIP','stale process/listener ownership',
     (('PROCESS','PID','WINDOW','CLIENT_GENERATION'),('STALE','GENERATION','OWNERSHIP','TCP'))),
    ('R5.198_UNKNOWN_WIRE_AFTER_CAST','new unknown protocol wire after settled action',
     (('UNKNOWN_WIRE','PROTOCOL','DECODE'),('CAST','ACTION','SETTLED','CANONICAL'))),
    ('READY_NO_FIRST_TURN','both Ready but no proven first turn',
     (('READY',),('TURN_OWNER','FIRST_TURN','READY_BARRIER'))),
    ('WRONG_FOCUS_WINDOW','wrong focus/window before input',
     (('FOCUS','WINDOW','ATTESTATION'),('INPUT','EXECUTION','PRE_INPUT'))),
    ('END_TURN_NO_NEXT_OWNER','End Turn but no next owner/handoff',
     (('END_TURN','ENDTURN'),('NEXT_OWNER','TURN_OWNER','HANDOFF'))),
    ('FIGHT_END_WORLD_REENTRY_STALL','fight end / world re-entry stall',
     (('FIGHT_END','VICTORY','DEFEAT'),('WORLD_REENTRY','WORLD_REENTRY','WORLD'))),
)


def _forensic_signal_text(events:Iterable[DiagnosticEvent|dict],*,code:str='',boundary:str='')->str:
    parts=[code,boundary]
    for raw in events:
        e=_as_event(raw)
        # Healthy trace traffic must not manufacture a historical "match".
        # Only failure/safety/settlement-uncertainty signals contribute, plus the
        # explicit incident code/boundary supplied by the caller.
        if not (e.failure_code or e.severity in TERMINAL_SEVERITIES or e.physical_input_state=='MAY_HAVE_SENT'):
            continue
        parts.extend((e.event_name,e.boundary or '',e.failure_code or '',e.owner_system or '',e.physical_input_state or ''))
        # Only bounded scalar diagnostic payload values participate in heuristic
        # matching; arbitrary nested payload text is intentionally ignored.
        for key,value in e.payload.items():
            if key in ('scope','kind','status','reason','phase','workflow_phase') and isinstance(value,(str,int,bool)):
                parts.append(str(value))
    return ' '.join(parts).upper()


def historical_similarity_report(events:Iterable[DiagnosticEvent|dict],*,code:str='',boundary:str='',limit:int=5)->dict:
    """Return bounded historical *similarity*, never root-cause identity."""
    rows=list(events);text=_forensic_signal_text(rows,code=code,boundary=boundary)
    matches=[]
    for case_id,title,groups in _HISTORICAL_SIGNATURES:
        matched=[]
        for alternatives in groups:
            hit=next((token for token in alternatives if token in text),None)
            if hit is not None:matched.append(hit)
        if not matched:continue
        score=len(matched)/len(groups)
        # Require every cue group for a strong match.  One-group partials are
        # retained only when the signature itself has one group.
        if len(matched)<len(groups) and len(groups)>1:continue
        matches.append({'case_id':case_id,'title':title,'similarity_score':round(score,3),
                        'matched_cues':matched,'classification':'SIMILARITY_ONLY',
                        'root_cause_reused':False})
    matches.sort(key=lambda x:(-x['similarity_score'],x['case_id']))
    return {'schema_version':1,'matches':matches[:max(1,limit)],
            'note':'Historical similarity is a search hint only; current evidence must establish the current root cause independently.'}


def recovery_history_report(events:Iterable[DiagnosticEvent|dict],*,limit:int=24)->dict:
    """Summarize bounded recovery/retry/watchdog evidence with exact event refs."""
    ordered=sorted((_as_event(e) for e in events),key=lambda e:(e.producer_seq,e.monotonic_ns,e.event_id))
    rows=[]
    for e in ordered:
        name=e.event_name
        if not (('recovery' in name) or ('retry' in name) or name.endswith('.watchdog') or '.watchdog_' in name):continue
        rows.append({'event_id':e.event_id,'event_name':name,'owner_system':e.owner_system,'boundary':e.boundary,
                     'account_id':e.account_id,'fight_epoch':e.fight_epoch,'turn_epoch':e.turn_epoch,
                     'failure_code':e.failure_code,'severity':e.severity,
                     'status':e.payload.get('status') if isinstance(e.payload,dict) else None,
                     'reason':e.payload.get('reason') if isinstance(e.payload,dict) else None})
    rows=rows[-max(1,limit):]
    return {'schema_version':1,'attempts':rows,'count':len(rows),
            'note':'Rows are recorded recovery/watchdog evidence only; absence does not prove that no external/manual recovery occurred.'}


def proven_fact_report(events:Iterable[DiagnosticEvent|dict],boundary_graph:Iterable[dict],action_report:dict)->dict:
    """Build a small evidence-linked summary without upgrading diagnostic facts to gameplay authority."""
    event_by_id={_as_event(e).event_id:_as_event(e) for e in events}
    facts=[]
    for edge in boundary_graph:
        if not isinstance(edge,dict) or edge.get('status')!='OBSERVED':continue
        ref=edge.get('event_id')
        if not isinstance(ref,str) or ref not in event_by_id:continue
        facts.append({'kind':'BOUNDARY_OBSERVED','event_id':ref,'event_name':edge.get('event_name'),
                      'boundary':edge.get('boundary'),'owner_system':edge.get('owner_system')})
        if len(facts)>=24:break
    settled=0;unresolved=[]
    for row in action_report.get('actions',[]) if isinstance(action_report,dict) else ():
        if not isinstance(row,dict):continue
        if row.get('state')=='SETTLED':settled+=1
        elif row.get('state') not in (None,'NOT_SENT'):unresolved.append({'action_id':row.get('action_id'),'state':row.get('state')})
    return {'schema_version':1,'facts':facts,'settled_action_count':settled,'unresolved_actions':unresolved[:16],
            'note':'These are facts about included diagnostic evidence, not independent certification of game/server truth.'}
