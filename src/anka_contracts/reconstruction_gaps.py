"""P34 bounded, non-authoritative reconstruction-coverage contracts.

Coverage is about what was *observed*, not what the server did or what ANKA
may execute. No contract in this module can authorize input or Canonical writes.
"""
from __future__ import annotations
from dataclasses import dataclass, field

_KNOWN={'FIGHT_START_OBSERVED','FIGHT_END_OBSERVED','TURN_START_OBSERVED',
        'TURN_END_OBSERVED','ACTOR_CELL_OBSERVED','SPELL_CAST_OBSERVED',
        'ACTOR_RESOURCE_ABSOLUTE','ACTOR_HP_ABSOLUTE','ACTOR_COOLDOWN_SNAPSHOT'}
_STATES={'GAPS_FOUND_RESEARCH_ONLY','INCOMPLETE_RESEARCH_ONLY','BLOCKED_RESEARCH_ONLY'}

@dataclass(frozen=True,slots=True)
class CoverageEntry:
    kind: str
    observations: int
    reducer_supported: bool
    caveats: tuple[str,...]

    def __post_init__(self):
        if (self.kind not in _KNOWN or type(self.observations) is not int or self.observations < 0
            or not isinstance(self.reducer_supported,bool) or not isinstance(self.caveats,tuple)
            or any(not isinstance(code,str) or not code.isascii() or len(code)>100 for code in self.caveats)):
            raise ValueError('P34_COVERAGE_ENTRY_INVALID')

@dataclass(frozen=True,slots=True)
class ReconstructionCoverageReport:
    status: str
    reason_codes: tuple[str,...]
    observations: int
    projected_events: int
    spell_cast_observations: int
    cell_observations: int
    complete_actor_fields: int
    expected_actor_fields: int
    coverage: tuple[CoverageEntry,...]
    first_blocked_index: int|None = None
    final_phase: str|None = None
    authority: str = field(default='RESEARCH_ONLY_NOT_CANONICAL',init=False)
    committed_events: int = field(default=0,init=False)
    actionable: bool = field(default=False,init=False)
    physical_input_sent: bool = field(default=False,init=False)
    live_state_mutated: bool = field(default=False,init=False)

    def __post_init__(self):
        nums=(self.observations,self.projected_events,self.spell_cast_observations,
              self.cell_observations,self.complete_actor_fields,self.expected_actor_fields)
        if (self.status not in _STATES or any(type(x) is not int or x < 0 for x in nums)
            or self.projected_events>self.observations+64
            or self.complete_actor_fields>self.expected_actor_fields
            or self.spell_cast_observations>self.observations
            or self.cell_observations>self.observations
            or type(self.reason_codes) is not tuple
            or any(not isinstance(v,str) or not v.isascii() or len(v)>120 for v in self.reason_codes)
            or type(self.coverage) is not tuple
            or any(not isinstance(v,CoverageEntry) for v in self.coverage)
            or (self.first_blocked_index is not None and
                (type(self.first_blocked_index) is not int or self.first_blocked_index<0 or self.first_blocked_index>=max(1,self.observations)))
            or (self.status!='BLOCKED_RESEARCH_ONLY' and self.first_blocked_index is not None)
            or (self.status=='BLOCKED_RESEARCH_ONLY' and not self.reason_codes)):
            raise ValueError('P34_COVERAGE_REPORT_INVALID')

    def to_dict(self)->dict:
        """No raw packet, account names, actor IDs, spell IDs or game values."""
        return dict(status=self.status,reason_codes=list(self.reason_codes),
            observations=self.observations,projected_events=self.projected_events,
            spell_cast_observations=self.spell_cast_observations,
            cell_observations=self.cell_observations,
            complete_actor_fields=self.complete_actor_fields,
            expected_actor_fields=self.expected_actor_fields,
            coverage=[dict(kind=v.kind,observations=v.observations,
                reducer_supported=v.reducer_supported,caveats=list(v.caveats)) for v in self.coverage],
            first_blocked_index=self.first_blocked_index,final_phase=self.final_phase,
            authority=self.authority,committed_events=0,actionable=False,
            live_state_mutated=False,physical_input_sent=False,current_build_certified=False,
            cross_account_server_order_certified=False,roster_is_synthetic_fixture=True)
