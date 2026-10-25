"""P29 research-only comparison of immutable, P28-validated capture evidence.

This *composition root* is the only place that joins Capture + Protocol.
No decoder controls authority. Missing exact message selectors, transport loss,
unsupported builds, or non-independent annotations never certify gameplay.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile
import json

from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_capture.transport import TransportAuditor
from anka_protocol.api import ProtocolInspector
from anka_protocol.adapters.historical import load_reference
from anka_protocol.adapters.historical_semantic import (
    HistoricalSemanticAdapter, HistoricalContext, ADAPTER_ID, BUILD,
)
from anka_protocol.evidence_intake import inspect_evidence_pack, IntakeRejected, evidence_binding_id, evidence_case_binding
from anka_protocol.adapters.declarative import load_local_recipe, RecipeRejected

MAX_COMPARISON_CAPTURE = 32 * 1024 * 1024
MAX_COMPARISON_PACK = 128 * 1024 * 1024
MAX_MESSAGES = 4096
MAX_FACTS = 4096


def _safe_result(code: str, *, cases: list[dict] | None = None,
                 counts: dict | None = None, comparison_binding: str | None = None) -> dict:
    entries = cases or []
    return {
        'status': code, 'comparison_binding': comparison_binding,
        'case_results': entries,
        'case_count': len(entries),
        'matched_cases': sum(r['status'] == 'MATCHED_RESEARCH_ONLY' for r in entries),
        'mismatched_cases': sum(r['status'] == 'FIELD_MISMATCH' for r in entries),
        'finding_counts': counts or {},
        'research_only': True, 'certified_capabilities': [],
        'live_semantic_certified': False, 'adapter_activated': False,
        'canonical_commits': 0, 'live_state_mutated': False,
        'physical_input_sent': False,
    }


def _facts_for_capability(draft) -> tuple[str | None, dict]:
    base = {'actor_id': draft.actor_id}
    if draft.kind == 'ACTOR_RESOURCE_ABSOLUTE':
        mapping = {'AP': ('actor_ap', 'ap'), 'MP': ('actor_mp', 'mp'),
                   'RANGE': ('actor_range', 'range')}
        if draft.resource not in mapping:
            return None, {}
        cap, field = mapping[draft.resource]
        return cap, {**base, 'value': draft.value, field: draft.value}
    if draft.kind == 'ACTOR_HP_ABSOLUTE':
        return 'actor_hp', {**base, 'value': draft.value,
                            'hp': draft.value, 'max_hp': draft.maximum}
    # Cooldown entries are arrays; intake v1 allows scalar oracles only.
    # Do not invent a partial scalar comparison for this capability.
    return None, {}



def _fight_facts_for_capability(draft) -> tuple[str | None, dict]:
    """Explicit per-capability public comparison fields; never export values."""
    mapping = {
        'FIGHT_START_OBSERVED': ('fight_start', ('fight_id',)),
        'FIGHT_END_OBSERVED': ('fight_end', ('fight_id',)),
        'TURN_START_OBSERVED': ('turn_start', ('fight_id','actor_id','turn_index')),
        'TURN_END_OBSERVED': ('turn_end', ('fight_id','actor_id','turn_index')),
        'ACTOR_CELL_OBSERVED': ('actor_cell', ('fight_id','actor_id','cell_id')),
        'SPELL_CAST_OBSERVED': ('spell_cast', ('fight_id','actor_id','spell_id','target_cell')),
    }
    entry = mapping.get(draft.kind)
    if entry is None:
        return None, {}
    capability, keys = entry
    return capability, {k: getattr(draft,k) for k in keys}

def compare_pack(path: Path, *, root: Path, adapter_factory=HistoricalSemanticAdapter,
                 expected_archive_sha256: str | None = None) -> dict:
    """Compare *selected* observed historical facts against independent annotations.

    P28 intake must pass first. The entire archive is read again and SHA-pinned
    to P28's immutable snapshot, so a replaced file cannot mix two pack versions.
    Current-build adapters are deliberately not loaded from untrusted ZIP data.
    """
    intake = inspect_evidence_pack(path)

    def bound_result(code: str, *, cases: list[dict] | None = None,
                     counts: dict | None = None) -> dict:
        # P42: case indexes only have meaning inside one exact evidence pack.
        # Carry verified intake identity for EVERY success and failure report.
        return _safe_result(code, cases=cases, counts=counts,
                            comparison_binding=evidence_binding_id(
                                intake.archive_sha256, intake.protocol_build, intake.adapter_id))
    if expected_archive_sha256 is not None and intake.archive_sha256 != expected_archive_sha256:
        return bound_result('PACK_CHANGED_SINCE_INTAKE')
    if intake.protocol_build == BUILD and intake.adapter_id == ADAPTER_ID:
        catalog = load_reference(root)
        factory = lambda: adapter_factory(requested_build=intake.protocol_build)
        expected_id = ADAPTER_ID
        expected_status = 'HISTORICAL_WIRE_OBSERVATION_ONLY'
    else:
        try:
            reviewed = load_local_recipe(root, build=intake.protocol_build, adapter_id=intake.adapter_id)
        except (RecipeRejected, OSError) as exc:
            return bound_result('LOCAL_RESEARCH_RECIPE_REJECTED')
        if reviewed is None:
            return bound_result('ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD')
        recipe_adapter, catalog = reviewed
        factory = lambda: recipe_adapter
        expected_id = intake.adapter_id
        expected_status = 'RESEARCH_WIRE_OBSERVATION_ONLY'
    try:
        raw = Path(path).read_bytes()
        if len(raw) > MAX_COMPARISON_PACK or sha256(raw).hexdigest() != intake.archive_sha256:
            return bound_result('PACK_CHANGED_DURING_COMPARISON')
        with ZipFile(BytesIO(raw)) as z:
            manifest = json.loads(z.read('manifest.json'))
            ports = manifest.get('server_ports')
            if ports is None:
                return bound_result('CAPTURE_PORTS_UNSPECIFIED')
            if any('selector' not in row for row in manifest['cases']):
                return bound_result('EXACT_SOURCE_SELECTOR_REQUIRED')
            # Bound memory and refuse unverifiable source shapes.
            capture_files = {row['capture'] for row in manifest['cases']}
            if len(capture_files) > 3:
                return bound_result('TOO_MANY_CAPTURES_FOR_COMPARISON')
            selected = {}
            for capture_name in sorted(capture_files):
                info = z.getinfo(capture_name)
                if info.file_size > MAX_COMPARISON_CAPTURE:
                    return bound_result('CAPTURE_TOO_LARGE_FOR_COMPARISON')
                raw_capture = z.read(capture_name)
                try:
                    segments = read_pcapng_tcp_segments(
                        Path('unused'), server_ports=set(ports), raw=raw_capture)
                    if len(segments) > 20000:
                        return bound_result('CAPTURE_SEGMENT_LIMIT')
                    transport = TransportAuditor().audit(tuple(segments))
                except (ValueError, OSError, OverflowError):
                    return bound_result('CAPTURE_MALFORMED_OR_UNSUPPORTED')
                messages = []
                decoded = []
                fight_decoded = []
                issue = []
                adapter = factory()

                def on_message(message):
                    if len(messages) >= MAX_MESSAGES:
                        issue.append('MESSAGE_BUDGET_EXCEEDED')
                        raise ValueError('P29_MESSAGE_BUDGET_EXCEEDED')
                    messages.append(message)
                    result = adapter.decode(message, context=HistoricalContext())
                    if (result.protocol_build != intake.protocol_build or result.adapter_id != expected_id
                        or result.wire_name != message.name or
                        (result.candidates and result.status != 'CANDIDATES_ONLY')):
                        issue.append('DECODED_RESULT_CONTRACT_INVALID')
                    if result.status == 'QUARANTINED':
                        issue.append('SEMANTIC_SCHEMA_DRIFT')
                    if len(decoded) + len(result.candidates) > MAX_FACTS:
                        issue.append('FACT_BUDGET_EXCEEDED')
                        raise ValueError('P29_FACT_BUDGET_EXCEEDED')
                    for draft in result.candidates:
                        e = draft.evidence
                        if (e.protocol_build != intake.protocol_build or e.adapter_id != expected_id
                            or e.wire_name != message.name or e.packet_number != message.packet_number
                            or e.message_index != message.message_index
                            or e.transport_generation != message.generation
                            or e.flow_digest != sha256(message.flow_key.encode('utf8')).hexdigest()):
                            issue.append('DECODED_SOURCE_PROVENANCE_INVALID')
                    decoded.extend(result.candidates)
                    # P31 event research is a DIFFERENT contract. It cannot be
                    # fed to the authoritative or historical scalar staging gate.
                    if hasattr(adapter, 'decode_fight'):
                        fight_result = adapter.decode_fight(message)
                        if ((fight_result.adapter_id,fight_result.protocol_build,fight_result.wire_name)
                            != (expected_id,intake.protocol_build,message.name)):
                            issue.append('FIGHT_RESULT_CONTRACT_INVALID')
                        if fight_result.status == 'QUARANTINED':
                            issue.append('SEMANTIC_SCHEMA_DRIFT')
                        if len(decoded)+len(fight_decoded)+len(fight_result.candidates)>MAX_FACTS:
                            issue.append('FACT_BUDGET_EXCEEDED')
                            raise ValueError('P31_FACT_BUDGET_EXCEEDED')
                        for draft in fight_result.candidates:
                            e = draft.evidence
                            if (draft.authority != 'RESEARCH_ONLY_NOT_CANONICAL'
                                or (e.protocol_build,e.adapter_id,e.wire_name,e.packet_number,
                                    e.message_index,e.transport_generation,e.flow_digest)
                                != (intake.protocol_build,expected_id,message.name,message.packet_number,
                                    message.message_index,message.generation,
                                    sha256(message.flow_key.encode('utf8')).hexdigest())):
                                issue.append('DECODED_SOURCE_PROVENANCE_INVALID')
                        fight_decoded.extend(fight_result.candidates)

                inspector = ProtocolInspector(catalog,
                    requested_build=intake.protocol_build, on_message=on_message)
                try:
                    for segment in segments:
                        inspector.consume(segment)
                    wire = inspector.finish()
                except (ValueError, OSError, OverflowError):
                    return bound_result('DECODER_OR_INSPECTOR_EXCEPTION')
                if issue:
                    return bound_result(sorted(set(issue))[0])
                if (transport.status != 'OBSERVED_NO_DETECTED_GAPS'
                    or wire.status != expected_status
                    or wire.packet_loss_reported or wire.quarantined_streams
                    or wire.unanchored_streams or wire.direction_mismatches):
                    return bound_result('TRANSPORT_OR_FRAMING_UNPROVEN')
                selected[capture_name] = (messages, decoded, fight_decoded)

            cases = []
            observed_counts = Counter()
            for index, row in enumerate(manifest['cases']):
                sel = row['selector']
                messages, facts, fight_facts = selected[row['capture']]
                matching_messages = [m for m in messages if (
                    m.packet_number == sel['packet_number'] and
                    m.message_index == sel['message_index'] and
                    m.generation == sel['transport_generation'] and
                    m.name == sel['wire_name'] and m.direction == sel['direction'] and
                    sha256(m.flow_key.encode('utf8')).hexdigest() == sel['flow_digest'])]
                status = 'SOURCE_MESSAGE_NOT_FOUND'
                mismatch_fields = []
                if len(matching_messages) > 1:
                    status = 'SOURCE_SELECTOR_AMBIGUOUS'
                elif len(matching_messages) == 1:
                    available = []
                    for draft in facts:
                        ref = draft.evidence
                        if (ref.packet_number, ref.message_index, ref.transport_generation,
                            ref.wire_name, ref.flow_digest) != (
                            sel['packet_number'], sel['message_index'], sel['transport_generation'],
                            sel['wire_name'], sel['flow_digest']):
                            continue
                        cap, fields = _facts_for_capability(draft)
                        if cap == row['capability']:
                            available.append(fields)
                    for draft in fight_facts:
                        ref = draft.evidence
                        if (ref.packet_number, ref.message_index, ref.transport_generation,
                            ref.wire_name, ref.flow_digest) != (
                            sel['packet_number'], sel['message_index'], sel['transport_generation'],
                            sel['wire_name'], sel['flow_digest']):
                            continue
                        cap, fields = _fight_facts_for_capability(draft)
                        if cap == row['capability']:
                            available.append(fields)
                    if not available:
                        status = 'CAPABILITY_NOT_MAPPED_OR_CONTEXT_MISSING'
                    elif len(available) != 1:
                        status = 'MULTIPLE_FACTS_FOR_ONE_SELECTOR'
                    else:
                        oracle = json.loads(z.read(row['oracle']))
                        expected = next(item['expected'] for item in oracle['observations']
                                        if item['id'] == row['oracle_id'])
                        allowed = {'actor_id','value'} | ({'ap'} if row['capability']=='actor_ap' else
                                     {'mp'} if row['capability']=='actor_mp' else
                                     {'range'} if row['capability']=='actor_range' else
                                     {'hp','max_hp'} if row['capability']=='actor_hp' else set())
                        fight_allowed = {
                            'fight_start': {'fight_id'}, 'fight_end': {'fight_id'},
                            'turn_start': {'fight_id','actor_id','turn_index'},
                            'turn_end': {'fight_id','actor_id','turn_index'},
                            'actor_cell': {'fight_id','actor_id','cell_id'},
                            'spell_cast': {'fight_id','actor_id','spell_id','target_cell'},
                        }
                        allowed = fight_allowed.get(row['capability'],allowed)
                        required = fight_allowed.get(row['capability'])
                        if (not set(expected).issubset(allowed)
                            or (required is not None and set(expected)!=required)
                            or (required is None and not (set(expected) - {'actor_id'}))):
                            status = 'ORACLE_FIELDS_NOT_COMPARABLE'
                        else:
                            mismatch_fields = sorted(k for k, value in expected.items()
                                                     if available[0].get(k) != value)
                            status = 'FIELD_MISMATCH' if mismatch_fields else 'MATCHED_RESEARCH_ONLY'
                observed_counts[status] += 1
                # Never export oracle values, actor IDs, capture names, raw flow identity,
                # witnesses, or user-written case IDs to routine GPT reports.
                cases.append({'case_index': index, 'capability': row['capability'],
                              'case_binding': evidence_case_binding(
                                  intake.archive_sha256, intake.protocol_build,
                                  intake.adapter_id, index, intake.case_evidence[index]),
                              'status': status, 'mismatch_fields': mismatch_fields})
            overall = ('RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED'
                       if all(x['status'] == 'MATCHED_RESEARCH_ONLY' for x in cases)
                       else 'RESEARCH_COMPARISON_BLOCKED')
            return bound_result(overall, cases=cases, counts=dict(sorted(observed_counts.items())))
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return bound_result('COMPARISON_FAILED_CLOSED')
