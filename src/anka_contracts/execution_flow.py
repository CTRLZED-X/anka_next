"""P18 fixture-only execution contracts. No physical action authority exists here."""
from __future__ import annotations
from dataclasses import dataclass


def _token(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= 120 and value.isascii() and all(
        c.isalnum() or c in '_.:-' for c in value)


@dataclass(frozen=True, slots=True)
class OfflineActionIntent:
    action_id: str
    action_key: str
    session_id: str
    account_id: str
    client_id: str
    window_generation: int
    fight_id: str
    turn_id: str
    actor_id: int
    state_revision: int
    kind: str
    target_cell: int | None = None
    synthetic_only: bool = True
    actionable: bool = False
    physical_input_permitted: bool = False

    def __post_init__(self):
        values = (self.action_id, self.action_key, self.session_id, self.account_id,
                  self.client_id, self.fight_id, self.turn_id)
        if (not all(_token(v) for v in values)
                or type(self.window_generation) is not int or self.window_generation < 1
                or type(self.actor_id) is not int or not 0 < abs(self.actor_id) < 2**63
                or type(self.state_revision) is not int or self.state_revision < 0
                or self.kind not in ('CAST', 'MOVE', 'READY', 'END_TURN')
                or (self.target_cell is not None and (type(self.target_cell) is not int
                                                      or not 0 <= self.target_cell <= 100000))):
            raise ValueError('P18_ACTION_INTENT_INVALID')
        if (self.synthetic_only is not True or self.actionable is not False
                or self.physical_input_permitted is not False):
            raise ValueError('P18_AUTHORITY_FORGERY')

    def to_dict(self) -> dict:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class OfflineOutcomeEvidence:
    evidence_id: str
    action_id: str
    session_id: str
    account_id: str
    client_id: str
    window_generation: int
    fight_id: str
    turn_id: str
    actor_id: int
    observed_revision: int
    outcome: str
    synthetic_only: bool = True
    authoritative: bool = False
    physical_input_permitted: bool = False

    def __post_init__(self):
        tokens = (self.evidence_id, self.action_id, self.session_id, self.account_id,
                  self.client_id, self.fight_id, self.turn_id)
        if (not all(_token(t) for t in tokens)
                or type(self.window_generation) is not int or self.window_generation < 1
                or type(self.actor_id) is not int or not 0 < abs(self.actor_id) < 2**63
                or type(self.observed_revision) is not int or self.observed_revision < 0
                or self.outcome not in ('ACCEPTED', 'REJECTED', 'INCONCLUSIVE')):
            raise ValueError('P18_OUTCOME_EVIDENCE_INVALID')
        if (self.synthetic_only is not True or self.authoritative is not False
                or self.physical_input_permitted is not False):
            raise ValueError('P18_OUTCOME_AUTHORITY_FORGERY')

    def to_dict(self) -> dict:
        return {field: getattr(self, field) for field in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class OfflineActionAudit:
    action_id: str
    status: str
    reason: str
    event_count: int
    evidence_ids: tuple[str, ...]
    synthetic_only: bool = True
    actionable: bool = False
    physical_input_permitted: bool = False

    def __post_init__(self):
        if (self.synthetic_only is not True or self.actionable is not False
                or self.physical_input_permitted is not False):
            raise ValueError('P18_REPORT_AUTHORITY_FORGERY')

    def to_dict(self) -> dict:
        return {'action_id': self.action_id, 'status': self.status, 'reason': self.reason,
                'event_count': self.event_count, 'evidence_ids': list(self.evidence_ids),
                'synthetic_only': True, 'actionable': False,
                'physical_input_permitted': False, 'selected_action': None}
