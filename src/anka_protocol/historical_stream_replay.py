"""P47: bounded, provenance-aware *research-only* P45/P46 wire-stream replay.

The old single-message decoders cannot establish completeness or fight authority.
This facade connects them without discarding unknown, unsupported, or conflicting
wire messages.  It never promotes events, mutates game state, or sends input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256

from anka_contracts.historical_lifecycle import LegacyFightScope, LegacyFightObservation
from anka_contracts.historical_combat import HistoricalCombatObservation
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_lifecycle import (
    HistoricalLifecycleDecoder, BUILD as HISTORICAL_BUILD, NAMES as LIFECYCLE_NAMES,
)
from anka_protocol.adapters.historical_combat import (
    HistoricalCombatDecoder, RECOGNIZED as COMBAT_NAMES,
)
from anka_protocol.historical_combined_audit import audit_historical_combined
from anka_protocol.historical_timeline import audit_historical_timeline
from anka_protocol.historical_combat_audit import audit_historical_combat

MAX_WIRE_OBSERVATIONS = 4096
MAX_TOTAL_BODY_BYTES = 16 * 1024 * 1024
MAX_FLOW_KEY_BYTES = 1024
MAX_UNKNOWN_NAME_SUMMARY = 24


@dataclass(frozen=True, slots=True)
class HistoricalStreamReplay:
    """Offline research receipt, not an admission token or live-readiness proof."""
    status: str
    first_issue: str | None
    blocking_issue: str | None
    wire_messages_seen: int
    decoded_messages: int
    unsupported_actions: int
    unmapped_wire_messages: int
    observations: tuple[LegacyFightObservation | HistoricalCombatObservation, ...]
    unknown_wire_names: tuple[str, ...]
    chronology_status: str | None
    chronology_issue: str | None
    lifecycle_audit_status: str | None
    combat_audit_status: str | None
    source_completeness_verified: bool = field(default=False, init=False)
    current_client_certified: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)

    def __post_init__(self):
        if self.status not in {'RESEARCH_REPLAY_ONLY', 'PARTIAL_EVIDENCE', 'BLOCKED_EVIDENCE'}:
            raise ValueError('P47_REPORT_STATUS_INVALID')
        if (self.status == 'RESEARCH_REPLAY_ONLY') != (self.first_issue is None):
            raise ValueError('P47_REPORT_STATUS_REASON_MISMATCH')
        if (self.status == 'BLOCKED_EVIDENCE') != (self.blocking_issue is not None):
            raise ValueError('P47_REPORT_HARD_BLOCKER_REQUIRED')
        if not (0 <= len(self.observations) == self.decoded_messages <= self.wire_messages_seen <= MAX_WIRE_OBSERVATIONS):
            raise ValueError('P47_REPORT_COUNTS_INVALID')
        if (self.unsupported_actions < 0 or self.unmapped_wire_messages < 0 or
                self.decoded_messages + self.unsupported_actions + self.unmapped_wire_messages > self.wire_messages_seen):
            raise ValueError('P47_REPORT_COUNTS_INVALID')
        if len(self.unknown_wire_names) > MAX_UNKNOWN_NAME_SUMMARY:
            raise ValueError('P47_REPORT_UNKNOWN_LIMIT')


def replay_historical_server_stream(
    messages: tuple[WireMessage, ...], *, scope: LegacyFightScope | None,
) -> HistoricalStreamReplay:
    """Decode one ordered *server-flow* research trace; preserve every evidence gap.

    `scope` is caller supplied, NOT independent flow/account attestation. Packet
    ordinals are useful for order checks but cannot prove capture continuity.
    Even `RESEARCH_REPLAY_ONLY` is never eligible for authoritative admission.
    """
    events: list[LegacyFightObservation | HistoricalCombatObservation] = []
    unknown: list[str] = []
    decoded = unsupported = unmapped = seen = total_body_bytes = 0
    problem: str | None = None
    hard_blocker: str | None = None
    severe = False

    def mark(issue: str, *, quarantine: bool = False) -> None:
        nonlocal problem, severe, hard_blocker
        if problem is None:
            problem = issue
        if quarantine and hard_blocker is None:
            hard_blocker = issue
        severe = severe or quarantine

    def report() -> HistoricalStreamReplay:
        life_events = tuple(e for e in events if isinstance(e, LegacyFightObservation))
        combat_events = tuple(e for e in events if isinstance(e, HistoricalCombatObservation))
        combined = audit_historical_combined(tuple(events)) if events else None
        life = audit_historical_timeline(life_events) if life_events else None
        combat = audit_historical_combat(combat_events) if combat_events else None
        if combined and combined.first_issue:
            mark(combined.first_issue, quarantine=combined.status in ('SCOPE_CONFLICT', 'ORDER_CONFLICT'))
        if life and life.first_issue:
            mark(life.first_issue, quarantine=life.status in ('SCOPE_CONFLICT', 'ORDER_CONFLICT'))
        if combat and combat.first_issue:
            mark(combat.first_issue, quarantine=combat.status in ('SCOPE_CONFLICT', 'ORDER_CONFLICT'))
        return HistoricalStreamReplay(
            'BLOCKED_EVIDENCE' if severe else 'PARTIAL_EVIDENCE' if problem else 'RESEARCH_REPLAY_ONLY',
            problem, hard_blocker, seen, decoded, unsupported, unmapped, tuple(events), tuple(unknown),
            combined.status if combined else None, combined.first_issue if combined else None,
            life.status if life else None, combat.status if combat else None,
        )

    if not isinstance(messages, tuple) or len(messages) > MAX_WIRE_OBSERVATIONS:
        mark('P47_STREAM_SIZE_OR_TYPE_INVALID', quarantine=True)
        return report()
    if not messages:
        mark('P47_NO_WIRE_EVIDENCE')
        return report()
    if not isinstance(scope, LegacyFightScope) or scope.protocol_build != HISTORICAL_BUILD:
        mark('P47_SCOPE_OR_BUILD_UNVERIFIED', quarantine=True)
        return report()

    decoder_life = HistoricalLifecycleDecoder(requested_build=HISTORICAL_BUILD)
    decoder_combat = HistoricalCombatDecoder(requested_build=HISTORICAL_BUILD)
    last_cursor = (-1, -1)
    for msg in messages:
        seen += 1
        if not isinstance(msg, WireMessage):
            mark('P47_NOT_A_WIRE_MESSAGE', quarantine=True)
            break
        if msg.direction != 'server_to_client':
            mark('P47_SERVER_ONLY_DIRECTION_REQUIRED', quarantine=True)
            break
        if type(msg.flow_key) is not str:
            mark('P47_FLOW_KEY_INVALID', quarantine=True)
            break
        try:
            flow_bytes = msg.flow_key.encode('utf8', errors='strict')
        except UnicodeError:
            mark('P47_FLOW_KEY_INVALID', quarantine=True)
            break
        if not 1 <= len(flow_bytes) <= MAX_FLOW_KEY_BYTES:
            mark('P47_FLOW_KEY_INVALID', quarantine=True)
            break
        if sha256(flow_bytes).hexdigest() != scope.flow_digest or msg.generation != scope.generation:
            mark('P47_FLOW_OR_GENERATION_MISMATCH', quarantine=True)
            break
        total_body_bytes += len(msg.body)
        if total_body_bytes > MAX_TOTAL_BODY_BYTES:
            mark('P47_STREAM_BODY_BUDGET_EXCEEDED', quarantine=True)
            break
        cursor = (msg.packet_number, msg.message_index)
        if cursor <= last_cursor:
            mark('P47_REPEATED_OR_REORDERED_WIRE_SOURCE', quarantine=True)
            break
        last_cursor = cursor
        if msg.name in LIFECYCLE_NAMES:
            result = decoder_life.decode(msg, scope=scope)
        elif msg.name in COMBAT_NAMES:
            result = decoder_combat.decode(msg, scope=scope)
        else:
            unmapped += 1
            if msg.name not in unknown and len(unknown) < MAX_UNKNOWN_NAME_SUMMARY:
                unknown.append(msg.name)
            mark('P47_UNMAPPED_WIRE_SEMANTICS')
            continue
        if result.status == 'UNSUPPORTED_ACTION':
            unsupported += 1
            mark(result.failure_code or 'P47_UNSUPPORTED_COMBAT_ACTION')
            continue
        if result.status != 'OBSERVATIONS_ONLY' or len(result.observations) != 1:
            mark(result.failure_code or ('P47_DECODER_' + result.status), quarantine=True)
            break
        events.extend(result.observations)
        decoded += 1
    if not events and not problem:
        mark('P47_NO_DECODED_OBSERVATIONS')
    # A research chronology cannot turn a caller-provided flow scope or unknown
    # capture continuity into authoritative game truth.
    return report()
