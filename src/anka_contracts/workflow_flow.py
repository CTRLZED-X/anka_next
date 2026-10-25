"""P17 mission contract consumes coordination RESULTS, never its implementation."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.coordination_flow import PartyTimelineReport


@dataclass(frozen=True, slots=True)
class SyntheticFightOutcome:
    fight_id: str
    outcome: str
    observation_id: str

    def __post_init__(self):
        def token(s):return type(s) is str and 1 <= len(s) <= 100 and s.isascii() and all(c.isalnum() or c in '_.-' for c in s)
        if not all(token(s) for s in (self.fight_id, self.observation_id)) or self.outcome not in ('VICTORY', 'DEFEAT'):
            raise ValueError('P17_OUTCOME_FIXTURE_INVALID')


@dataclass(frozen=True, slots=True)
class MissionResearchReport:
    status: str
    confirmed_synthetic_wins: int
    synthetic_losses: int
    unresolved_fights: int
    reasons: tuple[str,...]
    synthetic_only: bool = True
    actionable: bool = False
    authoritative: bool = False

    def __post_init__(self):
        if self.synthetic_only is not True or self.actionable is not False or self.authoritative is not False:
            raise ValueError('P17_MISSION_AUTHORITY_FORGERY')

    def to_dict(self):
        return {'status': self.status, 'synthetic_wins': self.confirmed_synthetic_wins,
                'synthetic_losses': self.synthetic_losses, 'unresolved_fights': self.unresolved_fights,
                'reasons': list(self.reasons), 'synthetic_only': True,
                'actionable': False, 'authoritative': False, 'physical_input_permitted': False}
