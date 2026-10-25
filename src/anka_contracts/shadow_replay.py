"""P33 immutable, non-authoritative bridge contracts for research replay.

These types deliberately cannot request state commits or input authority.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ShadowScope:
    session_id: str
    account_id: str
    account_generation: int
    fight_id: int
    roster_fixture: tuple[int, ...]
    protocol_build: str
    adapter_id: str
    flow_digest: str
    transport_generation: int

    def __post_init__(self):
        def token(v):
            return isinstance(v, str) and 0 < len(v) <= 90 and all(
                c.isascii() and (c.isalnum() or c in '_.-') for c in v)
        if not token(self.session_id) or not token(self.account_id):
            raise ValueError('P33_SHADOW_SESSION_INVALID')
        if type(self.account_generation) is not int or self.account_generation < 0:
            raise ValueError('P33_SHADOW_GENERATION_INVALID')
        if type(self.fight_id) is not int or not 0 < self.fight_id < 2**63:
            raise ValueError('P33_SHADOW_FIGHT_INVALID')
        if (not isinstance(self.roster_fixture, tuple) or len(self.roster_fixture) > 64
            or not self.roster_fixture or len(set(self.roster_fixture)) != len(self.roster_fixture)
            or any(type(v) is not int or v == 0 or abs(v) >= 2**63 for v in self.roster_fixture)):
            raise ValueError('P33_SHADOW_ROSTER_INVALID')
        if not token(self.protocol_build.replace(' ', '_')) or not token(self.adapter_id):
            raise ValueError('P33_SHADOW_ADAPTER_INVALID')
        if not isinstance(self.flow_digest, str) or len(self.flow_digest) != 64 or any(c not in '0123456789abcdef' for c in self.flow_digest):
            raise ValueError('P33_SHADOW_FLOW_INVALID')
        if type(self.transport_generation) is not int or self.transport_generation < 0:
            raise ValueError('P33_SHADOW_FLOW_GENERATION_INVALID')


@dataclass(frozen=True, slots=True)
class ShadowEventSpec:
    """Synthetic projection instruction, never a production Canonical event."""
    kind: str
    actor_id: int | None = None
    resource: str | None = None
    value: int | None = None
    maximum: int | None = None
    cooldowns: tuple[tuple[int, int], ...] = ()
    origin: str = field(default='SYNTHETIC_REPLAY_SPEC_ONLY', init=False)


@dataclass(frozen=True, slots=True)
class ShadowReplayReport:
    status: str
    reason_codes: tuple[str, ...]
    observed: int
    fixture_events: int
    projected_events: int
    final_phase: str | None
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL', init=False)
    committed_events: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    live_state_mutated: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self):
        if self.status not in {'SHADOW_CONSISTENT_RESEARCH_ONLY','SHADOW_INCOMPLETE_RESEARCH','SHADOW_BLOCKED'}:
            raise ValueError('P33_SHADOW_STATUS_INVALID')
        if (type(self.observed) is not int or self.observed < 0
            or type(self.fixture_events) is not int or self.fixture_events < 0
            or type(self.projected_events) is not int or self.projected_events < 0):
            raise ValueError('P33_SHADOW_COUNTS_INVALID')
        if not isinstance(self.reason_codes, tuple) or any(not isinstance(r,str) or len(r)>120 for r in self.reason_codes):
            raise ValueError('P33_SHADOW_REASON_INVALID')

    def to_dict(self) -> dict:
        return {
            'status': self.status, 'reason_codes': list(self.reason_codes),
            'observed': self.observed, 'fixture_events': self.fixture_events,
            'projected_events': self.projected_events, 'final_phase': self.final_phase,
            'authority': self.authority, 'committed_events': 0,
            'physical_input_sent': False, 'live_state_mutated': False,
            'actionable': False, 'current_build_certified': False,
            'roster_is_synthetic_fixture': True,
        }
