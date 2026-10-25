"""P31 research-only fight observations, *never* admitted game-state events.

Source provenance is mandatory. A wire message that merely resembles a fight
message cannot grant authoritative turn ownership or a server outcome.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from anka_contracts.canonical import EvidenceRef

KINDS = frozenset({'FIGHT_START_OBSERVED','FIGHT_END_OBSERVED',
                   'TURN_START_OBSERVED','TURN_END_OBSERVED',
                   'ACTOR_CELL_OBSERVED','SPELL_CAST_OBSERVED'})

@dataclass(frozen=True, slots=True)
class FightResearchDraft:
    kind: str
    evidence: EvidenceRef
    fight_id: int
    actor_id: int | None = None
    turn_index: int | None = None
    cell_id: int | None = None
    spell_id: int | None = None
    target_cell: int | None = None
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL',init=False)
    def __post_init__(self):
        if self.kind not in KINDS: raise ValueError('FIGHT_RESEARCH_KIND_INVALID')
        if not isinstance(self.evidence, EvidenceRef):
            raise ValueError('FIGHT_RESEARCH_PROVENANCE_REQUIRED')
        if type(self.fight_id) is not int or not 0 < self.fight_id < 2**63:
            raise ValueError('FIGHT_RESEARCH_ID_INVALID')
        if self.kind in ('FIGHT_START_OBSERVED','FIGHT_END_OBSERVED'):
            if any(x is not None for x in (self.actor_id,self.turn_index,self.cell_id,self.spell_id,self.target_cell)):
                raise ValueError('FIGHT_RESEARCH_EXTRANEOUS_FIELD')
        elif self.kind in ('TURN_START_OBSERVED','TURN_END_OBSERVED'):
            if (type(self.actor_id) is not int or self.actor_id == 0 or abs(self.actor_id)>=2**63
                or type(self.turn_index) is not int or not 0 <= self.turn_index <= 1_000_000
                or any(x is not None for x in (self.cell_id,self.spell_id,self.target_cell))):
                raise ValueError('FIGHT_RESEARCH_TURN_INVALID')
        elif self.kind == 'ACTOR_CELL_OBSERVED':
            if (type(self.actor_id) is not int or self.actor_id==0 or abs(self.actor_id)>=2**63
                or type(self.cell_id) is not int or not 0<=self.cell_id<=100000
                or any(x is not None for x in (self.turn_index,self.spell_id,self.target_cell))):
                raise ValueError('FIGHT_RESEARCH_CELL_INVALID')
        elif self.kind == 'SPELL_CAST_OBSERVED':
            if (type(self.actor_id) is not int or self.actor_id==0 or abs(self.actor_id)>=2**63
                or type(self.spell_id) is not int or not 0<self.spell_id<10**9
                or type(self.target_cell) is not int or not 0<=self.target_cell<=100000
                or any(x is not None for x in (self.turn_index,self.cell_id))):
                raise ValueError('FIGHT_RESEARCH_SPELL_INVALID')

@dataclass(frozen=True, slots=True)
class FightResearchResult:
    status: str
    adapter_id: str
    protocol_build: str
    wire_name: str
    candidates: tuple[FightResearchDraft,...] = ()
    failure_code: str | None = None
    def __post_init__(self):
        if self.status not in {'CANDIDATES_ONLY','NO_SEMANTIC_MAPPING','QUARANTINED'}:
            raise ValueError('FIGHT_RESEARCH_STATUS_INVALID')
        if (self.status=='CANDIDATES_ONLY') != bool(self.candidates):
            raise ValueError('FIGHT_RESEARCH_CANDIDATE_STATUS_INVALID')
        if (not isinstance(self.candidates, tuple) or len(self.candidates)>32
            or any(not isinstance(d,FightResearchDraft) or
                   (d.evidence.protocol_build,d.evidence.adapter_id,d.evidence.wire_name)
                   != (self.protocol_build,self.adapter_id,self.wire_name) for d in self.candidates)):
            raise ValueError('FIGHT_RESEARCH_CANDIDATE_PROVENANCE_INVALID')
        if self.status=='QUARANTINED' and not self.failure_code:
            raise ValueError('FIGHT_RESEARCH_QUARANTINE_REASON_REQUIRED')
