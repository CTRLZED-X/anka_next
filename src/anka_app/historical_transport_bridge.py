"""P48: bounded offline CapturePoll -> P6 framing -> P47 research replay.

The composition root is the only consumer importing all three implementation
packages. Capture/poll ownership and continuity are *not* account attribution.
No result from this module may authorize canonical commit or physical input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

from anka_contracts.capture import CapturePoll, CapturedTcpSegment
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.protocol import WireMessage
from anka_capture.transport import TransportAuditor
from anka_protocol.api import ProtocolInspector
from anka_protocol.adapters.historical import load_reference
from anka_protocol.historical_stream_replay import (
    HistoricalStreamReplay, replay_historical_server_stream,
)

MAX_POLLS = 256
MAX_SEGMENTS = 100_000
MAX_REPLAY_INPUT = 4096


@dataclass(frozen=True, slots=True)
class HistoricalTransportResearch:
    """Opaque, bounded evidence receipt; does not contain raw captures or IPs."""
    status: str
    first_issue: str | None
    blocking_issue: str | None
    transport_status: str
    protocol_status: str
    source_segments: int
    framed_server_messages: int
    selected_server_messages: int
    foreign_server_messages: int
    capture_loss_visible: bool
    replay: HistoricalStreamReplay
    source_completeness_verified: bool = field(default=False, init=False)
    account_binding_verified: bool = field(default=False, init=False)
    current_client_certified: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)

    def __post_init__(self):
        if self.status not in {'RESEARCH_TRANSPORT_ONLY','PARTIAL_EVIDENCE','BLOCKED_EVIDENCE'}:
            raise ValueError('P48_REPORT_STATUS_INVALID')
        if (self.status == 'RESEARCH_TRANSPORT_ONLY') != (self.first_issue is None):
            raise ValueError('P48_REPORT_STATUS_REASON_MISMATCH')
        if (self.status == 'BLOCKED_EVIDENCE') != (self.blocking_issue is not None):
            raise ValueError('P48_REPORT_BLOCKER_MISMATCH')
        if not 0 <= self.selected_server_messages <= self.framed_server_messages:
            raise ValueError('P48_REPORT_COUNTS_INVALID')
        if self.framed_server_messages != self.foreign_server_messages + self.selected_server_messages:
            raise ValueError('P48_REPORT_COUNTS_INVALID')
        if not 0 <= self.source_segments <= MAX_SEGMENTS:
            raise ValueError('P48_REPORT_COUNTS_INVALID')


def replay_historical_capture_polls(
    polls: tuple[CapturePoll, ...], *, scope: LegacyFightScope | None, root: Path,
    forensic_without_driver_proof: bool = False,
) -> HistoricalTransportResearch:
    """Read-only trace pipeline. Polls are caller-provided, not independent witnesses.

    The same P6 ProtocolInspector used by the real offline capture path frames
    actual TCP segment bytes. It never marks a selected research trace complete:
    finite polls, SYNs and no visible gaps are only *necessary* observations.
    """
    first: str | None = None
    blocker: str | None = None
    def mark(code: str, *, hard: bool = False):
        nonlocal first, blocker
        if first is None:
            first = code
        if hard and blocker is None:
            blocker = code

    # P49: a saved PCAPNG file has no trustworthy driver-drop counter. Permit
    # *forensic-only* framing of such captures, while retaining a hard blocker.
    # Neither this flag nor any decoded observation can certify source completeness.
    safe_forensic = (type(forensic_without_driver_proof) is bool and
        forensic_without_driver_proof and isinstance(polls, tuple) and bool(polls) and
        all(isinstance(p, CapturePoll) and p.dropped == 0 and
            not p.overflowed and p.driver_drop_visibility == 'UNKNOWN'
            for p in polls))
    segments = ()
    observed: list[WireMessage] = []
    report_protocol = None
    report_transport = None
    loss = False

    if not isinstance(polls, tuple) or not polls or len(polls) > MAX_POLLS:
        mark('P48_POLL_SET_INVALID', hard=True)
    elif any(not isinstance(p, CapturePoll) for p in polls):
        mark('P48_POLL_TYPE_INVALID', hard=True)
    elif sum(len(p.segments) for p in polls) > MAX_SEGMENTS:
        mark('P48_SEGMENT_LIMIT', hard=True)
    elif any(not isinstance(s, CapturedTcpSegment) for p in polls for s in p.segments):
        mark('P48_SEGMENT_TYPE_INVALID', hard=True)
    else:
        generations = {p.source_generation for p in polls}
        if len(generations) != 1:
            mark('P48_CAPTURE_GENERATION_CHANGED', hard=True)
        if any(p.dropped or p.overflowed or p.driver_drop_visibility != 'AVAILABLE_CLEAN' for p in polls):
            loss = True
            mark('P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN', hard=True)
        if any(p.exhausted for p in polls[:-1]) or not polls[-1].exhausted:
            mark('P48_CAPTURE_POLL_BOUNDARY_INCOMPLETE')
        segments = tuple(s for poll in polls for s in poll.segments)
        if not segments:
            mark('P48_NO_SELECTED_SEGMENTS')
        else:
            try:
                report_transport = TransportAuditor().audit(segments)
            except (ValueError, TypeError):
                mark('P48_CAPTURE_ORDER_INVALID', hard=True)
            else:
                if report_transport.status != 'OBSERVED_NO_DETECTED_GAPS':
                    mark('P48_TRANSPORT_NOT_CONTIGUOUS', hard=True)
                if report_transport.reconnects:
                    mark('P48_RECONNECT_SPLITS_FLOW_SCOPE', hard=True)
            allow_forensic = (safe_forensic and
                blocker == 'P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN' and
                report_transport is not None and
                report_transport.status == 'OBSERVED_NO_DETECTED_GAPS' and
                len(generations) == 1 and not any(p.exhausted for p in polls[:-1]) and
                polls[-1].exhausted)
            if (not blocker or allow_forensic) and isinstance(scope, LegacyFightScope):
                try:
                    inspector = ProtocolInspector(load_reference(Path(root)),
                        requested_build=scope.protocol_build, on_message=observed.append)
                    for poll in polls:
                        inspector.consume_poll(poll)
                    report_protocol = inspector.finish()
                except (ValueError, TypeError, OSError):
                    mark('P48_FRAMER_OR_REFERENCE_INVALID', hard=True)
                else:
                    if (report_protocol.invalid_frames or report_protocol.quarantined_streams or
                        report_protocol.unanchored_streams or report_protocol.packet_loss_reported):
                        mark('P48_PROTOCOL_FRAMING_UNTRUSTED', hard=True)
                    # A parseable frame without an Ankama Any envelope can
                    # contain an unstudied control/extension message. The P6
                    # receipt intentionally omits it from `framed_messages`;
                    # do not let a clean P47 *subset* hide that missing frame.
                    if inspector.counts['FRAME_WITHOUT_RECOGNIZED_ENVELOPE']:
                        mark('P48_NON_GAME_OR_UNCLASSIFIED_FRAME')
                    protocol_observed = report_protocol.status == 'HISTORICAL_WIRE_OBSERVATION_ONLY'
                    forensic_incomplete_only = (allow_forensic and
                        report_protocol.status == 'INCOMPLETE_EVIDENCE_OBSERVATION_ONLY' and
                        not report_protocol.invalid_frames and
                        not report_protocol.quarantined_streams and
                        not report_protocol.unanchored_streams)
                    if not (protocol_observed or forensic_incomplete_only):
                        mark('P48_PROTOCOL_BUILD_OR_REFERENCE_UNVERIFIED', hard=True)
    if not isinstance(scope, LegacyFightScope):
        mark('P48_SCOPE_MISSING', hard=True)

    # This comparison is only a caller-supplied selector, never independent proof
    # that the nominated account owns the window/process/flow.
    selected = []
    foreign = 0
    for message in observed:
        if message.direction != 'server_to_client':
            continue
        if (isinstance(scope, LegacyFightScope) and
            sha256(message.flow_key.encode('utf8')).hexdigest() == scope.flow_digest):
            selected.append(message)
        else:
            foreign += 1
    if len(selected) > MAX_REPLAY_INPUT:
        mark('P48_RESEARCH_WIRE_BUDGET_EXCEEDED', hard=True)
        selected = selected[:MAX_REPLAY_INPUT]
    if any(message.generation != scope.generation for message in selected) if isinstance(scope, LegacyFightScope) else False:
        mark('P48_FLOW_GENERATION_MISMATCH', hard=True)
    replay = replay_historical_server_stream(tuple(selected), scope=scope)
    if replay.blocking_issue:
        mark(replay.blocking_issue, hard=True)
    elif replay.first_issue:
        mark(replay.first_issue)
    if not selected and not blocker:
        mark('P48_NO_SELECTED_SERVER_WIRE')
    return HistoricalTransportResearch(
        'BLOCKED_EVIDENCE' if blocker else 'PARTIAL_EVIDENCE' if first else 'RESEARCH_TRANSPORT_ONLY',
        first, blocker, report_transport.status if report_transport else 'NOT_VERIFIED',
        report_protocol.status if report_protocol else 'NOT_VERIFIED', len(segments),
        sum(m.direction == 'server_to_client' for m in observed), len(selected), foreign,
        loss, replay,
    )
