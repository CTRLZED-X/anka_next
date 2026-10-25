"""P9 pure state-evidence quality evaluator: describes gaps, never authorizes input.

This evaluator is intentionally separate from the P8 reducer and journal.
It can inspect replayed synthetic snapshots without changing the durable ledger.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

_REQUIRED = ('hp', 'max_hp', 'AP', 'MP', 'cell_id', 'cooldowns')

@dataclass(frozen=True, slots=True)
class StateQualityReport:
    status: str
    revision: int | None
    actor_id: int
    failures: tuple[str, ...]
    missing_fields: tuple[str, ...]
    phase: str | None
    # No demonstrated current-build observation means *never* actionable.
    actionable: bool = False
    authoritative: bool = False
    def to_dict(self) -> dict:
        return {'status':self.status, 'revision':self.revision,
                'actor_id':self.actor_id,'failures':list(self.failures),
                'missing_fields':list(self.missing_fields),'phase':self.phase,
                'actionable':False,'authoritative':False}


def inspect_state_quality(snapshot:dict|None, *, session_id:str, account_id:str,
                          account_generation:int, actor_id:int,
                          minimum_revision:int=1) -> StateQualityReport:
    if not isinstance(session_id,str) or not session_id or not isinstance(account_id,str) or not account_id:
        raise ValueError('QUALITY_SCOPE_INVALID')
    if any(type(x) is not int for x in (account_generation,actor_id,minimum_revision)) or account_generation<0 or actor_id==0 or minimum_revision<1:
        raise ValueError('QUALITY_SCOPE_INVALID')
    if snapshot is None:
        return StateQualityReport('MISSING_EVIDENCE',None,actor_id,('NO_SNAPSHOT',),tuple(_REQUIRED),None)
    if not isinstance(snapshot,dict):
        raise TypeError('QUALITY_SNAPSHOT_REQUIRED')
    failures=set()
    if snapshot.get('authority') != 'SYNTHETIC_FIXTURE_ONLY' or snapshot.get('actionable') is not False:
        failures.add('UNSUPPORTED_STATE_AUTHORITY')
    if (snapshot.get('session_id'), snapshot.get('account_id'),snapshot.get('account_generation')) != (session_id,account_id,account_generation):
        failures.add('ACCOUNT_OR_PROCESS_GENERATION_MISMATCH')
    rev=snapshot.get('revision')
    if type(rev) is not int or rev<minimum_revision:
        failures.add('STALE_OR_INVALID_REVISION')
    phase=snapshot.get('phase')
    if phase != 'IN_FIGHT':failures.add('NO_ACTIVE_FIGHT')
    actors=snapshot.get('actors')
    if not isinstance(actors,dict):
        failures.add('ACTOR_STATE_INVALID'); actors={}
    actor=actors.get(str(actor_id))
    if not isinstance(actor,dict):
        failures.add('ACTOR_NOT_OBSERVED');actor={}
    missing=tuple(field for field in _REQUIRED if actor.get(field) is None)
    if missing:failures.add('MISSING_DECISION_FIELDS')
    hp=actor.get('hp');max_hp=actor.get('max_hp')
    if hp is not None and max_hp is not None and (type(hp) is not int or type(max_hp) is not int or hp<0 or hp>max_hp):
        failures.add('HP_INCONSISTENT')
    if hp==0:failures.add('ACTOR_DEFEATED')
    owner=snapshot.get('turn_owner_id')
    if owner is None:failures.add('TURN_OWNER_UNPROVEN')
    elif owner!=actor_id:failures.add('NOT_ACTOR_TURN')
    if owner is not None and str(owner) not in actors:
        failures.add('TURN_OWNER_NOT_IN_ACTOR_SET')
    # Important: full fields do not imply freshness or authoritative provenance.
    failures.add('CURRENT_BUILD_EVIDENCE_NOT_CERTIFIED')
    return StateQualityReport('SIMULATED_ONLY' if not failures - {'CURRENT_BUILD_EVIDENCE_NOT_CERTIFIED'} else 'INCOMPLETE_OR_INCONSISTENT',
                              rev if type(rev) is int else None,actor_id,tuple(sorted(failures)),missing,
                              phase if isinstance(phase,str) else None)
