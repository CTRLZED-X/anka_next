"""Transport-only P4 contracts. No protocol message semantics or account assertions.

Raw payloads exist only transiently in memory for a future decoder; they are not
serializable by the public capture-receipt API or emitted to diagnostics.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CapturedTcpSegment:
    flow_id: str = field(repr=False)
    direction: str
    seq: int
    payload: bytes = field(repr=False)
    packet_number: int
    tcp_flags: int = 0
    # Optional source timestamps. Legacy/replay fixtures may omit these; the
    # definitive envelope assembler labels any deterministic fallback explicitly.
    observed_utc: str | None = None
    observed_monotonic_ns: int | None = None
    timestamp_provenance: str = 'UNKNOWN'

    def __post_init__(self) -> None:
        if self.direction not in ('server_to_client', 'client_to_server'):
            raise ValueError('INVALID_CAPTURE_DIRECTION')
        if type(self.seq) is not int or not 0 <= self.seq < 2**32:
            raise ValueError('INVALID_TCP_SEQUENCE')
        if type(self.packet_number) is not int or self.packet_number < 1:
            raise ValueError('INVALID_PACKET_NUMBER')
        if not isinstance(self.payload, bytes):
            raise ValueError('INVALID_PAYLOAD_TYPE')
        if not isinstance(self.flow_id, str) or not self.flow_id:
            raise ValueError('INVALID_FLOW_ID')
        if type(self.tcp_flags) is not int or not 0 <= self.tcp_flags <= 255:
            raise ValueError('INVALID_TCP_FLAGS')
        if self.observed_utc is not None and (type(self.observed_utc) is not str or not self.observed_utc):
            raise ValueError('INVALID_CAPTURE_UTC')
        if self.observed_monotonic_ns is not None and (type(self.observed_monotonic_ns) is not int or self.observed_monotonic_ns < 0):
            raise ValueError('INVALID_CAPTURE_MONOTONIC')
        if self.timestamp_provenance not in ('UNKNOWN','LIVE_CALLBACK','PCAP_WALL_CLOCK','REPLAY_ORDINAL','TEST_FIXTURE'):
            raise ValueError('INVALID_CAPTURE_TIMESTAMP_PROVENANCE')

    @property
    def syn(self) -> bool:
        return bool(self.tcp_flags & 0x02)

    @property
    def rst(self) -> bool:
        return bool(self.tcp_flags & 0x04)

    @property
    def fin(self) -> bool:
        return bool(self.tcp_flags & 0x01)


@dataclass(frozen=True, slots=True)
class CapturePoll:
    """Future live-source boundary: bounded batches with explicit loss evidence.

    The actual Windows/Npcap backend is deliberately NOT implemented in P4.
    When dropped > 0 or overflowed is true, consumers must never infer
    transport completeness from observed packets alone.
    """
    source_generation: str
    segments: tuple[CapturedTcpSegment,...] = field(repr=False)
    dropped: int
    overflowed: bool
    exhausted: bool
    driver_drop_visibility: str = "UNKNOWN"

    def __post_init__(self) -> None:
        if not self.source_generation:
            raise ValueError('SOURCE_GENERATION_REQUIRED')
        if not isinstance(self.segments, tuple) or len(self.segments)>4096:
            raise ValueError('POLL_BATCH_TOO_LARGE')
        if type(self.dropped) is not int or self.dropped < 0:
            raise ValueError('POLL_DROPPED_COUNT_INVALID')
        if type(self.overflowed) is not bool or type(self.exhausted) is not bool:
            raise ValueError('POLL_BOOLEAN_INVALID')
        if self.driver_drop_visibility not in ("UNKNOWN", "AVAILABLE_CLEAN", "AVAILABLE_DROPPED"):
            raise ValueError("INVALID_DRIVER_DROP_VISIBILITY")

    @property
    def transport_evidence_complete(self) -> bool:
        # This is a *necessary* condition, never sufficient to certify a stream.
        return self.dropped == 0 and not self.overflowed

    @property
    def live_loss_accounting_complete(self) -> bool:
        """Stronger live guarantee: driver loss accounting must also be known."""
        return self.transport_evidence_complete and self.driver_drop_visibility == "AVAILABLE_CLEAN"


@dataclass(frozen=True, slots=True)
class CaptureScope:
    capture_session_id: str
    server_ports: tuple[int,...]
    flow_client_bindings: tuple[tuple[str,str], ...]

    def __post_init__(self):
        if not self.capture_session_id.startswith('capture-'):
            raise ValueError('INVALID_CAPTURE_SCOPE_SESSION')
        if not self.server_ports or len(set(self.server_ports))!=len(self.server_ports) or any(type(p) is not int or not 1<=p<=65535 for p in self.server_ports):
            raise ValueError('INVALID_CAPTURE_SCOPE_PORTS')
        flows=[f for f,_ in self.flow_client_bindings]
        if len(flows)!=len(set(flows)) or any(not f or not c.startswith('client-') for f,c in self.flow_client_bindings):
            raise ValueError('INVALID_CAPTURE_FLOW_BINDINGS')

@dataclass(frozen=True, slots=True)
class CaptureHealthSnapshot:
    status: str
    emitted_envelopes: int
    emitted_payload_bytes: int
    unresolved_gaps: int
    reconnects: int
    duplicate_segments: int
    reordered_segments: int
    ambiguous_or_unbound_segments: int
    capture_loss_fences: int
    buffer_overflow_fences: int

    def __post_init__(self):
        vals=(self.emitted_envelopes,self.emitted_payload_bytes,self.unresolved_gaps,self.reconnects,self.duplicate_segments,self.reordered_segments,self.ambiguous_or_unbound_segments,self.capture_loss_fences,self.buffer_overflow_fences)
        if any(type(v) is not int or v<0 for v in vals): raise ValueError('INVALID_CAPTURE_HEALTH_COUNT')
        if self.status not in ('CLEAN','UNCERTAIN','NO_TRAFFIC'): raise ValueError('INVALID_CAPTURE_HEALTH_STATUS')
