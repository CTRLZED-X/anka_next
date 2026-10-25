"""Bounded, sanitized and causally inspectable local incident bundles.

Observability is passive: none of the data produced here is an authority source for
Canonical state, Coordination permits, Workflow progress or Execution input.
"""
from __future__ import annotations
from hashlib import sha256
from datetime import datetime
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED
import json
import re

from anka_contracts.diagnostics import DiagnosticEvent, OperationTraceSpec, now_utc
from anka_observability.forensics import (
    FirstDivergenceAnalyzer, PartyReadyAnalyzer, action_lifecycle_report, evidence_matrix,
    historical_similarity_report, recovery_history_report, proven_fact_report,
    workflow_lifecycle_report, turn_handoff_report,
)
from anka_observability.redaction import sanitize,sanitize_export,has_diagnostic_truncation,has_unredacted_sensitive_data
from anka_observability.api import (
    is_priority_event,
    DIAGNOSTIC_EVENT_ID_RE, DIAGNOSTIC_INVOCATION_ID_RE, DIAGNOSTIC_RUN_ID_RE,
)

BUNDLE_SCHEMA=2
EVIDENCE_STATUS=('PRESENT','PRESENT_STALE','PARTIAL','MISSING','NOT_APPLICABLE','EXPORT_FAILED')
CRITICAL_SECTIONS=(
    'bootstrap','configuration','identity','capture','protocol','canonical','live_state',
    'coordination','decision','execution','outcome','workflow','observability',
)
MAX_TIMELINE_BYTES=256*1024
MAX_PRIORITY_TIMELINE_BYTES=128*1024
MAX_PINNED_TIMELINE_BYTES=96*1024
REQUIRED_SCHEMA2_FILES=frozenset({
    'diagnosis.json','evidence_matrix.json','timeline.jsonl','GPT_READ_FIRST.md','run_manifest.json',
    'analysis/diagnosis.json','analysis/boundary_graph.json','analysis/party_ready.json',
    'analysis/action_lifecycles.json','analysis/evidence_gaps.json','analysis/historical_matches.json',
    'analysis/recovery_history.json','analysis/proven_facts.json','analysis/next_verification.json',
    'analysis/workflow_lifecycle.json','analysis/turn_handoff.json',
    'analysis/evidence_request.json','analysis/snapshot_index.json','analysis/gpt_summary.json',
    'logs/relevant_timeline.jsonl','logs/priority_timeline.jsonl','logs/relevant_errors.jsonl',
    'metadata/flight_recorder.json','metadata/artifact_integrity.json','metadata/capture_protocol_summary.json',
})


def _serialized(data:object)->bytes:
    return (json.dumps(sanitize_export(data),sort_keys=True,ensure_ascii=True,indent=2)+'\n').encode('utf8')


def _json_line(data:object)->bytes:
    """One actual JSON object per line. Pretty JSON is not JSONL."""
    return (json.dumps(sanitize(data),sort_keys=True,ensure_ascii=True,separators=(',',':'))+'\n').encode('utf8')


def _event_key(e:dict):
    return (int(e.get('producer_seq',0)),int(e.get('monotonic_ns',0)),str(e.get('event_id','')))


def _semantic_artifact(value:object)->object:
    """Strip generated presentation identifiers before recomputing analyzer truth.

    Finding IDs exist so humans/GPT can reference a finding inside one exported
    bundle. They are intentionally fresh UUIDs and therefore are not part of the
    forensic semantics a verifier can deterministically recompute.
    """
    if isinstance(value,dict):
        return {k:_semantic_artifact(v) for k,v in value.items() if k!='finding_id'}
    if isinstance(value,list):return [_semantic_artifact(v) for v in value]
    if isinstance(value,tuple):return [_semantic_artifact(v) for v in value]
    return value


def _loss_adjusted_confidence(confidence:str, evidence_loss:bool)->str:
    """Downgrade causal certainty when recorder evidence is known incomplete.

    Analyzer confidence describes the retained slice. A bundle that knows rows
    were overwritten, dropped, truncated or lost must not present that same level
    as confidence in the true first divergence across the whole run.
    """
    if not evidence_loss:return confidence
    return {'HIGH':'MEDIUM','MEDIUM':'LOW','LOW':'LOW','UNDETERMINED':'UNDETERMINED'}.get(confidence,'UNDETERMINED')


def _aggregate_physical_input_state(events) -> str:
    """Return the conservative run-level physical-input risk summary.

    A later NOT_SENT observation must never erase an earlier uncertain or proven
    external input. MAY_HAVE_SENT wins because it creates the strongest replay
    constraint; SENT follows, then SEND_STARTED, UNKNOWN, and finally NOT_SENT.
    """
    rank={'NOT_SENT':0,'UNKNOWN':1,'SEND_STARTED':2,'SENT':3,'MAY_HAVE_SENT':4}
    states=[e.get('physical_input_state') for e in events if isinstance(e,dict) and e.get('physical_input_state') in rank]
    if not states:return 'UNKNOWN'
    return max(states,key=lambda state:rank[state])


def _dedup(events)->list[dict]:
    by_id={}
    for raw in events:
        if not isinstance(raw,dict):continue
        event_id=raw.get('event_id')
        if not isinstance(event_id,str) or not event_id:continue
        by_id.setdefault(event_id,raw)
    return sorted(by_id.values(),key=_event_key)


def _fit_lines(events:list[dict],limit:int,*,prefer_latest:bool=False)->tuple[list[dict],bytes,int]:
    """Return whole JSONL records only, never byte-sliced partial JSON."""
    ordered=list(reversed(events)) if prefer_latest else list(events)
    kept=[];used=0
    for event in ordered:
        line=_json_line(event)
        if len(line)>8192:continue
        if used+len(line)>limit:continue
        kept.append(event);used+=len(line)
    if prefer_latest:kept.reverse()
    kept=sorted(_dedup(kept),key=_event_key)
    blob=b''.join(_json_line(x) for x in kept)
    return kept,blob,max(0,len(events)-len(kept))


def _priority_row(row:dict)->bool:
    try:return is_priority_event(DiagnosticEvent.from_dict(row))
    except (TypeError,ValueError):return row.get('severity') in ('ERROR','CRITICAL','SAFETY','SETTLEMENT')


_CAUSAL_SKELETON_EVENTS=frozenset({
    # Mission/fight lifecycle authority.  Self-transitions are filtered below.
    'workflow.phase_changed','workflow.action_requested','workflow.action_authorization_blocked',
    # Exact external-boundary / settlement evidence needed to distinguish intent,
    # send uncertainty and observed completion for every action family.
    'execution.admitted','execution.input_sent','execution.input_not_sent',
    'execution.input_may_have_sent','execution.exception_after_send_started',
    'execution.outcome_settled','execution.outcome_terminal_unresolved','execution.outcome_missing',
    # READY and turn-handoff causal edges.
    'ready.requested','protocol.ready_observed','canonical.ready_committed',
    'coordination.ready_barrier_satisfied','coordination.turn_owner_proved','decision.frame_created',
    # Pre-action Decision result is required to distinguish deliberate WAIT/
    # NO_ACTION/FAULT from a later Workflow/Coordination authorization stop.
    'decision.plan_result',
})

def _causal_skeleton_row(row:dict)->bool:
    """Return evidence that must outrank routine priority chatter at export.

    A bounded incident cannot retain every event from a long farming run.  It must,
    however, preserve enough authority edges to reconstruct the mission phase and
    the input/outcome lifecycle.  This lane is a *retention policy only*; it grants
    no gameplay authority and does not change event severity.
    """
    name=row.get('event_name')
    if row.get('severity') in ('ERROR','CRITICAL','SAFETY'):return True
    if row.get('failure_code'):return True
    if name=='workflow.phase_changed':
        payload=row.get('payload') if isinstance(row.get('payload'),dict) else {}
        return payload.get('from_phase')!=payload.get('to_phase')
    return name in _CAUSAL_SKELETON_EVENTS


def _bounded_timeline(observer, *, incident_code:str|None=None, incident_boundary:str|None=None) -> tuple[list[dict], bytes, bytes, dict]:
    """Flight-recorder export: exact incident trigger + pinned + critical + recent.

    The event that most directly triggered this incident is reserved *before* all
    other bounded lanes.  A saturated causal/priority workload must never produce
    a verifier-clean ZIP that names a failure while omitting the failure row itself.
    """
    pinned=_dedup(getattr(observer,'pinned',()))
    priority_memory=_dedup(getattr(observer,'priority',()))
    recent=_dedup(getattr(observer,'recent',()))
    all_memory=_dedup(pinned+priority_memory+recent)
    exact=[e for e in all_memory if incident_code and e.get('failure_code')==incident_code]
    if not exact and incident_boundary:
        exact=[e for e in all_memory if e.get('boundary')==incident_boundary and
               (e.get('failure_code') or e.get('severity') in ('ERROR','CRITICAL','SAFETY') or
                e.get('physical_input_state')=='MAY_HAVE_SENT' or
                e.get('evidence_class') in ('MISSING','CONFLICTING'))]
    trigger=exact[-1:]
    trigger_ids={e.get('event_id') for e in trigger}
    trigger_blob=b''.join(_json_line(e) for e in trigger)
    # A legal recorder event is already bounded to <=8192 bytes.  Keep defensive
    # accounting explicit in case a foreign FrozenDiagnostics is constructed.
    if len(trigger_blob)>MAX_TIMELINE_BYTES:
        trigger=[];trigger_ids=set();trigger_blob=b''
    # Repair a smaller priority ring from the still-resident recent ring at export
    # time.  If a priority row cannot fit the bounded priority export, it must not
    # reappear only in the ordinary timeline, which would make the priority index
    # silently incomplete.
    priority=_dedup(priority_memory+[row for row in recent if _priority_row(row)])
    # Pinned pre-failure context is the highest-retention diagnostic lane.  It is
    # followed by critical/settlement evidence and then the newest ordinary
    # context.  All three remain bounded and duplicate event IDs are removed.
    pinned_without_trigger=[e for e in pinned if e.get('event_id') not in trigger_ids]
    pinned_budget=min(MAX_PINNED_TIMELINE_BYTES,max(0,MAX_TIMELINE_BYTES-len(trigger_blob)))
    pinned_kept,pinned_blob,pinned_omitted=_fit_lines(pinned_without_trigger,pinned_budget)
    pinned_ids={e['event_id'] for e in pinned_kept}
    priority_only=[e for e in priority if e.get('event_id') not in pinned_ids and e.get('event_id') not in trigger_ids]
    priority_limit=min(MAX_PRIORITY_TIMELINE_BYTES,max(0,MAX_TIMELINE_BYTES-len(trigger_blob)-len(pinned_blob)))
    # Preserve the causal skeleton before routine priority rows.  Previously the
    # priority budget was filled oldest-first; a perfectly complete Q9 mission
    # therefore lost its final End-Turn/fight-end/world-reentry edges and the
    # forensic report falsely looked IN_PROGRESS.
    skeleton=[e for e in priority_only if _causal_skeleton_row(e)]
    skeleton_kept,skeleton_blob,skeleton_omitted=_fit_lines(skeleton,priority_limit)
    skeleton_ids={e['event_id'] for e in skeleton_kept}
    remaining_priority=max(0,priority_limit-len(skeleton_blob))
    routine_priority=[e for e in priority_only if e.get('event_id') not in skeleton_ids and not _causal_skeleton_row(e)]
    # Routine priority context prefers the newest rows once the durable causal
    # skeleton is secured.  Pinned pre-failure context already protects the
    # earliest anomaly neighborhood independently.
    routine_kept,routine_blob,routine_omitted=_fit_lines(routine_priority,remaining_priority,prefer_latest=True)
    priority_kept=sorted(skeleton_kept+routine_kept,key=_event_key)
    priority_only_blob=b''.join(_json_line(e) for e in priority_kept)
    priority_omitted=skeleton_omitted+routine_omitted
    important_ids=trigger_ids|pinned_ids|{e['event_id'] for e in priority_kept}
    priority_candidate_ids={e.get('event_id') for e in priority}
    ordinary=[e for e in recent if e.get('event_id') not in important_ids and e.get('event_id') not in priority_candidate_ids]
    important_blob=trigger_blob+pinned_blob+priority_only_blob
    remaining=max(0,MAX_TIMELINE_BYTES-len(important_blob))
    ordinary_kept,ordinary_blob,ordinary_omitted=_fit_lines(ordinary,remaining,prefer_latest=True)
    events=sorted(trigger+pinned_kept+priority_kept+ordinary_kept,key=_event_key)
    timeline=b''.join(_json_line(e) for e in events)
    priority_blob=b''.join(_json_line(e) for e in sorted(trigger+pinned_kept+priority_kept,key=_event_key))
    meta={
        'recent_capacity':getattr(observer,'max_recent',len(recent)),
        'priority_capacity':getattr(observer,'max_priority',len(priority)),
        'pinned_capacity':getattr(observer,'max_pinned',len(pinned)),
        'recent_in_memory':len(recent),'priority_in_memory':len(priority_memory),'pinned_in_memory':len(pinned),
        'recent_overwrites':int(getattr(observer,'recent_overwrites',0)),
        'priority_overwrites':int(getattr(observer,'priority_overwrites',0)),
        'pinned_context_omissions':int(getattr(observer,'pinned_context_omissions',0)),
        'sanitization_truncations':int(getattr(observer,'sanitization_truncations',0)),
        'timeline_events_included':len(events),
        'priority_events_included':len(trigger)+len(pinned_kept)+len(priority_kept),
        'incident_trigger_events_included':len(trigger),
        'incident_trigger_event_ids':[e.get('event_id') for e in trigger],
        'causal_skeleton_events_in_memory':len(skeleton),
        'causal_skeleton_events_included':len(skeleton_kept),
        'causal_skeleton_events_omitted_for_size':skeleton_omitted,
        'pinned_events_included':len(pinned_kept),
        'timeline_events_omitted_for_size':ordinary_omitted+priority_omitted+pinned_omitted,
        'journal_dropped_events':int(getattr(observer,'dropped',0)),
        'journal_queue_drops':int(getattr(observer,'journal_queue_drops',0)),
        'priority_journal_queue_drops':int(getattr(observer,'priority_journal_queue_drops',0)),
        'journal_pending':int(getattr(observer,'journal_pending',0)),
        'priority_journal_pending':int(getattr(observer,'priority_journal_pending',0)),
        'persistent_storage_available':bool(getattr(observer,'available',False)),
        'source_tail_uncertain':bool(getattr(observer,'source_tail_uncertain',False)),
    }
    return events,timeline,priority_blob,meta


def _legacy_diagnosis(code:str,boundary:str,detail:str,observer,events:list[dict])->dict:
    return {
        'schema_version':1,
        'failure_code':sanitize(code),
        'first_observed_boundary':sanitize(boundary),
        'finding_status':'HYPOTHESIS_NOT_VERIFIED',
        'confidence':'UNDETERMINED',
        'explanation':sanitize(detail),
        'candidate_causes':[],
        'cause_status':'UNDETERMINED',
        'evidence_ids':[e['event_id'] for e in events if e.get('severity') in ('ERROR','CRITICAL','SAFETY')][-20:],
        'observer_dropped_events':observer.dropped,
        'observer_errors':list(observer.errors[-10:]),
        'missing_information':'This bounded bundle cannot by itself certify live game state, root causes, or server outcomes.',
    }


def _build_artifacts(observer, code:str, boundary:str, detail:str, *,
                     trace_spec:OperationTraceSpec|None=None,
                     control_state:str='UNKNOWN',
                     primary_export_failed:bool=False) -> tuple[dict[str,bytes],dict]:
    events,timeline,priority_timeline,flight=_bounded_timeline(observer,incident_code=code,incident_boundary=boundary)
    snapshots=getattr(observer,'snapshots',{})
    snapshot_artifacts={}
    snapshot_names=[]
    snapshot_omissions=[]
    for name,value in sorted(snapshots.items()):
        safe_name=str(name)
        try:payload=_serialized(value)
        except Exception as exc:
            snapshot_omissions.append({'name':safe_name,'reason':'SERIALIZATION_FAILED:'+type(exc).__name__.upper()})
            continue
        if len(payload)>32768:
            snapshot_omissions.append({'name':safe_name,'reason':'SERIALIZED_SIZE_LIMIT'})
            continue
        snapshot_artifacts[f'snapshots/{safe_name}.json']=payload
        snapshot_names.append(safe_name)
    flight=dict(flight)
    flight['snapshot_export_omissions']=len(snapshot_omissions)
    loss=(observer.dropped or flight['recent_overwrites'] or flight['priority_overwrites'] or
          flight['pinned_context_omissions'] or flight['sanitization_truncations'] or flight['timeline_events_omitted_for_size'] or flight['journal_queue_drops'] or
          flight['priority_journal_queue_drops'] or flight['snapshot_export_omissions'] or not flight['persistent_storage_available'] or flight.get('source_tail_uncertain',False))
    sections=evidence_matrix(events,dropped=int(bool(loss)),observer_errors=observer.errors)
    if 'setup' in boundary or 'startup' in boundary or 'bootstrap' in boundary:
        sections['bootstrap']='PARTIAL' if sections['bootstrap']=='MISSING' else sections['bootstrap']
    if 'config' in boundary:
        sections['configuration']='PARTIAL' if sections['configuration']=='MISSING' else sections['configuration']
    if 'client' in boundary or 'identity' in boundary:
        sections['identity']='PARTIAL' if sections['identity']=='MISSING' else sections['identity']
    if primary_export_failed:sections['observability']='EXPORT_FAILED'

    physical_input_state=_aggregate_physical_input_state(events)

    finding=None;boundary_graph=[]
    if trace_spec is not None:
        analysis=FirstDivergenceAnalyzer().analyze(trace_spec,events,fallback_failure_code=code,control_state=control_state)
        finding=analysis.finding;boundary_graph=list(analysis.boundary_graph)

    # READY is a party operation: prove each account's request→send→server→
    # Canonical chain independently before accepting the shared barrier.  Keep
    # this supplemental artifact even when another trace is the primary incident.
    ready_accounts=tuple(dict.fromkeys(e.get('account_id') for e in events
        if e.get('event_name')=='ready.requested' and isinstance(e.get('account_id'),str)))
    party_ready_payload={'schema_version':1,'status':'NOT_APPLICABLE','required_accounts':list(ready_accounts),'account_graphs':[],'shared_graph':[],'matched_event_ids':[]}
    if len(ready_accounts)>=2:
        party_ready=PartyReadyAnalyzer().analyze(events,ready_accounts,control_state=control_state)
        party_ready_payload={'schema_version':1,'status':'DIVERGED' if party_ready.finding else 'COMPLETE',
            'required_accounts':list(ready_accounts),'account_graphs':list(party_ready.account_graphs),
            'shared_graph':list(party_ready.shared_graph),'matched_event_ids':list(party_ready.matched_event_ids),
            'finding':party_ready.finding.to_dict() if party_ready.finding else None}
        if (trace_spec is not None and trace_spec.operation.upper().startswith('READY')) or 'READY' in code or 'ready' in boundary.lower():
            if party_ready.finding is not None:finding=party_ready.finding
            elif trace_spec is not None and trace_spec.operation.upper().startswith('READY'):
                finding=None
                boundary_graph=[edge for graph in party_ready.account_graphs for edge in graph['edges']]+list(party_ready.shared_graph)

    finding_scope='INCLUDED_EVIDENCE_ONLY' if loss else 'COMPLETE_RECORDER_EVIDENCE'
    retained_confidence=(finding.confidence if finding is not None else 'UNDETERMINED')
    confidence=_loss_adjusted_confidence(retained_confidence,bool(loss))
    if finding is None:
        diagnosis=_legacy_diagnosis(code,boundary,detail,observer,events)
        diagnosis.update({'evidence_loss_present':bool(loss),'first_divergence_scope':finding_scope,
                          'cause_scope':finding_scope,'candidate_causes_may_be_incomplete':bool(loss)})
        first_boundary='NOT_ESTABLISHED';confidence='UNDETERMINED';missing=[]
        next_test='Collect the earliest missing authoritative boundary evidence.'
    else:
        cause_status=('MULTIPLE_PLAUSIBLE' if len(finding.candidate_causes)>1 else
                      'SINGLE_SUPPORTED' if len(finding.candidate_causes)==1 else 'UNDETERMINED')
        diagnosis={'schema_version':2,**finding.to_dict(),'confidence':confidence,
                   'retained_evidence_confidence':retained_confidence,
                   'cause_status':cause_status,'cause_scope':finding_scope,
                   'candidate_causes_may_be_incomplete':bool(loss),'explanation':sanitize(detail),
                   'observer_dropped_events':observer.dropped,'observer_errors':list(observer.errors[-10:]),
                   'evidence_loss_present':bool(loss),'first_divergence_scope':finding_scope}
        first_boundary=finding.first_divergent_boundary
        missing=list(finding.missing_evidence);next_test=finding.recommended_next_test

    suspected_owner=(finding.suspected_owner if finding is not None else 'NOT_ESTABLISHED')
    cause_status=(diagnosis.get('cause_status','UNDETERMINED') if isinstance(diagnosis,dict) else 'UNDETERMINED')
    candidate_causes=(list(finding.candidate_causes) if finding is not None else [])
    errors=[e for e in events if e.get('severity') in ('ERROR','CRITICAL','SAFETY')]
    error_lines=b''.join(_json_line(e) for e in errors)
    gaps=[{'section':key,'status':value} for key,value in sections.items() if value not in ('PRESENT','NOT_APPLICABLE')]
    evidence_payload={'schema_version':2,'sections':sections,
        'note':'Statuses describe diagnostic evidence availability only; they never promote observer data to gameplay authority.'}
    evidence_completeness='PARTIAL' if any(v not in ('PRESENT','NOT_APPLICABLE') for v in sections.values()) else 'PRESENT'
    run_manifest={
        'schema_version':2,'run_id':observer.run_id,'invocation_id':observer.invocation_id,
        'control_state':control_state,'observer_dropped_events':observer.dropped,
        'observer_errors':list(observer.errors[-10:]),'bounded_recent_event_count':len(events),
        'physical_input_state':physical_input_state,'flight_recorder':flight,
        'evidence_completeness':evidence_completeness,
    }
    next_verification={'schema_version':1,'recommended_next_test':next_test,'missing_evidence':missing}
    graph_payload={'schema_version':1,'operation':trace_spec.operation if trace_spec else None,'edges':boundary_graph}
    action_lifecycles=action_lifecycle_report(events)
    pre_action_outcomes=action_lifecycles.get('pre_action_outcomes',[]) if isinstance(action_lifecycles,dict) else []
    latest_included_pre_action_outcome=(pre_action_outcomes[-1] if pre_action_outcomes else None)
    action_rows=action_lifecycles.get('actions',[]) if isinstance(action_lifecycles,dict) else []
    latest_included_action_lifecycle=(action_rows[-1] if action_rows else None)
    historical_matches=historical_similarity_report(events,code=code,boundary=boundary)
    recovery_history=recovery_history_report(events)
    workflow_lifecycle=workflow_lifecycle_report(events)
    turn_handoff=turn_handoff_report(events)
    proven_facts=proven_fact_report(events,boundary_graph,action_lifecycles)
    support_refs=(list(diagnosis.get('supporting_evidence_ids',[]) or []) if finding is not None else [])
    historical_ids=[row.get('case_id') for row in historical_matches.get('matches',[]) if isinstance(row,dict)]
    recovery_count=int(recovery_history.get('count',0) or 0)
    unresolved_actions=proven_facts.get('unresolved_actions',[]) if isinstance(proven_facts,dict) else []
    attempted_operation=(trace_spec.operation if trace_spec is not None else code)
    gap_summary=[f"{row['section']}={row['status']}" for row in gaps]
    gpt_finding_status=('NOT_ESTABLISHED' if finding is None else ('DIVERGENCE_CANDIDATE' if loss else 'DIVERGENCE_IDENTIFIED'))
    gpt_summary={
        'schema_version':1,'incident_code':sanitize(code),'attempted_operation':sanitize(attempted_operation),
        'finding_status':gpt_finding_status,
        'first_divergence':sanitize(first_boundary),'first_divergence_scope':finding_scope,
        'absence_is_conclusive':not bool(loss),'source_tail_uncertain':bool(flight.get('source_tail_uncertain',False)),
        'observed_export_boundary':sanitize(boundary),
        'suspected_owner':sanitize(suspected_owner),'confidence':confidence,
        'retained_evidence_confidence':retained_confidence,
        'cause_status':cause_status,'cause_scope':finding_scope,
        'candidate_causes_may_be_incomplete':bool(loss),'candidate_causes':candidate_causes,
        'supporting_evidence_ids':support_refs,'control_state':sanitize(control_state),
        'physical_input_state':physical_input_state,'expected_missing_evidence':missing,
        'next_targeted_verification':sanitize(next_test),'diagnostic_coverage_gaps':gap_summary,
        'snapshot_names':snapshot_names,'snapshot_omissions':snapshot_omissions,
        'settled_action_count':proven_facts.get('settled_action_count',0),
        'unresolved_actions':unresolved_actions,'latest_included_pre_action_outcome':latest_included_pre_action_outcome,
        'latest_included_action_lifecycle':latest_included_action_lifecycle,
        'pre_action_outcomes_omitted':action_lifecycles.get('pre_action_outcomes_omitted',0),
        'action_lifecycles_omitted':action_lifecycles.get('actions_omitted',0),
        'recovery_attempt_count':recovery_count,
        'historical_similarity_case_ids':historical_ids,'workflow_lifecycle_status':workflow_lifecycle.get('status'),
        'workflow_current_phase':workflow_lifecycle.get('current_phase'),'turn_handoff_status':turn_handoff.get('status'),
        'evidence_completeness':evidence_completeness,
        'observer_errors':list(observer.errors[-10:]),
        'authority_note':'Diagnostic conclusions are evidence indexes only and never grant gameplay authority.',
    }

    gpt_summary_blob=_serialized(gpt_summary)
    gpt_summary_sha256=sha256(gpt_summary_blob).hexdigest()
    read_first=(
        '# ANKA diagnostic incident\n\n'
        f'**Code:** {sanitize(code)}\n\n'
        f'**Attempted operation:** {sanitize(attempted_operation)}\n\n'
        f'**First divergence:** {sanitize(first_boundary)}\n\n'
        f'**Finding status:** {gpt_finding_status}; scope={finding_scope}; absence_conclusive={not bool(loss)}.\n\n'
        + ('**Crash-tail warning:** source tail is uncertain; missing post-crash events cannot prove that an action failed or never happened.\n\n' if flight.get('source_tail_uncertain',False) else '')
        + f'**Observed/export boundary:** {sanitize(boundary)}\n\n'
        f'**Suspected owner:** {sanitize(suspected_owner)}\n\n'
        f'**Confidence:** {confidence}\n\n'
        f'**Cause status:** {cause_status}; scope={finding_scope}; candidates_may_be_incomplete={bool(loss)}; candidates={sanitize(candidate_causes) if candidate_causes else "none established"}.\n\n'
        f'**Supporting evidence IDs:** {sanitize(support_refs) if support_refs else "none uniquely identified"}\n\n'
        f'**Control state:** {sanitize(control_state)}\n\n'
        f'**Physical input state:** {physical_input_state} (from included diagnostic evidence; UNKNOWN if absent).\n\n'
        f'**Detail:** {sanitize(detail)}\n\n'
        f'**Expected-but-missing evidence:** {sanitize(missing) if missing else "not uniquely established"}\n\n'
        f'**Next targeted verification:** {sanitize(next_test)}\n\n'
        f'**Proven diagnostic facts:** {len(proven_facts.get("facts",[]))} observed trace edges; '
        f'{proven_facts.get("settled_action_count",0)} settled actions; unresolved={sanitize(unresolved_actions)}.\n\n'
        f'**Recorded recovery/watchdog attempts:** {recovery_count}.\n\n'
        f'**Workflow lifecycle index:** {workflow_lifecycle.get("status")} at phase {workflow_lifecycle.get("current_phase")}; next={sanitize(workflow_lifecycle.get("next_expected_transition"))}.\n\n'
        f'**End Turn handoff index:** {turn_handoff.get("status")}; next_owner={sanitize(turn_handoff.get("next_owner_account_id"))}.\n\n'
        f'**Latest included pre-action causal outcome:** {sanitize(latest_included_pre_action_outcome) if latest_included_pre_action_outcome else "none included"}; omitted={action_lifecycles.get("pre_action_outcomes_omitted",0)}.\n\n'
        f'**Latest included action lifecycle:** {sanitize(latest_included_action_lifecycle) if latest_included_action_lifecycle else "none included"}; omitted={action_lifecycles.get("actions_omitted",0)}.\n\n'
        f'**Historical similarity hints (not root-cause proof):** {sanitize(historical_ids) if historical_ids else "none"}.\n\n'
        f'**Evidence completeness:** {evidence_completeness}; flight recorder overwrites={flight["recent_overwrites"]}; '
        f'journal drops={observer.dropped}; size omissions={flight["timeline_events_omitted_for_size"]}.\n\n'
        f'**Diagnostic coverage gaps:** {sanitize(gap_summary) if gap_summary else "none declared"}.\n\n'
        f'**Available shipped bounded snapshots:** {sanitize(snapshot_names) if snapshot_names else "none"}.\n\n'
        f'**Snapshot omissions:** {sanitize(snapshot_omissions) if snapshot_omissions else "none"}.\n\n'
        '**Machine-readable forensic index:** `analysis/gpt_summary.json`.\n\n'
        f'**Machine summary SHA-256:** {gpt_summary_sha256}\n\n'
        f'**Observer health:** storage_available={flight["persistent_storage_available"]}; errors={sanitize(list(observer.errors[-10:]))}.\n\n'
        + ('**INCIDENT_PRIMARY_EXPORT_FAILED:** primary run-folder ZIP write failed; this is the bounded fallback artifact.\n\n' if primary_export_failed else '')
        + 'Raw packet captures, credentials and environment dumps are excluded by default. '
        'The evidence matrix explicitly declares missing/partial sections; observer output never grants gameplay authority.\n'
    ).encode('utf8')

    artifacts={
        'diagnosis.json':_serialized(diagnosis),'evidence_matrix.json':_serialized(evidence_payload),
        'timeline.jsonl':timeline,'GPT_READ_FIRST.md':read_first,'run_manifest.json':_serialized(run_manifest),
        'analysis/diagnosis.json':_serialized({**diagnosis,'physical_input_state':physical_input_state}),
        'analysis/boundary_graph.json':_serialized(graph_payload),
        'analysis/party_ready.json':_serialized(party_ready_payload),
        'analysis/action_lifecycles.json':_serialized(action_lifecycles),
        'analysis/evidence_gaps.json':_serialized({'schema_version':1,'gaps':gaps}),
        'analysis/historical_matches.json':_serialized(historical_matches),
        'analysis/recovery_history.json':_serialized(recovery_history),
        'analysis/workflow_lifecycle.json':_serialized(workflow_lifecycle),
        'analysis/turn_handoff.json':_serialized(turn_handoff),
        'analysis/proven_facts.json':_serialized(proven_facts),
        'analysis/next_verification.json':_serialized(next_verification),
        'analysis/snapshot_index.json':_serialized({'schema_version':1,'snapshots':snapshot_names,'omitted':snapshot_omissions,
            'note':'Only shipped snapshot names are listed as available. Omitted snapshots are explicit; all snapshot content is bounded, sanitized diagnostic context and is not gameplay authority.'}),
        'analysis/gpt_summary.json':gpt_summary_blob,
        'logs/relevant_timeline.jsonl':timeline,'logs/priority_timeline.jsonl':priority_timeline,
        'logs/relevant_errors.jsonl':error_lines,
        'metadata/flight_recorder.json':_serialized({'schema_version':1,**flight}),
        'metadata/artifact_integrity.json':_serialized({'schema_version':1,'verification':'see manifest.json'}),
        'metadata/capture_protocol_summary.json':_serialized({'schema_version':1,'raw_protocol_included':False,'status':sections['protocol']}),
        'analysis/evidence_request.json':_serialized({'schema_version':1,
            'raw_network_evidence_required_for_protocol_reverse_engineering': (sections['protocol']!='PRESENT' or code=='CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED'),
            'note':'Raw packet payloads remain excluded by default; this file states when additional primary evidence is required.'}),
        **snapshot_artifacts,
    }
    return artifacts,sections


def _emergency_artifacts(observer,code:str,boundary:str,detail:str,control_state:str,analysis_error:str)->tuple[dict[str,bytes],dict]:
    """Simple second-line envelope used when advanced forensic construction fails."""
    try:events,timeline,priority_timeline,flight=_bounded_timeline(observer,incident_code=code,incident_boundary=boundary)
    except Exception:
        events=[];timeline=b'';priority_timeline=b''
        flight={'recent_capacity':0,'priority_capacity':0,'pinned_capacity':0,'recent_in_memory':0,'priority_in_memory':0,'pinned_in_memory':0,
                'recent_overwrites':0,'priority_overwrites':0,'pinned_context_omissions':0,'sanitization_truncations':0,'timeline_events_included':0,
                'priority_events_included':0,'pinned_events_included':0,'timeline_events_omitted_for_size':0,
                'journal_dropped_events':int(getattr(observer,'dropped',0)),
                'journal_queue_drops':int(getattr(observer,'journal_queue_drops',0)),
                'priority_journal_queue_drops':int(getattr(observer,'priority_journal_queue_drops',0)),
                'journal_pending':int(getattr(observer,'journal_pending',0)),
                'priority_journal_pending':int(getattr(observer,'priority_journal_pending',0)),
                'persistent_storage_available':bool(getattr(observer,'available',False)),
                'source_tail_uncertain':bool(getattr(observer,'source_tail_uncertain',False))}
    errors=list(getattr(observer,'errors',()))[-10:]+['ADVANCED_ANALYSIS_FAILED:'+analysis_error]
    physical_input_state=_aggregate_physical_input_state(events)
    diagnosis={
        'schema_version':2,'failure_code':sanitize(code),'first_divergent_boundary':sanitize(boundary),
        'suspected_owner':'anka_observability','confidence':'UNDETERMINED',
        'supporting_evidence_ids':tuple(e.get('event_id') for e in events if e.get('severity') in ('ERROR','CRITICAL','SAFETY'))[-20:],
        'contradicting_evidence_ids':(), 'missing_evidence':('ADVANCED_FORENSIC_ANALYSIS',),
        'control_state':sanitize(control_state),'recommended_next_test':'Inspect the included bounded timeline and rerun the forensic analyzer offline.',
        'candidate_causes':('ADVANCED_ANALYSIS_FAILED',),'explanation':sanitize(detail),
        'observer_dropped_events':int(getattr(observer,'dropped',0)),'observer_errors':errors,
    }
    sections={k:'MISSING' for k in CRITICAL_SECTIONS};sections['observability']='EXPORT_FAILED'
    run_manifest={'schema_version':2,'run_id':observer.run_id,'invocation_id':observer.invocation_id,
                  'control_state':control_state,'observer_dropped_events':int(getattr(observer,'dropped',0)),
                  'observer_errors':errors,'bounded_recent_event_count':len(events),'physical_input_state':physical_input_state,
                  'flight_recorder':flight,'evidence_completeness':'PARTIAL'}
    read_first=(
        '# ANKA emergency diagnostic incident\n\n'
        f'**Code:** {sanitize(code)}\n\n**Observed boundary:** {sanitize(boundary)}\n\n'
        '**Forensic status:** ADVANCED_ANALYSIS_FAILED. The original application failure is preserved; '
        'no root cause is asserted by this fallback.\n\n'
        f'**Control state:** {sanitize(control_state)}\n\n'
        f'**Physical input state:** {physical_input_state} (most conservative state present in included evidence).\n\n'
        f'**Detail:** {sanitize(detail)}\n\n'
        'Use the included bounded timeline as primary evidence. Raw packet payloads and secrets are excluded.\n'
    )
    emergency_gpt_summary={'schema_version':1,'incident_code':sanitize(code),'attempted_operation':sanitize(code),
        'finding_status':'ADVANCED_ANALYSIS_UNAVAILABLE','first_divergence':'NOT_ESTABLISHED',
        'observed_export_boundary':sanitize(boundary),'suspected_owner':'anka_observability','confidence':'UNDETERMINED',
        'cause_status':'UNDETERMINED','cause_scope':'INCLUDED_EVIDENCE_ONLY',
        'candidate_causes_may_be_incomplete':True,'candidate_causes':[],
        'supporting_evidence_ids':list(diagnosis.get('supporting_evidence_ids',())),'control_state':sanitize(control_state),
        'physical_input_state':physical_input_state,'expected_missing_evidence':['ADVANCED_FORENSIC_ANALYSIS'],
        'next_targeted_verification':'Rerun forensic analysis offline.','diagnostic_coverage_gaps':['observability=EXPORT_FAILED'],
        'snapshot_names':[],'settled_action_count':0,'unresolved_actions':[],'latest_included_pre_action_outcome':None,
        'latest_included_action_lifecycle':None,'pre_action_outcomes_omitted':0,'action_lifecycles_omitted':0,
        'recovery_attempt_count':0,
        'historical_similarity_case_ids':[],'evidence_completeness':'PARTIAL','observer_errors':errors,
        'authority_note':'Diagnostic conclusions are evidence indexes only and never grant gameplay authority.'}
    emergency_gpt_blob=_serialized(emergency_gpt_summary)
    emergency_gpt_sha256=sha256(emergency_gpt_blob).hexdigest()
    read_first=read_first.replace(
        'Use the included bounded timeline as primary evidence. Raw packet payloads and secrets are excluded.\n',
        'Use the included bounded timeline as primary evidence. Raw packet payloads and secrets are excluded.\n\n'
        f'**Machine-readable forensic index:** `analysis/gpt_summary.json`.\n\n'
        f'**Machine summary SHA-256:** {emergency_gpt_sha256}\n')
    read_first=read_first.encode('utf8')
    artifacts={
        'diagnosis.json':_serialized(diagnosis),'analysis/diagnosis.json':_serialized(diagnosis),
        'evidence_matrix.json':_serialized({'schema_version':2,'sections':sections}),
        'timeline.jsonl':timeline,'logs/relevant_timeline.jsonl':timeline,'logs/priority_timeline.jsonl':priority_timeline,
        'logs/relevant_errors.jsonl':b''.join(_json_line(e) for e in events if e.get('severity') in ('ERROR','CRITICAL','SAFETY')),
        'GPT_READ_FIRST.md':read_first,'run_manifest.json':_serialized(run_manifest),
        'analysis/boundary_graph.json':_serialized({'schema_version':1,'operation':None,'edges':[]}),
        'analysis/party_ready.json':_serialized({'schema_version':1,'status':'ANALYSIS_UNAVAILABLE','required_accounts':[],'account_graphs':[],'shared_graph':[],'matched_event_ids':[]}),
        'analysis/action_lifecycles.json':_serialized({'schema_version':1,'actions':[],'pre_action_outcomes':[],
            'total_pre_action_outcome_count':0,'pre_action_outcomes_omitted':0,
            'authorization_blockers':[],'status':'ANALYSIS_UNAVAILABLE'}),
        'analysis/evidence_gaps.json':_serialized({'schema_version':1,'gaps':[{'section':'observability','status':'EXPORT_FAILED'}]}),
        'analysis/historical_matches.json':_serialized({'schema_version':1,'matches':[],'note':'Advanced historical similarity analysis unavailable.'}),
        'analysis/recovery_history.json':_serialized({'schema_version':1,'attempts':[],'count':0,'note':'Advanced recovery analysis unavailable.'}),
        'analysis/workflow_lifecycle.json':_serialized({'schema_version':1,'status':'ANALYSIS_UNAVAILABLE','current_phase':None,'transitions':[],'matched_event_ids':[]}),
        'analysis/turn_handoff.json':_serialized({'schema_version':1,'status':'ANALYSIS_UNAVAILABLE','action_id':None,'event_ids':[]}),
        'analysis/proven_facts.json':_serialized({'schema_version':1,'facts':[],'settled_action_count':0,'unresolved_actions':[],'note':'Advanced fact extraction unavailable.'}),
        'analysis/next_verification.json':_serialized({'schema_version':1,'recommended_next_test':'Rerun forensic analysis offline.','missing_evidence':['ADVANCED_FORENSIC_ANALYSIS']}),
        'analysis/snapshot_index.json':_serialized({'schema_version':1,'snapshots':[], 'note':'Advanced snapshot indexing unavailable.'}),
        'analysis/gpt_summary.json':emergency_gpt_blob,
        'analysis/evidence_request.json':_serialized({'schema_version':1,'raw_network_evidence_required_for_protocol_reverse_engineering':False}),
        'metadata/flight_recorder.json':_serialized({'schema_version':1,**flight}),
        'metadata/artifact_integrity.json':_serialized({'schema_version':1,'verification':'see manifest.json'}),
        'metadata/capture_protocol_summary.json':_serialized({'schema_version':1,'raw_protocol_included':False,'status':'MISSING'}),
    }
    return artifacts,sections


def _write_zip(path:Path, artifacts:dict[str,bytes], manifest:dict) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(path,'w',compression=ZIP_DEFLATED) as z:
        for name,data in artifacts.items():z.writestr(name,data)
        z.writestr('manifest.json',_serialized(manifest))


def _manifest(observer,id_:str,artifacts:dict[str,bytes],sections:dict,*,primary_failed:bool,advanced_failed:bool)->dict:
    # The outer manifest is the first file an operator/verifier may inspect. Its
    # completeness claim must be identical to the authoritative run manifest,
    # including recorder loss/overwrites—not merely the subsystem evidence matrix.
    completeness='PARTIAL' if any(v not in ('PRESENT','NOT_APPLICABLE') for v in sections.values()) else 'PRESENT'
    try:
        run_meta=json.loads(artifacts.get('run_manifest.json',b'{}'))
        run_completeness=run_meta.get('evidence_completeness') if isinstance(run_meta,dict) else None
        if run_completeness in EVIDENCE_STATUS:completeness=run_completeness
    except Exception:
        completeness='PARTIAL'
    m={'schema_version':BUNDLE_SCHEMA,'incident_id':id_,'run_id':observer.run_id,
       'created_utc':now_utc(),'source':'DEFINITIVE_OBSERVABILITY_Q8','files':{},
       'raw_protocol_included':False,'external_upload':False,
       'completeness':completeness,
       'dropped_events':int(getattr(observer,'dropped',0)),'primary_export_failed':primary_failed,
       'advanced_analysis_failed':advanced_failed}
    for name,content in artifacts.items():m['files'][name]={'sha256':sha256(content).hexdigest(),'bytes':len(content)}
    return m


def export_incident(observer,code:str,*,boundary:str,detail:str='',trace_spec:OperationTraceSpec|None=None,control_state:str='UNKNOWN')->Path:
    if not re.fullmatch(r'[A-Z][A-Z0-9_]{2,80}',code):raise ValueError('INVALID_INCIDENT_CODE')
    id_='incident-'+uuid4().hex
    primary=observer.folder/'incidents'/(id_+'.zip')
    advanced_failed=False
    try:
        artifacts,sections=_build_artifacts(observer,code,boundary,detail,trace_spec=trace_spec,control_state=control_state,primary_export_failed=False)
    except Exception as exc:
        advanced_failed=True
        artifacts,sections=_emergency_artifacts(observer,code,boundary,detail,control_state,type(exc).__name__.upper())
    manifest=_manifest(observer,id_,artifacts,sections,primary_failed=False,advanced_failed=advanced_failed)
    try:
        _write_zip(primary,artifacts,manifest);return primary
    except Exception as exc:
        # ZIP construction/compression/path failures are observer failures, not
        # application authority.  RuntimeError/ValueError from the ZIP layer are
        # just as important to contain as OSError.
        fallback=Path(gettempdir())/'ANKA_NEXT'/'incidents'/(id_+'.zip')
        # Rebuild normal artifacts so the evidence matrix truthfully marks the
        # primary export path as failed. If that advanced rebuild fails too, the
        # emergency envelope remains independent of the analyzer.
        try:
            artifacts,sections=_build_artifacts(observer,code,boundary,detail,trace_spec=trace_spec,control_state=control_state,primary_export_failed=True)
        except Exception as analysis_exc:
            advanced_failed=True
            artifacts,sections=_emergency_artifacts(observer,code,boundary,detail,control_state,type(analysis_exc).__name__.upper())
        manifest=_manifest(observer,id_,artifacts,sections,primary_failed=True,advanced_failed=advanced_failed)
        _write_zip(fallback,artifacts,manifest);return fallback


def _parse_jsonl(blob:bytes,add,prefix:str)->list[dict]:
    rows=[]
    try:text=blob.decode('utf8')
    except UnicodeDecodeError:
        add(prefix+'_UTF8_INVALID');return rows
    for i,line in enumerate(text.splitlines(),1):
        if not line:continue
        if len(line.encode('utf8'))>8192:add(prefix+'_LINE_OVERSIZED');continue
        try:obj=json.loads(line)
        except json.JSONDecodeError:
            add(prefix+'_JSON_INVALID');continue
        if not isinstance(obj,dict):add(prefix+'_ROW_INVALID');continue
        rows.append(obj)
    return rows


def verify_incident(path:Path)->dict:
    """Read-only ZIP integrity/privacy/causal-shape check.

    This verifies artifact integrity and internal evidence references, never the
    factual truth of a gameplay diagnosis.
    """
    errors=[]
    def add(code:str)->None:
        if code not in errors and len(errors)<100:errors.append(code)
    try:
        with ZipFile(path) as z:
            names=z.namelist()
            if len(set(names))!=len(names):add('DUPLICATE_ZIP_ENTRIES')
            if len({name.casefold() for name in names})!=len(names):add('CASE_INSENSITIVE_ZIP_COLLISION')
            if len(names)>96:add('TOO_MANY_ENTRIES')
            for name in names:
                if name.startswith('/') or '\\' in name or '..' in name.split('/'):add('UNSAFE_ZIP_PATH:'+name[:160])
            if 'manifest.json' not in names:add('MISSING_MANIFEST');return {'status':'FAIL','errors':errors}
            info=z.getinfo('manifest.json')
            if info.file_size>65536:add('OVERSIZED_MANIFEST');return {'status':'FAIL','errors':errors}
            if sum(i.file_size for i in z.infolist())>3*1024*1024:add('OVERSIZED_BUNDLE_UNCOMPRESSED');return {'status':'FAIL','errors':errors}
            try:m=json.loads(z.read('manifest.json'))
            except (json.JSONDecodeError,UnicodeDecodeError,ValueError):add('MANIFEST_JSON_INVALID');return {'status':'FAIL','errors':errors}
            if not isinstance(m,dict):add('MANIFEST_SHAPE_INVALID');return {'status':'FAIL','errors':errors}
            if has_unredacted_sensitive_data(m):add('UNREDACTED_SENSITIVE_DATA:manifest.json')
            if m.get('schema_version') not in (1,2):add('SCHEMA_MISMATCH')
            if m.get('schema_version')==2:
                missing_required=sorted(REQUIRED_SCHEMA2_FILES-set(names))
                for required_name in missing_required[:32]:add('MISSING_REQUIRED_ARTIFACT:'+required_name)
            declared=m.get('files')
            if not isinstance(declared,dict):add('MANIFEST_FILES_INVALID');declared={}
            if set(names)-{'manifest.json'}!=set(declared):add('MANIFEST_FILE_SET_MISMATCH')
            for name,receipt in declared.items():
                if not isinstance(name,str):add('MANIFEST_FILE_NAME_INVALID');continue
                if not isinstance(receipt,dict):add('MANIFEST_FILE_RECEIPT_INVALID:'+name[:120]);continue
                if name not in names:continue
                i=z.getinfo(name)
                if i.file_size>1024*1024:add('OVERSIZED_FILE:'+name[:120]);continue
                data=z.read(name)
                expected_hash=receipt.get('sha256');expected_bytes=receipt.get('bytes')
                if (not isinstance(expected_hash,str) or len(expected_hash)!=64 or type(expected_bytes) is not int or expected_bytes<0):
                    add('MANIFEST_FILE_RECEIPT_INVALID:'+name[:120]);continue
                if expected_hash!=sha256(data).hexdigest() or expected_bytes!=len(data):add('BAD_CHECKSUM:'+name[:120])
                # A hostile bundle can update both a file and its checksum. The
                # verifier therefore re-applies the privacy invariant to decoded
                # artifacts instead of treating hashes as a secrecy guarantee.
                try:
                    if name.endswith('.json'):
                        privacy_obj=json.loads(data)
                        if has_unredacted_sensitive_data(privacy_obj):add('UNREDACTED_SENSITIVE_DATA:'+name[:120])
                    elif name.endswith('.jsonl'):
                        for privacy_line in data.decode('utf8').splitlines():
                            if privacy_line and has_unredacted_sensitive_data(json.loads(privacy_line)):
                                add('UNREDACTED_SENSITIVE_DATA:'+name[:120]);break
                    elif name.endswith('.md'):
                        if has_unredacted_sensitive_data(data.decode('utf8')):add('UNREDACTED_SENSITIVE_DATA:'+name[:120])
                except (json.JSONDecodeError,UnicodeDecodeError,ValueError,TypeError):
                    # Dedicated structural parsers below report malformed data.
                    pass

            if m.get('schema_version')==2 and 'GPT_READ_FIRST.md' in names and 'analysis/gpt_summary.json' in names:
                try:
                    read_first_text=z.read('GPT_READ_FIRST.md').decode('utf8')
                    summary_hash=sha256(z.read('analysis/gpt_summary.json')).hexdigest()
                    expected_marker='**Machine summary SHA-256:** '+summary_hash
                    if expected_marker not in read_first_text:add('GPT_READ_FIRST_SUMMARY_HASH_MISMATCH')
                except UnicodeDecodeError:
                    add('GPT_READ_FIRST_UTF8_INVALID')

            matrix=None
            if 'evidence_matrix.json' in names:
                try:matrix=json.loads(z.read('evidence_matrix.json'))
                except (json.JSONDecodeError,UnicodeDecodeError,ValueError):add('EVIDENCE_MATRIX_JSON_INVALID')
                if matrix is not None:
                    if not isinstance(matrix,dict) or not isinstance(matrix.get('sections'),dict):add('EVIDENCE_MATRIX_SHAPE_INVALID')
                    else:
                        sections=matrix['sections'];present=set(sections)
                        required=set(CRITICAL_SECTIONS if m.get('schema_version')==2 else ('bootstrap','configuration','identity','capture','protocol','canonical','live_state','coordination','decision','execution','outcome'))
                        if not required.issubset(present):add('INCOMPLETE_EVIDENCE_MATRIX')
                        if any(not isinstance(k,str) or v not in EVIDENCE_STATUS for k,v in sections.items()):add('BAD_EVIDENCE_STATUS')
            if m.get('raw_protocol_included') is not False:add('RAW_PROTOCOL_DEFAULT_POLICY_VIOLATION')

            # Definitive bundles must contain valid line-delimited diagnostic DTOs
            # and all diagnosis evidence references must point to included rows.
            # `timeline.jsonl` and `logs/relevant_timeline.jsonl` are deliberate
            # aliases for GPT/operator ergonomics; disagreement means the bundle
            # is self-contradictory even if both files are individually valid.
            rows=[];priority_rows=[];error_rows=[];run_manifest=None;recorder_loss=False
            relevant_blob=z.read('logs/relevant_timeline.jsonl') if 'logs/relevant_timeline.jsonl' in names else b''
            if 'logs/relevant_timeline.jsonl' in names:
                rows=_parse_jsonl(relevant_blob,add,'TIMELINE')
            if 'timeline.jsonl' in names:
                timeline_blob=z.read('timeline.jsonl')
                _parse_jsonl(timeline_blob,add,'TIMELINE_ALIAS')
                if timeline_blob!=relevant_blob:add('TIMELINE_ALIAS_MISMATCH')
            if 'logs/priority_timeline.jsonl' in names:
                priority_rows=_parse_jsonl(z.read('logs/priority_timeline.jsonl'),add,'PRIORITY_TIMELINE')
            if 'logs/relevant_errors.jsonl' in names:
                error_rows=_parse_jsonl(z.read('logs/relevant_errors.jsonl'),add,'ERROR_TIMELINE')
            event_ids=set();seqs=set();run_id=None;invocation_id=None;events_by_id={};parsed_events_by_id={};last_primary_seq=None;last_primary_mono=None
            if 'run_manifest.json' in names:
                try:run_manifest=json.loads(z.read('run_manifest.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):run_manifest={};add('RUN_MANIFEST_JSON_INVALID')
                if isinstance(run_manifest,dict):
                    run_id=run_manifest.get('run_id');invocation_id=run_manifest.get('invocation_id')
                    if not isinstance(run_id,str) or DIAGNOSTIC_RUN_ID_RE.fullmatch(run_id) is None:
                        add('RUN_MANIFEST_RUN_ID_INVALID')
                    if not isinstance(invocation_id,str) or DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(invocation_id) is None:
                        add('RUN_MANIFEST_INVOCATION_ID_INVALID')
                    flight=run_manifest.get('flight_recorder',{})
                    if isinstance(flight,dict):
                        recorder_loss=any(int(flight.get(k,0) or 0)>0 for k in ('recent_overwrites','priority_overwrites','pinned_context_omissions','sanitization_truncations','timeline_events_omitted_for_size','journal_dropped_events','journal_queue_drops','priority_journal_queue_drops','snapshot_export_omissions')) or not bool(flight.get('persistent_storage_available',True)) or bool(flight.get('source_tail_uncertain',False))
                        if recorder_loss and run_manifest.get('evidence_completeness')=='PRESENT':add('LOSS_CLAIMED_COMPLETE')
            for obj in rows:
                try:event=DiagnosticEvent.from_dict(obj)
                except (TypeError,ValueError):add('TIMELINE_EVENT_INVALID');continue
                if DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.event_id) is None:add('TIMELINE_EVENT_ID_INVALID')
                if event.parent_event_id is not None and DIAGNOSTIC_EVENT_ID_RE.fullmatch(event.parent_event_id) is None:
                    add('TIMELINE_PARENT_EVENT_ID_INVALID')
                if DIAGNOSTIC_INVOCATION_ID_RE.fullmatch(event.invocation_id) is None:add('TIMELINE_INVOCATION_ID_INVALID')
                if event.run_id is None or DIAGNOSTIC_RUN_ID_RE.fullmatch(event.run_id) is None:add('TIMELINE_RUN_ID_INVALID')
                try:
                    stamp=datetime.fromisoformat(event.occurred_utc.replace('Z','+00:00'))
                    if stamp.tzinfo is None:raise ValueError('naive')
                except (TypeError,ValueError):add('TIMELINE_TIMESTAMP_INVALID')
                if event.event_id in event_ids:add('TIMELINE_EVENT_ID_DUPLICATE')
                if last_primary_seq is not None and event.producer_seq<=last_primary_seq:add('TIMELINE_ORDER_INVALID')
                if last_primary_mono is not None and event.monotonic_ns<last_primary_mono:add('TIMELINE_MONOTONIC_REGRESSION')
                last_primary_seq=event.producer_seq;last_primary_mono=event.monotonic_ns
                event_ids.add(event.event_id);events_by_id[event.event_id]=obj;parsed_events_by_id[event.event_id]=event
                seq_key=(event.invocation_id,event.run_id,event.producer_seq)
                if seq_key in seqs:add('TIMELINE_PRODUCER_SEQ_DUPLICATE')
                seqs.add(seq_key)
                if run_id is not None and event.run_id!=run_id:add('TIMELINE_RUN_ID_MISMATCH')
                if invocation_id is not None and event.invocation_id!=invocation_id:add('TIMELINE_INVOCATION_ID_MISMATCH')
            manifest_run_id=m.get('run_id')
            if manifest_run_id is None:
                if m.get('schema_version')==2:add('MANIFEST_RUN_ID_INVALID')
            elif not isinstance(manifest_run_id,str) or DIAGNOSTIC_RUN_ID_RE.fullmatch(manifest_run_id) is None:
                add('MANIFEST_RUN_ID_INVALID')
            if manifest_run_id is not None and run_id is not None and manifest_run_id!=run_id:add('MANIFEST_RUN_ID_MISMATCH')
            if isinstance(run_manifest,dict):
                if run_manifest.get('physical_input_state')!=_aggregate_physical_input_state(rows):
                    add('RUN_MANIFEST_PHYSICAL_STATE_MISMATCH')
                if m.get('completeness')!=run_manifest.get('evidence_completeness'):
                    add('MANIFEST_COMPLETENESS_MISMATCH')
                if m.get('dropped_events')!=run_manifest.get('observer_dropped_events'):
                    add('MANIFEST_DROPPED_EVENTS_MISMATCH')

            # Secondary timeline views are convenience indexes, not independent
            # evidence stores. They must be exact subsets of the shipped primary
            # timeline so GPT cannot be shown a priority/error event that is absent
            # from the evidence set used by the forensic analyzers.
            for prefix,secondary in (('PRIORITY_TIMELINE',priority_rows),('ERROR_TIMELINE',error_rows)):
                seen_secondary=set()
                for obj in secondary:
                    try:event=DiagnosticEvent.from_dict(obj)
                    except (TypeError,ValueError):add(prefix+'_EVENT_INVALID');continue
                    if event.event_id in seen_secondary:add(prefix+'_EVENT_ID_DUPLICATE')
                    seen_secondary.add(event.event_id)
                    primary=events_by_id.get(event.event_id)
                    if primary is None:add(prefix+'_EVENT_NOT_IN_PRIMARY');continue
                    if primary!=obj:add(prefix+'_EVENT_MISMATCH')
                    if prefix=='ERROR_TIMELINE' and event.severity not in ('ERROR','CRITICAL','SAFETY'):
                        add('ERROR_TIMELINE_NON_ERROR_EVENT')
                positions={event_id:i for i,event_id in enumerate(events_by_id)}
                ordered_positions=[positions.get(row.get('event_id')) for row in secondary if isinstance(row,dict) and row.get('event_id') in positions]
                if ordered_positions!=sorted(ordered_positions):add(prefix+'_ORDER_INVALID')
            priority_ids={row.get('event_id') for row in priority_rows if isinstance(row,dict)}
            required_priority_ids={event_id for event_id,event in parsed_events_by_id.items() if is_priority_event(event)}
            if not required_priority_ids.issubset(priority_ids):add('PRIORITY_TIMELINE_INCOMPLETE')
            error_ids={row.get('event_id') for row in error_rows if isinstance(row,dict)}
            required_error_ids={event_id for event_id,event in parsed_events_by_id.items() if event.severity in ('ERROR','CRITICAL','SAFETY')}
            if error_ids!=required_error_ids:add('ERROR_TIMELINE_INCOMPLETE')
            if isinstance(run_manifest,dict):
                flight=run_manifest.get('flight_recorder',{})
                if run_manifest.get('bounded_recent_event_count')!=len(rows):add('RUN_MANIFEST_EVENT_COUNT_MISMATCH')
                if isinstance(flight,dict):
                    if flight.get('timeline_events_included')!=len(rows):add('FLIGHT_TIMELINE_COUNT_MISMATCH')
                    if flight.get('priority_events_included')!=len(priority_rows):add('FLIGHT_PRIORITY_COUNT_MISMATCH')
                    trigger_ids=flight.get('incident_trigger_event_ids',[])
                    trigger_count=flight.get('incident_trigger_events_included',0)
                    if type(trigger_count) is not int or trigger_count < 0 or trigger_count > 1:
                        add('FLIGHT_TRIGGER_COUNT_INVALID')
                    if not isinstance(trigger_ids,list) or any(not isinstance(x,str) for x in trigger_ids):
                        add('FLIGHT_TRIGGER_IDS_INVALID')
                    else:
                        if len(trigger_ids)!=trigger_count:add('FLIGHT_TRIGGER_COUNT_MISMATCH')
                        if len(set(trigger_ids))!=len(trigger_ids):add('FLIGHT_TRIGGER_ID_DUPLICATE')
                        if any(x not in event_ids for x in trigger_ids):add('FLIGHT_TRIGGER_NOT_IN_PRIMARY')
                        if any(x not in priority_ids for x in trigger_ids):add('FLIGHT_TRIGGER_NOT_IN_PRIORITY')
                    if any(has_diagnostic_truncation(row) for row in rows) and int(flight.get('sanitization_truncations',0) or 0)<1:
                        add('FLIGHT_SANITIZATION_TRUNCATION_UNDECLARED')

            # Redundant metadata files exist for GPT/operator ergonomics only.
            # They must agree with the authoritative run manifest/evidence matrix;
            # otherwise a validly checksummed bundle could still tell two stories.
            if 'metadata/flight_recorder.json' in names:
                try:flight_meta=json.loads(z.read('metadata/flight_recorder.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):flight_meta={};add('FLIGHT_METADATA_JSON_INVALID')
                if not isinstance(flight_meta,dict):
                    add('FLIGHT_METADATA_SHAPE_INVALID')
                elif isinstance(run_manifest,dict):
                    run_flight=run_manifest.get('flight_recorder',{})
                    comparable={k:v for k,v in flight_meta.items() if k!='schema_version'}
                    if not isinstance(run_flight,dict) or comparable!=run_flight:
                        add('FLIGHT_METADATA_MISMATCH')
            if 'metadata/capture_protocol_summary.json' in names:
                try:cp_meta=json.loads(z.read('metadata/capture_protocol_summary.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):cp_meta={};add('CAPTURE_PROTOCOL_SUMMARY_JSON_INVALID')
                if not isinstance(cp_meta,dict):
                    add('CAPTURE_PROTOCOL_SUMMARY_SHAPE_INVALID')
                else:
                    if cp_meta.get('raw_protocol_included') is not False:
                        add('CAPTURE_PROTOCOL_RAW_POLICY_MISMATCH')
                    if isinstance(matrix,dict) and isinstance(matrix.get('sections'),dict):
                        if cp_meta.get('status')!=matrix['sections'].get('protocol'):
                            add('CAPTURE_PROTOCOL_STATUS_MISMATCH')

            if 'analysis/evidence_gaps.json' in names:
                try:evidence_gaps=json.loads(z.read('analysis/evidence_gaps.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):evidence_gaps={};add('EVIDENCE_GAPS_JSON_INVALID')
                if not isinstance(evidence_gaps,dict) or not isinstance(evidence_gaps.get('gaps'),list):
                    add('EVIDENCE_GAPS_SHAPE_INVALID')
                elif isinstance(matrix,dict) and isinstance(matrix.get('sections'),dict) and not bool(m.get('advanced_analysis_failed')):
                    expected_gaps={key:value for key,value in matrix['sections'].items()
                                   if value not in ('PRESENT','NOT_APPLICABLE')}
                    actual_gaps={row.get('section'):row.get('status') for row in evidence_gaps.get('gaps',[])
                                 if isinstance(row,dict) and isinstance(row.get('section'),str)}
                    if len(actual_gaps)!=len(evidence_gaps.get('gaps',[])) or actual_gaps!=expected_gaps:
                        add('EVIDENCE_GAPS_DERIVATION_MISMATCH')

            snapshot_index={}
            if 'analysis/snapshot_index.json' in names:
                try:snapshot_index=json.loads(z.read('analysis/snapshot_index.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):snapshot_index={};add('SNAPSHOT_INDEX_JSON_INVALID')
                shipped=[]
                for snapshot_name in names:
                    if not snapshot_name.startswith('snapshots/') or not snapshot_name.endswith('.json'):continue
                    leaf=snapshot_name[len('snapshots/'):-len('.json')]
                    if '/' in leaf or not re.fullmatch(r'[a-z][a-z0-9_]{1,47}',leaf):
                        add('SNAPSHOT_FILE_NAME_INVALID');continue
                    try:
                        info=z.getinfo(snapshot_name)
                        if info.file_size>32768:add('SNAPSHOT_FILE_OVERSIZED')
                        payload=json.loads(z.read(snapshot_name))
                        if not isinstance(payload,dict):add('SNAPSHOT_PAYLOAD_INVALID')
                    except (json.JSONDecodeError,UnicodeDecodeError,ValueError):
                        add('SNAPSHOT_PAYLOAD_INVALID')
                    shipped.append(leaf)
                shipped=sorted(shipped)
                if not isinstance(snapshot_index,dict):add('SNAPSHOT_INDEX_SHAPE_INVALID')
                else:
                    declared_snapshots=snapshot_index.get('snapshots',[])
                    omitted_snapshots=snapshot_index.get('omitted',[])
                    if not isinstance(declared_snapshots,list) or any(not isinstance(x,str) for x in declared_snapshots):
                        add('SNAPSHOT_INDEX_SHAPE_INVALID')
                    elif declared_snapshots!=shipped:
                        add('SNAPSHOT_INDEX_SHIPPED_MISMATCH')
                    if not isinstance(omitted_snapshots,list):
                        add('SNAPSHOT_OMISSIONS_SHAPE_INVALID')
                    else:
                        omitted_names=[]
                        for row in omitted_snapshots:
                            if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not isinstance(row.get('reason'),str):
                                add('SNAPSHOT_OMISSIONS_SHAPE_INVALID');continue
                            omitted_names.append(row['name'])
                        if len(set(omitted_names))!=len(omitted_names):add('SNAPSHOT_OMISSIONS_DUPLICATE')
                        if set(omitted_names)&set(shipped):add('SNAPSHOT_OMISSION_CONFLICT')
                        if isinstance(run_manifest,dict):
                            flight=run_manifest.get('flight_recorder',{})
                            if isinstance(flight,dict) and int(flight.get('snapshot_export_omissions',0) or 0)!=len(omitted_names):
                                add('SNAPSHOT_OMISSION_COUNT_MISMATCH')

            diag={};root_diag={}
            if 'diagnosis.json' in names:
                try:root_diag=json.loads(z.read('diagnosis.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):root_diag={};add('ROOT_DIAGNOSIS_JSON_INVALID')
                if not isinstance(root_diag,dict):add('ROOT_DIAGNOSIS_SHAPE_INVALID')
            if 'analysis/diagnosis.json' in names:
                try:diag=json.loads(z.read('analysis/diagnosis.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):diag={};add('DIAGNOSIS_JSON_INVALID')
                if isinstance(diag,dict):
                    refs=diag.get('supporting_evidence_ids',diag.get('evidence_ids',[])) or []
                    if not isinstance(refs,(list,tuple)):add('DIAGNOSIS_EVIDENCE_REFS_INVALID')
                    elif any(not isinstance(x,str) or x not in event_ids for x in refs):add('DIAGNOSIS_EVIDENCE_REF_MISSING')
                    if isinstance(root_diag,dict):
                        analysis_legacy=dict(diag);analysis_legacy.pop('physical_input_state',None)
                        if root_diag!=analysis_legacy:add('DIAGNOSIS_ALIAS_MISMATCH')
            graph={}
            if 'analysis/boundary_graph.json' in names:
                try:graph=json.loads(z.read('analysis/boundary_graph.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):graph={};add('BOUNDARY_GRAPH_JSON_INVALID')
                if not isinstance(graph,dict) or not isinstance(graph.get('edges',[]),list):
                    add('BOUNDARY_GRAPH_SHAPE_INVALID')
                else:
                    for edge in graph.get('edges',[]):
                        if not isinstance(edge,dict):
                            add('BOUNDARY_GRAPH_EDGE_INVALID');continue
                        ref=edge.get('event_id')
                        if ref is not None and (not isinstance(ref,str) or ref not in event_ids):
                            add('BOUNDARY_GRAPH_EVIDENCE_REF_MISSING')
            if 'analysis/party_ready.json' in names:
                try:party=json.loads(z.read('analysis/party_ready.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):party={};add('PARTY_READY_JSON_INVALID')
                if isinstance(party,dict):
                    refs=party.get('matched_event_ids',[]) or []
                    if not isinstance(refs,(list,tuple)):add('PARTY_READY_EVIDENCE_REFS_INVALID')
                    elif any(not isinstance(x,str) or x not in event_ids for x in refs):add('PARTY_READY_EVIDENCE_REF_MISSING')
                    finding=party.get('finding')
                    if isinstance(finding,dict):
                        frefs=finding.get('supporting_evidence_ids',[]) or []
                        if any(not isinstance(x,str) or x not in event_ids for x in frefs):add('PARTY_READY_FINDING_REF_MISSING')
                    if not bool(m.get('advanced_analysis_failed')):
                        ready_accounts=tuple(dict.fromkeys(row.get('account_id') for row in rows
                            if row.get('event_name')=='ready.requested' and isinstance(row.get('account_id'),str)))
                        expected_party={'schema_version':1,'status':'NOT_APPLICABLE','required_accounts':list(ready_accounts),'account_graphs':[],'shared_graph':[],'matched_event_ids':[]}
                        if len(ready_accounts)>=2:
                            ready_result=PartyReadyAnalyzer().analyze(rows,ready_accounts,
                                control_state=(run_manifest.get('control_state','UNKNOWN') if isinstance(run_manifest,dict) else 'UNKNOWN'))
                            expected_party={'schema_version':1,'status':'DIVERGED' if ready_result.finding else 'COMPLETE',
                                'required_accounts':list(ready_accounts),'account_graphs':list(ready_result.account_graphs),
                                'shared_graph':list(ready_result.shared_graph),'matched_event_ids':list(ready_result.matched_event_ids),
                                'finding':ready_result.finding.to_dict() if ready_result.finding else None}
                        if _semantic_artifact(party)!=_semantic_artifact(expected_party):add('PARTY_READY_DERIVATION_MISMATCH')
            if 'analysis/recovery_history.json' in names:
                try:recovery=json.loads(z.read('analysis/recovery_history.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):recovery={};add('RECOVERY_HISTORY_JSON_INVALID')
                attempts=recovery.get('attempts',[]) if isinstance(recovery,dict) else None
                if not isinstance(attempts,list):add('RECOVERY_HISTORY_SHAPE_INVALID')
                else:
                    for row in attempts:
                        if not isinstance(row,dict):add('RECOVERY_HISTORY_ROW_INVALID');continue
                        ref=row.get('event_id')
                        if not isinstance(ref,str) or ref not in event_ids:add('RECOVERY_HISTORY_EVIDENCE_REF_MISSING')
                    if not bool(m.get('advanced_analysis_failed')):
                        try:
                            if recovery!=recovery_history_report(rows):add('RECOVERY_HISTORY_DERIVATION_MISMATCH')
                        except Exception:add('RECOVERY_HISTORY_RECOMPUTE_FAILED')
            facts={}
            if 'analysis/proven_facts.json' in names:
                try:facts=json.loads(z.read('analysis/proven_facts.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):facts={};add('PROVEN_FACTS_JSON_INVALID')
                rows_=facts.get('facts',[]) if isinstance(facts,dict) else None
                if not isinstance(rows_,list):add('PROVEN_FACTS_SHAPE_INVALID')
                else:
                    for row in rows_:
                        if not isinstance(row,dict):add('PROVEN_FACT_ROW_INVALID');continue
                        ref=row.get('event_id')
                        if not isinstance(ref,str) or ref not in event_ids:add('PROVEN_FACT_EVIDENCE_REF_MISSING')
            if 'analysis/workflow_lifecycle.json' in names:
                try:lifecycle=json.loads(z.read('analysis/workflow_lifecycle.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):lifecycle={};add('WORKFLOW_LIFECYCLE_JSON_INVALID')
                if not isinstance(lifecycle,dict):add('WORKFLOW_LIFECYCLE_SHAPE_INVALID')
                else:
                    refs=list(lifecycle.get('matched_event_ids',[]) or [])
                    for row in lifecycle.get('transitions',[]) or []:
                        if isinstance(row,dict) and isinstance(row.get('event_id'),str):refs.append(row['event_id'])
                    block=lifecycle.get('blocking_event')
                    if isinstance(block,dict) and isinstance(block.get('event_id'),str):refs.append(block['event_id'])
                    if any(not isinstance(ref,str) or ref not in event_ids for ref in refs):add('WORKFLOW_LIFECYCLE_EVIDENCE_REF_MISSING')
                    if not bool(m.get('advanced_analysis_failed')):
                        try:
                            if lifecycle!=workflow_lifecycle_report(rows):add('WORKFLOW_LIFECYCLE_DERIVATION_MISMATCH')
                        except Exception:add('WORKFLOW_LIFECYCLE_RECOMPUTE_FAILED')
            handoff={}
            if 'analysis/turn_handoff.json' in names:
                try:handoff=json.loads(z.read('analysis/turn_handoff.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):handoff={};add('TURN_HANDOFF_JSON_INVALID')
                if not isinstance(handoff,dict):add('TURN_HANDOFF_SHAPE_INVALID')
                else:
                    refs=handoff.get('event_ids',[]) or []
                    if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in event_ids for ref in refs):
                        add('TURN_HANDOFF_EVIDENCE_REF_MISSING')

                    if not bool(m.get('advanced_analysis_failed')):
                        try:
                            if handoff!=turn_handoff_report(rows):add('TURN_HANDOFF_DERIVATION_MISMATCH')
                        except Exception:add('TURN_HANDOFF_RECOMPUTE_FAILED')

            gpt={}
            if 'analysis/gpt_summary.json' in names:
                try:gpt=json.loads(z.read('analysis/gpt_summary.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):gpt={};add('GPT_SUMMARY_JSON_INVALID')
                if not isinstance(gpt,dict):add('GPT_SUMMARY_SHAPE_INVALID')
                else:
                    refs=gpt.get('supporting_evidence_ids',[]) or []
                    if not isinstance(refs,list) or any(not isinstance(x,str) or x not in event_ids for x in refs):
                        add('GPT_SUMMARY_EVIDENCE_REF_MISSING')
                    status=gpt.get('finding_status')
                    gpt_confidence=gpt.get('confidence')
                    retained_gpt_confidence=gpt.get('retained_evidence_confidence',gpt_confidence)
                    allowed_confidence=('HIGH','MEDIUM','LOW','UNDETERMINED')
                    if gpt_confidence not in allowed_confidence:add('GPT_SUMMARY_CONFIDENCE_INVALID')
                    if retained_gpt_confidence not in allowed_confidence:add('GPT_SUMMARY_RETAINED_CONFIDENCE_INVALID')
                    if status not in ('DIVERGENCE_IDENTIFIED','DIVERGENCE_CANDIDATE','NOT_ESTABLISHED','ADVANCED_ANALYSIS_UNAVAILABLE'):
                        add('GPT_SUMMARY_FINDING_STATUS_INVALID')
                    if status=='NOT_ESTABLISHED' and gpt.get('first_divergence')!='NOT_ESTABLISHED':
                        add('GPT_SUMMARY_FALSE_DIVERGENCE')
                    if status=='DIVERGENCE_CANDIDATE' and gpt.get('absence_is_conclusive') is not False:
                        add('GPT_SUMMARY_CANDIDATE_CONCLUSIVENESS_INVALID')
                    if isinstance(run_manifest,dict):
                        if gpt.get('physical_input_state')!=run_manifest.get('physical_input_state') and status!='ADVANCED_ANALYSIS_UNAVAILABLE':
                            add('GPT_SUMMARY_PHYSICAL_STATE_MISMATCH')
                        if gpt.get('evidence_completeness')!=run_manifest.get('evidence_completeness'):
                            add('GPT_SUMMARY_COMPLETENESS_MISMATCH')
                        if isinstance(snapshot_index,dict):
                            if gpt.get('snapshot_names')!=snapshot_index.get('snapshots',[]):
                                add('GPT_SUMMARY_SNAPSHOT_INDEX_MISMATCH')
                            if gpt.get('snapshot_omissions',[])!=snapshot_index.get('omitted',[]):
                                add('GPT_SUMMARY_SNAPSHOT_OMISSIONS_MISMATCH')
                        if status!='ADVANCED_ANALYSIS_UNAVAILABLE':
                            run_flight=run_manifest.get('flight_recorder',{})
                            if isinstance(run_flight,dict):
                                recorder_loss=any(int(run_flight.get(k,0) or 0)>0 for k in (
                                    'recent_overwrites','priority_overwrites','pinned_context_omissions',
                                    'sanitization_truncations','timeline_events_omitted_for_size',
                                    'journal_dropped_events','journal_queue_drops','priority_journal_queue_drops','snapshot_export_omissions')) \
                                    or not bool(run_flight.get('persistent_storage_available',True)) \
                                    or bool(run_flight.get('source_tail_uncertain',False))
                                expected_tail_uncertain=bool(run_flight.get('source_tail_uncertain',False))
                                if gpt.get('source_tail_uncertain') is not expected_tail_uncertain:
                                    add('GPT_SUMMARY_SOURCE_TAIL_MISMATCH')
                                if gpt.get('absence_is_conclusive') is not (not recorder_loss):
                                    add('GPT_SUMMARY_CONCLUSIVENESS_MISMATCH')
                                expected_scope='INCLUDED_EVIDENCE_ONLY' if recorder_loss else 'COMPLETE_RECORDER_EVIDENCE'
                                if gpt.get('first_divergence_scope')!=expected_scope:
                                    add('GPT_SUMMARY_DIVERGENCE_SCOPE_MISMATCH')
                                expected_cause_scope='INCLUDED_EVIDENCE_ONLY' if recorder_loss else 'COMPLETE_RECORDER_EVIDENCE'
                                if gpt.get('cause_scope')!=expected_cause_scope:
                                    add('GPT_SUMMARY_CAUSE_SCOPE_MISMATCH')
                                if gpt.get('candidate_causes_may_be_incomplete') is not bool(recorder_loss):
                                    add('GPT_SUMMARY_CAUSE_COMPLETENESS_MISMATCH')
                                if status=='DIVERGENCE_CANDIDATE' and recorder_loss:
                                    expected_confidence=_loss_adjusted_confidence(retained_gpt_confidence,True)
                                    if gpt_confidence!=expected_confidence:
                                        add('GPT_SUMMARY_LOSS_CONFIDENCE_MISMATCH')
                                    if gpt_confidence=='HIGH':
                                        add('GPT_SUMMARY_LOSS_CONFIDENCE_NOT_DOWNGRADED')
                    if status!='ADVANCED_ANALYSIS_UNAVAILABLE':
                        cause_status=gpt.get('cause_status')
                        causes=gpt.get('candidate_causes')
                        if cause_status not in ('UNDETERMINED','SINGLE_SUPPORTED','MULTIPLE_PLAUSIBLE'):
                            add('GPT_SUMMARY_CAUSE_STATUS_INVALID')
                        if not isinstance(causes,list) or any(not isinstance(x,str) for x in causes):
                            add('GPT_SUMMARY_CAUSES_INVALID')
                        elif cause_status=='UNDETERMINED' and causes:
                            add('GPT_SUMMARY_CAUSE_STATUS_MISMATCH')
                        elif cause_status=='SINGLE_SUPPORTED' and len(causes)!=1:
                            add('GPT_SUMMARY_CAUSE_STATUS_MISMATCH')
                        elif cause_status=='MULTIPLE_PLAUSIBLE' and len(causes)<2:
                            add('GPT_SUMMARY_CAUSE_STATUS_MISMATCH')
                    if isinstance(diag,dict) and status in ('DIVERGENCE_IDENTIFIED','DIVERGENCE_CANDIDATE'):
                        if gpt.get('first_divergence')!=diag.get('first_divergent_boundary') or gpt.get('suspected_owner')!=diag.get('suspected_owner'):
                            add('GPT_SUMMARY_FINDING_MISMATCH')
                        if gpt.get('confidence')!=diag.get('confidence'):
                            add('GPT_SUMMARY_CONFIDENCE_MISMATCH')
                        if gpt.get('retained_evidence_confidence')!=diag.get('retained_evidence_confidence'):
                            add('GPT_SUMMARY_RETAINED_CONFIDENCE_MISMATCH')
                        diag_causes=diag.get('candidate_causes',[]) or []
                        if gpt.get('candidate_causes')!=list(diag_causes) or gpt.get('cause_status')!=diag.get('cause_status'):
                            add('GPT_SUMMARY_CAUSE_MISMATCH')
                        if gpt.get('cause_scope')!=diag.get('cause_scope') or gpt.get('candidate_causes_may_be_incomplete')!=diag.get('candidate_causes_may_be_incomplete'):
                            add('GPT_SUMMARY_CAUSE_SCOPE_DIAGNOSIS_MISMATCH')
            if 'analysis/historical_matches.json' in names:
                try:history=json.loads(z.read('analysis/historical_matches.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):history={};add('HISTORICAL_MATCHES_JSON_INVALID')
                matches=history.get('matches',[]) if isinstance(history,dict) else None
                if not isinstance(matches,list):add('HISTORICAL_MATCHES_SHAPE_INVALID')
                else:
                    for row in matches:
                        if not isinstance(row,dict):add('HISTORICAL_MATCH_ROW_INVALID');continue
                        if row.get('classification') not in (None,'SIMILARITY_ONLY') or row.get('root_cause_reused') not in (None,False):
                            add('HISTORICAL_MATCH_CAUSALITY_INVALID')
            if 'analysis/action_lifecycles.json' in names:
                try:lifecycles=json.loads(z.read('analysis/action_lifecycles.json'))
                except (json.JSONDecodeError,UnicodeDecodeError):lifecycles={};add('ACTION_LIFECYCLES_JSON_INVALID')
                if not isinstance(lifecycles,dict):
                    add('ACTION_LIFECYCLES_SHAPE_INVALID')
                else:
                    actions=lifecycles.get('actions',[])
                    pre_action=lifecycles.get('pre_action_outcomes',[])
                    blockers=lifecycles.get('authorization_blockers',[])
                    if not isinstance(actions,list) or not isinstance(pre_action,list) or not isinstance(blockers,list):
                        add('ACTION_LIFECYCLES_SHAPE_INVALID')
                    else:
                        if not bool(m.get('advanced_analysis_failed')):
                            try:
                                expected_lifecycles=action_lifecycle_report(rows)
                                if lifecycles!=expected_lifecycles:
                                    add('ACTION_LIFECYCLES_DERIVATION_MISMATCH')
                            except Exception:
                                add('ACTION_LIFECYCLES_RECOMPUTE_FAILED')
                        for row in actions:
                            if not isinstance(row,dict):
                                add('ACTION_LIFECYCLE_ROW_INVALID');continue
                            refs=row.get('event_ids',[])
                            if not isinstance(refs,list):
                                add('ACTION_LIFECYCLE_EVIDENCE_REFS_INVALID')
                            elif any(not isinstance(x,str) or x not in event_ids for x in refs):
                                add('ACTION_LIFECYCLE_EVIDENCE_REF_MISSING')
                            decision_ref=row.get('decision_event_id')
                            if decision_ref is not None and (not isinstance(decision_ref,str) or decision_ref not in event_ids):
                                add('ACTION_LIFECYCLE_DECISION_REF_MISSING')
                            not_sent_ref=row.get('not_sent_event_id')
                            if not_sent_ref is not None and (not isinstance(not_sent_ref,str) or not_sent_ref not in event_ids):
                                add('ACTION_LIFECYCLE_NOT_SENT_REF_MISSING')
                            trace_id=row.get('trace_id')
                            if trace_id is not None and (not isinstance(trace_id,str) or not trace_id.startswith('trace-')):
                                add('ACTION_LIFECYCLE_TRACE_ID_INVALID')
                            nearby=row.get('nearby_semantic_context',[])
                            if not isinstance(nearby,list):
                                add('ACTION_LIFECYCLE_CONTEXT_INVALID')
                            else:
                                for context in nearby:
                                    if not isinstance(context,dict):
                                        add('ACTION_LIFECYCLE_CONTEXT_INVALID');continue
                                    ref=context.get('event_id')
                                    if not isinstance(ref,str) or ref not in event_ids:
                                        add('ACTION_LIFECYCLE_CONTEXT_REF_MISSING')
                            if row.get('nearby_semantic_context_is_causal_proof') is not False:
                                add('ACTION_LIFECYCLE_CONTEXT_CAUSALITY_INVALID')
                        for pre_row in pre_action:
                            if not isinstance(pre_row,dict):
                                add('PRE_ACTION_OUTCOME_INVALID');continue
                            refs=pre_row.get('event_ids',[])
                            if not isinstance(refs,list) or any(not isinstance(ref,str) or ref not in event_ids for ref in refs):
                                add('PRE_ACTION_OUTCOME_EVIDENCE_REF_MISSING')
                            decision_ref=pre_row.get('decision_event_id')
                            if not isinstance(decision_ref,str) or decision_ref not in event_ids:
                                add('PRE_ACTION_DECISION_REF_MISSING')
                            downstream_ref=pre_row.get('downstream_event_id')
                            if downstream_ref is not None and (not isinstance(downstream_ref,str) or downstream_ref not in event_ids):
                                add('PRE_ACTION_DOWNSTREAM_REF_MISSING')
                        for blocker in blockers:
                            if not isinstance(blocker,dict):
                                add('ACTION_AUTHORIZATION_BLOCKER_INVALID');continue
                            ref=blocker.get('event_id')
                            if not isinstance(ref,str) or ref not in event_ids:
                                add('ACTION_AUTHORIZATION_BLOCKER_REF_MISSING')
                        if isinstance(gpt,dict) and gpt:
                            lifecycle_pre=lifecycles.get('pre_action_outcomes',[])
                            expected_latest_pre=(lifecycle_pre[-1] if isinstance(lifecycle_pre,list) and lifecycle_pre else None)
                            if gpt.get('latest_included_pre_action_outcome')!=expected_latest_pre:
                                add('GPT_SUMMARY_PRE_ACTION_MISMATCH')
                            lifecycle_actions=lifecycles.get('actions',[])
                            expected_latest_action=(lifecycle_actions[-1] if isinstance(lifecycle_actions,list) and lifecycle_actions else None)
                            if gpt.get('latest_included_action_lifecycle')!=expected_latest_action:
                                add('GPT_SUMMARY_ACTION_LIFECYCLE_MISMATCH')
                            if gpt.get('pre_action_outcomes_omitted')!=lifecycles.get('pre_action_outcomes_omitted',0):
                                add('GPT_SUMMARY_PRE_ACTION_OMISSION_MISMATCH')
                            if gpt.get('action_lifecycles_omitted')!=lifecycles.get('actions_omitted',0):
                                add('GPT_SUMMARY_ACTION_OMISSION_MISMATCH')
                        if not bool(m.get('advanced_analysis_failed')) and isinstance(facts,dict) and isinstance(graph,dict):
                            try:
                                expected_facts=proven_fact_report(rows,graph.get('edges',[]),lifecycles)
                                if facts!=expected_facts:add('PROVEN_FACTS_DERIVATION_MISMATCH')
                            except Exception:add('PROVEN_FACTS_RECOMPUTE_FAILED')
    except Exception as exc:
        add('BUNDLE_OPEN_FAILED:'+type(exc).__name__.upper())
    return {'status':'PASS' if not errors else 'FAIL','errors':errors}
