"""P49: bounded, non-authoritative PCAPNG -> CapturePoll -> historical research.

A PCAPNG lacks independent packet-driver drop attestations. We can extract
possible historical observations from coherent saved bytes, but such results
are *always* blocked from canonical admission, actions or live certification.
The source is hashed across both parsing passes to detect file replacement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from anka_app.historical_transport_bridge import (
    HistoricalTransportResearch, replay_historical_capture_polls,
)
from anka_capture.api import (
    CaptureReceipt, CaptureRejected, MAX_CAPTURE_BYTES, MAX_CAPTURE_SEGMENTS,
    inspect_pcapng, validate_ports,
)
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_contracts.capture import CapturePoll
from anka_contracts.historical_lifecycle import LegacyFightScope

MAX_POLL_SEGMENTS = 4096


@dataclass(frozen=True, slots=True)
class HistoricalPcapngResearch:
    status: str
    reason: str
    capture: CaptureReceipt | None
    transport_research: HistoricalTransportResearch | None
    capture_sha256: str | None
    packet_records: int
    observed_historical_events: int
    source_completeness_verified: bool = field(default=False, init=False)
    account_binding_verified: bool = field(default=False, init=False)
    current_client_certified: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    authority: str = field(default='HISTORICAL_PCAPNG_RESEARCH_ONLY', init=False)

    def __post_init__(self):
        if self.status != 'BLOCKED_EVIDENCE':
            raise ValueError('P49_FILE_RESEARCH_ALWAYS_UNCERTIFIED')
        if not isinstance(self.reason, str) or not self.reason.startswith('P49_'):
            raise ValueError('P49_REASON_INVALID')
        if self.packet_records < 0 or self.observed_historical_events < 0:
            raise ValueError('P49_COUNTS_INVALID')


def inspect_historical_pcapng(
    path: Path, *, root: Path, ports: tuple[int, ...], scope: LegacyFightScope | None,
) -> HistoricalPcapngResearch:
    """Read a bounded source file twice; SHA match prevents mixed-revision replay.

    This research artifact is never trusted as an independent gameplay witness.
    No driver loss accounting or PID/HWND/character binding is supplied by a
    PCAPNG file. Raw capture bytes, IPs, payloads and paths never enter reports.
    """
    def rejected(reason: str, receipt: CaptureReceipt | None = None):
        return HistoricalPcapngResearch('BLOCKED_EVIDENCE', reason, receipt, None,
            receipt.source_sha256 if receipt else None,
            receipt.packet_records if receipt else 0, 0)

    try:
        validate_ports(ports)
    except (CaptureRejected, TypeError, ValueError):
        return rejected('P49_PORTS_INVALID')
    if not isinstance(scope, LegacyFightScope):
        return rejected('P49_SCOPE_UNVERIFIED')
    try:
        # Existing capture inspection enforces the 32-MB PCAPNG/100k-segment
        # budget and refuses unsupported link types and fragmented TCP.
        receipt = inspect_pcapng(Path(path), server_ports=ports)
    except (CaptureRejected, OSError, TypeError, ValueError):
        return rejected('P49_PCAPNG_REJECTED')
    try:
        file = Path(path)
        if file.stat().st_size > MAX_CAPTURE_BYTES:
            return rejected('P49_CAPTURE_CHANGED', receipt)
        raw = file.read_bytes()
        if len(raw) != receipt.source_bytes or sha256(raw).hexdigest() != receipt.source_sha256:
            return rejected('P49_CAPTURE_CHANGED', receipt)
        segments = tuple(read_pcapng_tcp_segments(file, server_ports=set(ports), raw=raw))
        if len(segments) != receipt.selected_segments or len(segments) > MAX_CAPTURE_SEGMENTS:
            return rejected('P49_CAPTURE_CHANGED', receipt)
    except (OSError, ValueError, TypeError, MemoryError, OverflowError):
        return rejected('P49_CAPTURE_REPLAY_REJECTED', receipt)
    finally:
        # Deliberately do not retain raw bytes in a report or diagnostic bundle.
        raw = None

    # Source-generation labels refer only to *this* file's immutable bytes.
    # They are not equivalent to a real Npcap process generation/witness.
    generation = 'offline-pcapng-' + receipt.source_sha256[:24]
    polls = tuple(CapturePoll(generation, tuple(segments[i:i + MAX_POLL_SEGMENTS]),
        0, False, i + MAX_POLL_SEGMENTS >= len(segments), 'UNKNOWN')
        for i in range(0, len(segments), MAX_POLL_SEGMENTS))
    if not polls:
        polls = (CapturePoll(generation, (), 0, False, True, 'UNKNOWN'),)
    trace = replay_historical_capture_polls(
        polls, scope=scope, root=Path(root), forensic_without_driver_proof=True,
    )
    # The classifier intentionally stays BLOCKED even if historical messages
    # were decoded. No implicit or explicit promotion path exists here.
    if trace.status != 'BLOCKED_EVIDENCE':
        return rejected('P49_UNCERTIFIED_CAPTURE_NOT_BLOCKED', receipt)
    reason = ('P49_NO_SELECTED_FLOW_PROOF' if trace.selected_server_messages == 0 else
              'P49_DRIVER_LOSS_AND_ACCOUNT_PROOF_MISSING')
    return HistoricalPcapngResearch('BLOCKED_EVIDENCE', reason, receipt,
        trace, receipt.source_sha256, receipt.packet_records,
        trace.replay.decoded_messages)
