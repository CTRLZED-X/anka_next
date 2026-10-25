"""Capture System P4: offline, read-only PCAPNG transport inspection.

No packet body is written to diagnostic logs or bundle exports.
No packet can be treated as a canonical game event in this milestone.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from anka_contracts.capture import CapturePoll

from anka_contracts.capture import CapturedTcpSegment
from anka_capture.pcapng import read_pcapng_tcp_segments, pcapng_packet_count
from anka_capture.transport import TransportAuditor

MAX_CAPTURE_BYTES = 32 * 1024 * 1024
MAX_CAPTURE_SEGMENTS = 100_000

def _safe_observer_record(observer,name:str,**kwargs)->None:
    """Publish passive capture evidence without making diagnostics authority."""
    if observer is None:return
    try:observer.record(name,**kwargs)
    except Exception:pass


class CaptureRejected(ValueError):
    pass


class TcpSegmentSource(Protocol):
    """Future live-source interface: bounded batches, explicit loss reporting.

    Poll is read-only; an implementation must not infer account ownership.
    """
    def poll(self, *, max_segments: int, timeout_seconds: float) -> CapturePoll: ...


@dataclass(frozen=True,slots=True)
class CaptureReceipt:
    schema_version: int
    status: str
    source_format: str
    source_sha256: str
    source_bytes: int
    packet_records: int
    selected_segments: int
    selected_payload_bytes: int
    flows: int
    unanchored_directions: int
    unresolved_gap_directions: int
    reconnects: int
    duplicates: int
    reordered_segments: int
    account_binding_verified: bool = False
    tcp_framing_verified: bool = False
    live_capture_equivalent: bool = False
    protocol_decoded: bool = False
    game_state_verified: bool = False
    physical_input_sent: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def validate_ports(ports: tuple[int, ...]) -> None:
    if not ports or len(ports)>32 or len(set(ports)) != len(ports) or any(type(p) is not int or not 1<=p<=65535 for p in ports):
        raise CaptureRejected('CAPTURE_PORTS_INVALID_OR_MISSING')


def _safe_parser_reason(exc: Exception) -> str:
    # Allowlisted classifications only: parser error strings must never carry
    # endpoints, payload bytes, filenames or other sensitive evidence.
    details=str(exc).lower()
    if 'byte-order magic' in details: return 'PCAPNG_ENDIAN_MARKER_INVALID'
    if 'block length trailer' in details: return 'PCAPNG_TRAILER_MISMATCH'
    if 'ipv6' in details: return 'SELECTED_IPV6_UNSUPPORTED'
    if 'fragment' in details: return 'FRAGMENTED_TCP_UNSUPPORTED'
    if 'linktype' in details: return 'PCAPNG_LINKTYPE_UNSUPPORTED'
    if 'interface' in details: return 'PCAPNG_INTERFACE_INVALID'
    if 'tcp' in details: return 'TCP_PACKET_INVALID'
    if 'length' in details or 'truncat' in details: return 'PCAPNG_TRUNCATED_OR_LENGTH_INVALID'
    return 'PCAPNG_MALFORMED_OR_UNSUPPORTED'


def inspect_pcapng(path: Path, *, server_ports: tuple[int,...], observer=None) -> CaptureReceipt:
    validate_ports(server_ports)
    path=Path(path)
    try:
        size=path.stat().st_size
    except OSError as exc:
        raise CaptureRejected('CAPTURE_FILE_UNREADABLE') from exc
    if not 28 <= size <= MAX_CAPTURE_BYTES:
        raise CaptureRejected('CAPTURE_FILE_SIZE_UNSUPPORTED')
    # Content is intentionally never copied to runtime/, exported, or logged.
    try:
        # Read exactly one bounded immutable snapshot: hashing and parsing must
        # refer to identical evidence even if another process rewrites the file.
        raw=path.read_bytes()
        if len(raw)!=size or len(raw)>MAX_CAPTURE_BYTES:
            raise CaptureRejected('CAPTURE_SOURCE_CHANGED_DURING_READ')
        if raw[:4] != b'\x0a\x0d\x0d\x0a':
            raise CaptureRejected('CAPTURE_FORMAT_NOT_PCAPNG')
        digest=sha256(raw)
        segments=read_pcapng_tcp_segments(path,server_ports=set(server_ports),raw=raw)
        if len(segments)>MAX_CAPTURE_SEGMENTS:
            raise CaptureRejected('CAPTURE_SEGMENT_LIMIT_EXCEEDED')
        count=pcapng_packet_count(path,raw=raw)
        health=TransportAuditor().audit(tuple(segments))
    except (OSError,ValueError,OverflowError,MemoryError) as exc:
        if isinstance(exc,CaptureRejected):raise
        # No raw message, endpoint or file path in error codes or logs.
        if observer is not None:
            reason=_safe_parser_reason(exc)
            _safe_observer_record(observer,'capture.replay_rejected',severity='ERROR',boundary='capture.pcapng',
                                  failure_code='CAPTURE_CONTENT_INVALID',payload={'error_type':type(exc).__name__,
                                 'reason_code':reason})
        raise CaptureRejected('CAPTURE_CONTENT_INVALID') from exc
    receipt=CaptureReceipt(1,health.status,'PCAPNG',digest.hexdigest(),size,count,len(segments),
       health.selected_payload_bytes,health.flows,health.unanchored_directions,
       health.unresolved_gap_directions,health.reconnects,health.duplicates,health.reordered_segments)
    if observer is not None:
        _safe_observer_record(observer,'capture.replay_inspected',boundary='capture.pcapng',payload=receipt.to_dict())
        if receipt.status!='OBSERVED_NO_DETECTED_GAPS':
            _safe_observer_record(observer,'capture.evidence_not_certified',severity='WARNING',boundary='capture.transport',
                                  failure_code=receipt.status,payload={'selected_segments':receipt.selected_segments,
                                   'unanchored':receipt.unanchored_directions,'gaps':receipt.unresolved_gap_directions})
    return receipt
