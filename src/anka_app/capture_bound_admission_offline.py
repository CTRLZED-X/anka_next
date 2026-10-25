"""P59: compare an untrusted admission rehearsal against actual saved PCAPNG bytes.

This only establishes that selected message bodies/positions occur in an inspected
file, NOT that the capture is complete, genuine, from a particular client, or
that any protocol semantics/character identities are correct. No writer access.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from anka_canonical.admission_review import review_admission_rehearsal
from anka_contracts.admission import AdmissionRehearsal
from anka_capture.api import inspect_pcapng, CaptureRejected, MAX_CAPTURE_BYTES
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_protocol.api import ProtocolInspector
from anka_protocol.adapters.historical import load_reference

MAX_WIRE_OBSERVATIONS = 4096


@dataclass(frozen=True, slots=True)
class CaptureBoundAdmissionReview:
    status: str
    reasons: tuple[str, ...]
    matching_messages: int
    claimed_messages: int
    observed_selected_messages: int
    file_bytes_match: bool
    # Intentionally prevents consumers promoting this report to a live grant.
    current_client_certified: bool = field(default=False, init=False)
    driver_loss_proven: bool = field(default=False, init=False)
    account_binding_verified: bool = field(default=False, init=False)
    authoritative: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.status not in ('FILE_WIRE_MATCH_UNTRUSTED', 'QUARANTINED'):
            raise ValueError('P59_STATUS_INVALID')
        if (self.status == 'FILE_WIRE_MATCH_UNTRUSTED') != (not self.reasons):
            raise ValueError('P59_STATUS_REASONS_INCONSISTENT')
        if not 0 <= self.matching_messages <= self.claimed_messages <= 512:
            raise ValueError('P59_CLAIM_COUNTERS_INVALID')
        if not 0 <= self.observed_selected_messages <= MAX_WIRE_OBSERVATIONS:
            raise ValueError('P59_OBSERVED_COUNTER_INVALID')

    def to_dict(self) -> dict:
        # Do not log raw file paths, bytes, names, flow digests, actor IDs, etc.
        return {'status': self.status, 'reasons': list(self.reasons),
                'matching_messages': self.matching_messages,
                'claimed_messages': self.claimed_messages,
                'observed_selected_messages': self.observed_selected_messages,
                'file_bytes_match': self.file_bytes_match,
                'driver_loss_proven': False, 'current_client_certified': False,
                'account_binding_verified': False, 'authoritative': False,
                'actionable': False, 'canonical_commits': 0,
                'physical_input_sent': False}


def _ref_key(ref) -> tuple:
    return (ref.flow_digest, ref.transport_generation, ref.packet_number,
            ref.message_index, ref.wire_name)


def review_capture_bound_admission(rehearsal: AdmissionRehearsal, *,
                                   capture_path: Path, root: Path,
                                   ports: tuple[int, ...]) -> CaptureBoundAdmissionReview:
    """Cross-check actual file bytes and all selected wire messages, read-only.

    A file SHA confirms a single inspected disk snapshot, NOT an authenticated
    capture origin. In particular a forged/edited PCAPNG can match every claim.
    Historical parser/catalog only; unsupported/current build always quarantined.
    """
    if type(rehearsal) is not AdmissionRehearsal:
        raise TypeError('P59_ADMISSION_REHEARSAL_REQUIRED')
    reasons = set()
    matching = 0
    observed = 0
    capture_matched = False
    structure = review_admission_rehearsal(rehearsal)
    if not structure.structural_consistency:
        reasons.add('P59_P58_STRUCTURAL_REVIEW_QUARANTINED')
    try:
        catalog = load_reference(Path(root))
    except (ValueError, TypeError, OSError):
        catalog = None
        reasons.add('P59_HISTORICAL_REFERENCE_INVALID')
    if catalog is not None and (rehearsal.scope.protocol_build != catalog.protocol_build or
                               rehearsal.scope.adapter_id != catalog.adapter_id):
        reasons.add('P59_UNSUPPORTED_OR_MISMATCHED_HISTORICAL_BUILD')
    # Inspect the same bounded source twice; do not follow symlinks to a different
    # snapshot between inspection and reassembly without re-checking digest.
    try:
        receipt = inspect_pcapng(Path(capture_path), server_ports=ports)
        if receipt.source_sha256 != rehearsal.scope.capture_sha256:
            reasons.add('P59_CAPTURE_FILE_HASH_MISMATCH')
        size = Path(capture_path).stat().st_size
        if size < 28 or size > MAX_CAPTURE_BYTES:
            reasons.add('P59_CAPTURE_FILE_CHANGED')
        else:
            raw = Path(capture_path).read_bytes()
            if len(raw) != receipt.source_bytes or sha256(raw).hexdigest() != receipt.source_sha256:
                reasons.add('P59_CAPTURE_FILE_CHANGED')
            else:
                capture_matched = receipt.source_sha256 == rehearsal.scope.capture_sha256
                if catalog is not None and 'P59_UNSUPPORTED_OR_MISMATCHED_HISTORICAL_BUILD' not in reasons:
                    observed_wire = []
                    overflow = False
                    def record_wire(message):
                        nonlocal overflow
                        if len(observed_wire) >= MAX_WIRE_OBSERVATIONS:
                            overflow = True
                            raise ValueError('P59_WIRE_LIMIT')
                        observed_wire.append(message)
                    parser = ProtocolInspector(catalog, requested_build=catalog.protocol_build,
                                               on_message=record_wire)
                    for segment in read_pcapng_tcp_segments(Path(capture_path),
                                                           server_ports=set(ports), raw=raw):
                        parser.consume(segment)
                    wire_receipt = parser.finish()
                    if (wire_receipt.invalid_frames or wire_receipt.quarantined_streams or
                        wire_receipt.unanchored_streams or overflow or
                        parser.counts['FRAME_WITHOUT_RECOGNIZED_ENVELOPE']):
                        reasons.add('P59_WIRE_STREAM_INCOMPLETE_OR_QUARANTINED')
                    selected = [m for m in observed_wire if m.direction == 'server_to_client' and
                                sha256(m.flow_key.encode('utf8')).hexdigest() == rehearsal.scope.flow_digest]
                    observed = len(selected)
                    claims_by_key = {_ref_key(c.evidence): c for c in rehearsal.packets}
                    seen = set()
                    for m in selected:
                        k = (sha256(m.flow_key.encode('utf8')).hexdigest(), m.generation,
                             m.packet_number, m.message_index, m.name)
                        if k in seen:
                            reasons.add('P59_DUPLICATE_OBSERVED_SOURCE')
                        seen.add(k)
                        claim = claims_by_key.get(k)
                        if claim is None:
                            reasons.add('P59_UNCLAIMED_SELECTED_WIRE_MESSAGE')
                        elif claim.direction != m.direction or claim.body != m.body:
                            reasons.add('P59_CLAIM_WIRE_BYTES_MISMATCH')
                        else:
                            matching += 1
                    if len(claims_by_key) != len(rehearsal.packets):
                        reasons.add('P59_DUPLICATE_CLAIM_PROVENANCE')
                    if matching != len(rehearsal.packets):
                        reasons.add('P59_CLAIM_SOURCE_NOT_OBSERVED')
                    if not selected:
                        reasons.add('P59_NO_SELECTED_FLOW_MESSAGES')
    except (CaptureRejected, OSError, ValueError, TypeError, OverflowError, MemoryError):
        reasons.add('P59_CAPTURE_OR_WIRE_READ_REJECTED')
    # Do not include anything discovered from input bytes in an exception/report.
    return CaptureBoundAdmissionReview('QUARANTINED' if reasons else 'FILE_WIRE_MATCH_UNTRUSTED',
        tuple(sorted(reasons)), matching, len(rehearsal.packets), observed, capture_matched)
