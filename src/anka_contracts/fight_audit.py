"""Independent read-only fight evidence audit contracts (P11).

This contract is intentionally unable to represent authoritative game control.
Multiple process-local observations are not automatically simultaneous facts.
"""
from __future__ import annotations
from dataclasses import dataclass


def _token(value:str)->bool:
    return (type(value) is str and 1<=len(value)<=100 and value.isascii()
            and all(c.isalnum() or c in '_.-' for c in value))

@dataclass(frozen=True,slots=True)
class AccountExpectation:
    session_id:str
    account_id:str
    account_generation:int
    local_actor_id:int

    def __post_init__(self):
        if not (_token(self.session_id) and _token(self.account_id)):
            raise ValueError('FIGHT_AUDIT_SCOPE_INVALID')
        if (type(self.account_generation) is not int or self.account_generation<0
            or type(self.local_actor_id) is not int or self.local_actor_id==0 or abs(self.local_actor_id)>=2**63):
            raise ValueError('FIGHT_AUDIT_SCOPE_INVALID')

@dataclass(frozen=True,slots=True)
class FightEvidenceReport:
    status:str
    observed_fight_id:str|None
    observed_turn_owner:int|None
    reasons:tuple[str,...]
    account_findings:tuple[dict,...]
    same_database_snapshot:bool
    shared_live_event_proof:bool=False
    actionable:bool=False
    authoritative:bool=False

    def to_dict(self)->dict:
        return {'status':self.status,'observed_fight_id':self.observed_fight_id,
                'observed_turn_owner':self.observed_turn_owner,'reasons':list(self.reasons),
                'accounts':[dict(item) for item in self.account_findings],
                'same_database_snapshot':self.same_database_snapshot,
                'shared_live_event_proof':False,'authoritative':False,'actionable':False}
