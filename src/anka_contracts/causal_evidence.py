"""P22 synthetic-only links between a party observation and its journal source.

A link is an *audit claim*, never an admission token. In particular, cross-
account chronology is NOT proven by reading two per-account histories together.
"""
from __future__ import annotations
from dataclasses import dataclass


def _token(value: object) -> bool:
    return (type(value) is str and 1 <= len(value) <= 100 and value.isascii()
            and all(c.isalnum() or c in '._-' for c in value))


@dataclass(frozen=True, slots=True)
class PartySourceLink:
    party_event_id: str
    source_session_id: str
    source_event_id: str

    def __post_init__(self):
        if not all(_token(x) for x in (self.party_event_id, self.source_session_id, self.source_event_id)):
            raise ValueError('P22_SOURCE_LINK_INVALID')


@dataclass(frozen=True, slots=True)
class PartySourceAudit:
    reasons: tuple[str, ...]
    checked_links: int
    linked_party_events: int
    synthetic_only: bool = True
    authoritative: bool = False
    actionable: bool = False
    cross_account_order_verified: bool = False

    def __post_init__(self):
        if (self.synthetic_only is not True or self.authoritative is not False
                or self.actionable is not False or self.cross_account_order_verified is not False):
            raise ValueError('P22_AUTHORITY_FORGERY')

    @property
    def status(self) -> str:
        return 'BLOCKED_SYNTHETIC' if self.reasons else 'PASS_SYNTHETIC_LINKAGE'

    def to_dict(self) -> dict:
        return {'status': self.status, 'first_failure': self.reasons[0] if self.reasons else None,
                'reasons': list(self.reasons), 'checked_links': self.checked_links,
                'linked_party_events': self.linked_party_events, 'synthetic_only': True,
                'authoritative': False, 'actionable': False,
                'cross_account_order_verified': False,
                'physical_input_permitted': False}
