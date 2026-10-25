"""Application-only composition; no direct dependencies between Protocol and Canonical.

All outputs are observation-only. Offline semantic audits are for investigating
historical packet evidence, not certifying current-build gameplay or live state.
"""
from __future__ import annotations
from pathlib import Path
from hashlib import sha256
from collections import Counter
from anka_canonical.qualification import ResearchContext, review_candidates
from anka_capture.api import inspect_pcapng,MAX_CAPTURE_BYTES,validate_ports,CaptureRejected
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.api import ProtocolInspector
from anka_protocol.adapters.historical import load_reference
from anka_protocol.adapters.historical_semantic import HistoricalSemanticAdapter,HistoricalContext,ADAPTER_ID,BUILD
from anka_canonical.staging import CanonicalStagingGate
from anka_contracts.protocol import WireMessage

MAX_FINDING_CODES=40
MAX_PENDING_SEMANTIC_MESSAGES=4096
MAX_PENDING_CANONICAL_FACTS=2048

def inspect_semantic_pcapng(path:Path,*,root:Path,ports:tuple[int,...],build:str,observer=None)->dict:
    validate_ports(ports)
    capture=inspect_pcapng(path,server_ports=ports,observer=observer)
    p=Path(path)
    if p.stat().st_size>MAX_CAPTURE_BYTES:raise CaptureRejected('CAPTURE_FILE_SIZE_UNSUPPORTED')
    raw=p.read_bytes()
    if sha256(raw).hexdigest()!=capture.source_sha256:raise CaptureRejected('CAPTURE_SOURCE_CHANGED_DURING_READ')
    segments=read_pcapng_tcp_segments(p,server_ports=set(ports),raw=raw)
    adapter=HistoricalSemanticAdapter(requested_build=build)
    # P23: two-phase observation. A message may decode correctly, then a later
    # TCP gap or incomplete frame invalidates the same capture. Never stage
    # candidates inside on_message before the final transport audit.
    pending = []
    pending_facts = 0
    capped = False
    provenance_mismatches = 0
    statuses = Counter()
    failure_codes = Counter()

    def on_message(msg:WireMessage)->None:
        nonlocal pending_facts, capped, provenance_mismatches
        # Bound memory independently of packet sizes and total capture count.
        if len(pending) >= MAX_PENDING_SEMANTIC_MESSAGES:
            capped = True
            return
        result = adapter.decode(msg,context=HistoricalContext())
        # An adapter's provenance labels are untrusted just like its decoded
        # values. Verify them against the original immutable wire observation.
        # No raw payloads/flow identities are retained or included in receipts.
        expected_digest = sha256(msg.flow_key.encode('utf8')).hexdigest()
        if (result.wire_name != msg.name or result.protocol_build != build
                or result.adapter_id != ADAPTER_ID or any(
                    (fact.evidence.wire_name != msg.name
                     or fact.evidence.protocol_build != build
                     or fact.evidence.adapter_id != ADAPTER_ID
                     or fact.evidence.packet_number != msg.packet_number
                     or fact.evidence.transport_generation != msg.generation
                     or fact.evidence.message_index != msg.message_index
                     or fact.evidence.flow_digest != expected_digest)
                    for fact in result.candidates)):
            provenance_mismatches += 1
        statuses[result.status] += 1
        if result.failure_code:
            failure_codes[result.failure_code] += 1
        if pending_facts + len(result.candidates) > MAX_PENDING_CANONICAL_FACTS:
            capped = True
            return
        pending_facts += len(result.candidates)
        pending.append(result)

    inspector = ProtocolInspector(load_reference(root),requested_build=build,
                                  observer=observer,on_message=on_message)
    for segment in segments:
        inspector.consume(segment)
    transport = inspector.finish()

    transport_clean = (capture.status == 'OBSERVED_NO_DETECTED_GAPS'
                       and transport.status == 'HISTORICAL_WIRE_OBSERVATION_ONLY'
                       and not transport.quarantined_streams
                       and not transport.unanchored_streams
                       and not transport.packet_loss_reported)
    # A malformed mapped wire schema should not lead to partial staging from
    # the same capture. Unknown wire names are NOT treated as semantic drift:
    # they can be optional/background traffic, as demonstrated in R5.198.
    schema_drift = statuses['QUARANTINED'] > 0
    held_back = pending_facts
    gate = CanonicalStagingGate()
    kinds = Counter()
    accepted = []
    failure = None
    if build != BUILD:
        failure = 'P23_HISTORICAL_BUILD_MISMATCH'
    elif not transport_clean:
        failure = 'P23_TRANSPORT_CONTINUITY_UNPROVEN'
    elif capped:
        failure = 'P23_SEMANTIC_BATCH_LIMIT_EXCEEDED'
    elif provenance_mismatches:
        failure = 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH'
    elif schema_drift:
        failure = 'P23_SEMANTIC_SCHEMA_DRIFT'
    else:
        # Check the complete bounded batch before accepting ANY research facts.
        drafts = tuple(fact for result in pending for fact in result.candidates)
        if drafts:
            review = review_candidates(drafts, ResearchContext(
                expected_build=build,
                expected_adapter=ADAPTER_ID
            ))
            if review.status != 'RESEARCH_ONLY':
                failure = 'P23_CANONICAL_BATCH_CONFLICT'
        if failure is None:
            for result in pending:
                if result.status != 'CANDIDATES_ONLY':
                    continue
                decision = gate.inspect(result)
                if decision.status != 'STAGED_UNCERTIFIED':
                    # Fail closed even if a future per-result gate changes.
                    failure = 'P23_CANONICAL_STAGING_REJECTED'
                    break
                accepted.extend(decision.accepted_for_research)
            if failure:
                # Do not expose partial staging if a late result fails.
                gate = CanonicalStagingGate()
                accepted.clear()
            else:
                held_back = 0
    for draft in accepted:
        kinds[draft.kind] += 1
    if observer is not None:
        observer.record('protocol.semantic_research_completed',
            severity='WARNING' if failure else 'INFO',
            boundary='protocol.semantic_to_canonical_staging',
            failure_code=failure,
            payload={'candidates':len(accepted),
                     'held_back_candidates':held_back,
                     'captured_messages':transport.framed_messages,
                     'transport_status':transport.status,
                     'capture_status':capture.status,
                     'quarantined_semantic_count':statuses['QUARANTINED'],
                     'source_provenance_mismatches':provenance_mismatches,
                     'live_ready':False,'physical_input_sent':False})
    return {'operation':'semantic-audit',
        'status':'QUARANTINED_RESEARCH_EVIDENCE' if failure else 'HISTORICAL_RESEARCH_ONLY',
        'first_failure_boundary':failure,
        'capture':capture.to_dict(), 'wire':transport.to_dict(),
        'semantic_status_counts':dict(sorted(statuses.items())),
        'failure_counts':dict(sorted(failure_codes.most_common(MAX_FINDING_CODES))),
        'candidate_kinds':dict(sorted(kinds.items())),
        'pending_candidates':pending_facts,
        'source_provenance_mismatches':provenance_mismatches,
        'withheld_candidates':held_back,
        'staged_candidates':len(accepted),
        'transport_continuity_observed':transport_clean,
        'batch_capacity_exceeded':capped,
        'research_only':True,
        'committed_events':0,'canonical_events_emitted':0,
        'live_state_mutated':False,'gameplay_capabilities_certified':False,
        'live_ready':False,'physical_input_sent':False}


def synthetic_semantic_demo(*,observer=None)->dict:
    """Synthetic protobuf bodies illustrate historical mapping only."""
    def vi(x):
        if x<0:x=(1<<64)+x
        out=bytearray()
        while x>=128:out.append((x&127)|128);x>>=7
        out.append(x);return bytes(out)
    def n(i,val):return vi((i<<3)|0)+vi(val)
    def b(i,raw):return vi((i<<3)|2)+vi(len(raw))+raw
    jtk=b(1,b(4,n(2,1)+b(1,n(1,11)+n(2,-2)))+b(4,n(2,23)+b(1,n(1,5))))+n(2,12345)
    # Demo values: actor 12345, AP=9, MP=5, HP=850/1000. Neither represents live evidence.
    inputs=(WireMessage('server_to_client','jtk',jtk,100,'synthetic',1,0),
        WireMessage('server_to_client','kqo',n(1,1000)+n(3,850),101,'synthetic',1,1))
    gate=CanonicalStagingGate();adapter=HistoricalSemanticAdapter(requested_build='Dofus 3.7.10.10')
    candidates=[]
    for msg in inputs:
        result=adapter.decode(msg,context=HistoricalContext(12345,True,True))
        admission=gate.inspect(result,transport_complete=True,account_attested=True)
        candidates.extend({'kind':x.kind,'actor_id':x.actor_id,'resource':x.resource,'value':x.value,'maximum':x.maximum}
                 for x in admission.accepted_for_research)
    if observer is not None:
        observer.record('protocol.semantic_research_completed',boundary='protocol.semantic_to_canonical_staging',
            payload={'synthetic':True,'candidate_count':len(candidates),'live_ready':False})
    return {'operation':'semantic-demo','status':'SYNTHETIC_HISTORICAL_CANDIDATES','candidates':candidates,
        'staged_candidates':gate.staged_count,'committed_events':0,'canonical_events_emitted':0,
        'gameplay_capabilities_certified':False,'live_state_mutated':False,'live_ready':False,'physical_input_sent':False}
