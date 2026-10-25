"""P17 immutable, strictly synthetic party lifecycle contracts.

These types cannot represent certified game observations or execution authority.
An account name or a ready event alone never proves fight/turn ownership.
"""
from __future__ import annotations
from dataclasses import dataclass, field


def _token(v: object) -> bool:
    return type(v) is str and 1 <= len(v) <= 100 and v.isascii() and all(
        c.isalnum() or c in '_.-' for c in v)


@dataclass(frozen=True, slots=True)
class PartyMember:
    account_id: str
    generation: int
    actor_id: int
    role: str

    def __post_init__(self):
        if (not _token(self.account_id) or type(self.generation) is not int or self.generation < 0
                or type(self.actor_id) is not int or self.actor_id == 0 or abs(self.actor_id) >= 2**63
                or self.role not in ('leader', 'follower')):
            raise ValueError('P17_MEMBER_INVALID')


KINDS = frozenset({'READY', 'FIGHT_STARTED', 'TURN_STARTED', 'END_TURN_INTENDED',
                   'TURN_ENDED', 'FIGHT_ENDED', 'CHECK', 'DISCONNECTED'})
ACCOUNT_KINDS = frozenset({'READY', 'TURN_STARTED', 'END_TURN_INTENDED', 'TURN_ENDED', 'DISCONNECTED'})
FIGHT_KINDS = frozenset({'FIGHT_STARTED', 'TURN_STARTED', 'END_TURN_INTENDED', 'TURN_ENDED', 'FIGHT_ENDED'})


@dataclass(frozen=True, slots=True)
class PartyFixtureEvent:
    sequence: int
    tick: int
    kind: str
    event_id: str
    account_id: str | None = None
    generation: int | None = None
    actor_id: int | None = None
    fight_id: str | None = None
    origin: str = field(default='SYNTHETIC_FIXTURE_ONLY', init=False)

    def __post_init__(self):
        if type(self.sequence) is not int or self.sequence <= 0 or type(self.tick) is not int or self.tick < 0:
            raise ValueError('P17_ORDER_INVALID')
        if self.kind not in KINDS or not _token(self.event_id):
            raise ValueError('P17_EVENT_INVALID')
        if self.kind in ACCOUNT_KINDS:
            if (not _token(self.account_id) or type(self.generation) is not int or self.generation < 0
                    or type(self.actor_id) is not int or self.actor_id == 0 or abs(self.actor_id) >= 2**63):
                raise ValueError('P17_ACCOUNT_EVENT_INVALID')
        elif any(v is not None for v in (self.account_id, self.generation, self.actor_id)):
            raise ValueError('P17_EXTRANEOUS_ACCOUNT')
        if self.kind in FIGHT_KINDS:
            if not _token(self.fight_id):
                raise ValueError('P17_FIGHT_REQUIRED')
        elif self.fight_id is not None:
            raise ValueError('P17_EXTRANEOUS_FIGHT')


@dataclass(frozen=True, slots=True)
class PartyTimelineReport:
    status: str
    fight_id: str | None
    turn_owner: int | None
    ready_accounts: tuple[str, ...]
    pending_end_actor: int | None
    reasons: tuple[str, ...]
    next_evidence: tuple[str, ...]
    last_sequence: int
    first_failed_sequence: int | None
    trace: tuple[tuple[int, str, str], ...]
    synthetic_only: bool = True
    authoritative: bool = False
    actionable: bool = False
    physical_input_permitted: bool = False

    def __post_init__(self):
        if (self.synthetic_only is not True or self.authoritative is not False
                or self.actionable is not False or self.physical_input_permitted is not False):
            raise ValueError('P17_AUTHORITY_FORGERY')

    def to_dict(self):
        return {'status': self.status, 'fight_id': self.fight_id, 'turn_owner': self.turn_owner,
                'ready_accounts': list(self.ready_accounts), 'pending_end_actor': self.pending_end_actor,
                'reasons': list(self.reasons), 'next_evidence': list(self.next_evidence),
                'last_sequence': self.last_sequence, 'first_failed_sequence': self.first_failed_sequence,
                'trace': [{'sequence': a, 'kind': b, 'phase': c} for a, b, c in self.trace],
                'synthetic_only': True, 'authoritative': False, 'actionable': False,
                'physical_input_permitted': False, 'selected_action': None}
