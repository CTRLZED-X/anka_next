"""P50: read-only, source-bound inventory of possible game TCP flows in PCAPNG.

Never identify an account, fight, character, client process, or current protocol
build from network endpoints. Hashed flow IDs are candidate selectors only.
The inventory pins the *exact* saved file revision used by P49 research replay.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from anka_app.historical_pcapng_bridge import HistoricalPcapngResearch, inspect_historical_pcapng
from anka_capture.api import CaptureRejected, MAX_CAPTURE_BYTES, MAX_CAPTURE_SEGMENTS, inspect_pcapng, validate_ports
from anka_capture.pcapng import read_pcapng_tcp_segments
from anka_capture.transport import TransportAuditor
from anka_contracts.historical_lifecycle import LegacyFightScope

MAX_DISCOVERED_FLOWS = 64


@dataclass(frozen=True, slots=True)
class FlowCandidate:
    flow_digest: str
    first_packet_number: int
    last_packet_number: int
    server_segments: int
    client_segments: int
    server_payload_segments: int
    client_payload_segments: int
    server_syn_seen: bool
    client_syn_seen: bool
    fin_or_reset_seen: bool
    transport_status: str
    observed_reconnects: int
    observed_gaps: int
    account_binding_verified: bool = field(default=False, init=False)
    complete_capture_verified: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self):
        if len(self.flow_digest) != 64 or any(x not in '0123456789abcdef' for x in self.flow_digest):
            raise ValueError('P50_FLOW_DIGEST_INVALID')
        if not (1 <= self.first_packet_number <= self.last_packet_number):
            raise ValueError('P50_PACKET_SCOPE_INVALID')
        if not (self.server_segments + self.client_segments > 0 and
                0 <= self.server_payload_segments <= self.server_segments and
                0 <= self.client_payload_segments <= self.client_segments and
                min(self.observed_reconnects, self.observed_gaps) >= 0):
            raise ValueError('P50_FLOW_COUNTS_INVALID')


@dataclass(frozen=True, slots=True)
class PcapngFlowInventory:
    status: str
    reason: str
    capture_sha256: str | None
    packet_records: int
    selected_segments: int
    flows: tuple[FlowCandidate, ...]
    source_completeness_verified: bool = field(default=False, init=False)
    account_binding_verified: bool = field(default=False, init=False)
    current_client_certified: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    authority: str = field(default='PCAPNG_FLOW_RECONNAISSANCE_ONLY', init=False)

    def __post_init__(self):
        if self.status not in ('CANDIDATES_ONLY', 'BLOCKED_EVIDENCE'):
            raise ValueError('P50_REPORT_STATUS_INVALID')
        if self.reason not in ('P50_ACCOUNT_IDENTITY_UNVERIFIED', 'P50_PCAPNG_REJECTED',
                               'P50_CAPTURE_CHANGED', 'P50_FLOW_LIMIT', 'P50_NO_SELECTED_FLOW',
                               'P50_PORTS_INVALID', 'P50_CAPTURE_REPLAY_REJECTED'):
            raise ValueError('P50_REPORT_REASON_INVALID')
        if (self.status == 'CANDIDATES_ONLY') != (self.reason == 'P50_ACCOUNT_IDENTITY_UNVERIFIED'):
            raise ValueError('P50_REPORT_SHAPE_INVALID')
        if (self.status == 'CANDIDATES_ONLY') != bool(self.flows):
            raise ValueError('P50_REPORT_CANDIDATES_INVALID')
        if self.selected_segments < 0 or self.packet_records < 0 or len(self.flows) > MAX_DISCOVERED_FLOWS:
            raise ValueError('P50_REPORT_COUNT_INVALID')
        if self.flows and self.selected_segments != sum(f.server_segments + f.client_segments for f in self.flows):
            raise ValueError('P50_REPORT_SEGMENTS_INCONSISTENT')
        if len({f.flow_digest for f in self.flows}) != len(self.flows):
            raise ValueError('P50_REPORT_DUPLICATE_DIGEST')


def inspect_pcapng_flow_inventory(path: Path, *, ports: tuple[int, ...]) -> PcapngFlowInventory:
    """Discover flows with opaque digests; verify the same bounded snapshot twice.

    This is forensic organization, not packet-driver certification or player
    identity. Neither PCAPNG nor any hash can prove which process owns a flow.
    """
    def blocked(code: str):
        return PcapngFlowInventory('BLOCKED_EVIDENCE', code, None, 0, 0, ())

    try:
        validate_ports(ports)
    except (CaptureRejected, ValueError, TypeError):
        return blocked('P50_PORTS_INVALID')
    try:
        receipt = inspect_pcapng(Path(path), server_ports=ports)
    except (CaptureRejected, OSError, ValueError, TypeError):
        return blocked('P50_PCAPNG_REJECTED')
    try:
        file = Path(path)
        if file.stat().st_size > MAX_CAPTURE_BYTES:
            return blocked('P50_CAPTURE_CHANGED')
        raw = file.read_bytes()
        if len(raw) != receipt.source_bytes or sha256(raw).hexdigest() != receipt.source_sha256:
            return blocked('P50_CAPTURE_CHANGED')
        segments = read_pcapng_tcp_segments(file, server_ports=set(ports), raw=raw)
        if len(segments) != receipt.selected_segments or len(segments) > MAX_CAPTURE_SEGMENTS:
            return blocked('P50_CAPTURE_CHANGED')
        grouped = defaultdict(list)
        for seg in segments:
            grouped[seg.flow_id].append(seg)
            if len(grouped) > MAX_DISCOVERED_FLOWS:
                return blocked('P50_FLOW_LIMIT')
        flows = []
        for flow_id, group in grouped.items():
            health = TransportAuditor().audit(tuple(group))
            flows.append(FlowCandidate(
                sha256(flow_id.encode('utf-8')).hexdigest(),
                group[0].packet_number, group[-1].packet_number,
                sum(s.direction == 'server_to_client' for s in group),
                sum(s.direction == 'client_to_server' for s in group),
                sum(s.direction == 'server_to_client' and bool(s.payload) for s in group),
                sum(s.direction == 'client_to_server' and bool(s.payload) for s in group),
                any(s.direction == 'server_to_client' and s.syn for s in group),
                any(s.direction == 'client_to_server' and s.syn for s in group),
                any(s.fin or s.rst for s in group),
                health.status, health.reconnects, health.unresolved_gap_directions,
            ))
        flows.sort(key=lambda f: (f.first_packet_number, f.flow_digest))
    except (ValueError, OSError, TypeError, OverflowError, MemoryError, UnicodeError):
        return blocked('P50_CAPTURE_REPLAY_REJECTED')
    finally:
        raw = None
    if not flows:
        return PcapngFlowInventory('BLOCKED_EVIDENCE','P50_NO_SELECTED_FLOW',
            receipt.source_sha256,receipt.packet_records,receipt.selected_segments,())
    return PcapngFlowInventory('CANDIDATES_ONLY','P50_ACCOUNT_IDENTITY_UNVERIFIED',
        receipt.source_sha256,receipt.packet_records,receipt.selected_segments,tuple(flows))


@dataclass(frozen=True, slots=True)
class InventoriedFlowResearch:
    status: str
    reason: str
    inventory_sha256: str | None
    research: HistoricalPcapngResearch | None
    account_binding_verified: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.status != 'BLOCKED_EVIDENCE' or not self.reason.startswith('P50_'):
            raise ValueError('P50_SELECTED_RESEARCH_MUST_REMAIN_BLOCKED')


def replay_inventoried_pcapng_flow(
    path: Path, *, root: Path, ports: tuple[int, ...], inventory: PcapngFlowInventory,
    scope: LegacyFightScope,
) -> InventoriedFlowResearch:
    """Reject stale inventory, missing flow or forged snapshot before P49 replay.

    Scope and selected digest are supplied by the investigator, *not* certified
    character/flow witnesses. The P49 decoder remains forever research-only.
    """
    def blocked(reason: str):
        return InventoriedFlowResearch('BLOCKED_EVIDENCE', reason, None, None)
    if not isinstance(inventory, PcapngFlowInventory) or inventory.status != 'CANDIDATES_ONLY':
        return blocked('P50_INVENTORY_REQUIRED')
    if not isinstance(scope, LegacyFightScope) or scope.flow_digest not in {f.flow_digest for f in inventory.flows}:
        return blocked('P50_FLOW_NOT_IN_INVENTORY')
    if (not isinstance(inventory.capture_sha256, str) or len(inventory.capture_sha256) != 64 or
            any(ch not in '0123456789abcdef' for ch in inventory.capture_sha256)):
        return blocked('P50_INVENTORY_SOURCE_INVALID')
    # A frozen dataclass is not a signed evidence certificate. Recreate the
    # opaque candidates independently from the file before selecting a scope;
    # neither forged digests nor stale flow boundaries may pass selection.
    refreshed = inspect_pcapng_flow_inventory(path, ports=ports)
    if refreshed.capture_sha256 != inventory.capture_sha256:
        return blocked('P50_INVENTORY_SOURCE_CHANGED')
    if (refreshed.status != 'CANDIDATES_ONLY' or refreshed.flows != inventory.flows or
            refreshed.packet_records != inventory.packet_records or
            refreshed.selected_segments != inventory.selected_segments):
        return blocked('P50_INVENTORY_FLOWS_UNVERIFIED')
    research = inspect_historical_pcapng(path, root=root, ports=ports, scope=scope)
    if research.capture_sha256 != inventory.capture_sha256:
        return blocked('P50_INVENTORY_SOURCE_CHANGED')
    if research.capture is None or (research.capture.packet_records != inventory.packet_records or
                                    research.capture.selected_segments != inventory.selected_segments):
        return blocked('P50_INVENTORY_COUNTS_CHANGED')
    return InventoriedFlowResearch('BLOCKED_EVIDENCE', 'P50_RESEARCH_ONLY',
        inventory.capture_sha256, research)
