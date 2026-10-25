"""P47 developer/setup smoke for *research-only* historical wire-stream replay."""
from __future__ import annotations

from hashlib import sha256

from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_lifecycle import BUILD
from anka_protocol.historical_stream_replay import replay_historical_server_stream


def _field(number: int, value: int) -> bytes:
    # The smoke uses tiny, independent hand-authored varint fixtures.
    if not 0 < number < 100 or not 0 <= value < 128:
        raise ValueError('P47_FIXTURE_INVALID')
    return bytes((number << 3, value)) if number < 16 else bytes(((number << 3) & 127 | 128, (number << 3) >> 7, value))


def historical_stream_smoke() -> dict:
    flow = 'p47_synthetic_offline_flow'
    scope = LegacyFightScope(77, sha256(flow.encode()).hexdigest(), 2, BUILD)
    def message(name: str, body: bytes, ordinal: int) -> WireMessage:
        return WireMessage('server_to_client', name, body, ordinal, flow, 2)

    good = replay_historical_server_stream((
        message('jvj', _field(3, 33), 1),
        message('jup', _field(2, 33), 2),
        message('jwp', b'', 3),
    ), scope=scope)
    gap = replay_historical_server_stream((
        message('jvj', _field(3, 33), 1),
        message('mystery', b'', 2),
        message('jup', _field(2, 33), 3),
    ), scope=scope)
    bad = replay_historical_server_stream((
        message('jvj', _field(3, 33), 1),
        message('jup', _field(2, 33), 1),
    ), scope=scope)
    expected = (
        good.status == 'RESEARCH_REPLAY_ONLY' and good.decoded_messages == 3 and
        gap.status == 'PARTIAL_EVIDENCE' and gap.unmapped_wire_messages == 1 and
        bad.status == 'BLOCKED_EVIDENCE' and bad.blocking_issue == 'P47_REPEATED_OR_REORDERED_WIRE_SOURCE' and
        all(not r.current_client_certified and not r.physical_input_sent and
            not r.actionable and not r.canonical_commits for r in (good,gap,bad))
    )
    if not expected:
        raise RuntimeError('P47_HISTORICAL_REPLAY_SMOKE_FAILED')
    return {'status': 'PASS_HISTORICAL_RESEARCH_ONLY',
            'research_events': good.decoded_messages,
            'partial_unknown_wire_detected': gap.first_issue,
            'duplicate_wire_block_detected': bad.blocking_issue,
            'live_ready': False, 'canonical_commits': 0, 'physical_input_sent': False}
