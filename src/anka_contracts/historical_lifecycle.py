"""Research-only fight lifecycle observations recovered from R5.198.

These are never Canonical events or evidence of a verified game-client identity.
They intentionally preserve unknown round/turn index rather than invent defaults.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from anka_contracts.canonical import EvidenceRef

_EVENT_TYPES = frozenset({'ROUND_OBSERVED', 'TURN_OWNER_OBSERVED',
                          'TURN_END_OBSERVED', 'FIGHT_READY_OBSERVED'})

@dataclass(frozen=True, slots=True)
class LegacyFightScope:
    """Caller-supplied offline scope; not an identity-attestation authority."""
    fight_id: int
    flow_digest: str
    generation: int
    protocol_build: str
    def __post_init__(self):
        if type(self.fight_id) is not int or not 0 < self.fight_id < 2**63:
            raise ValueError('P45_FIGHT_SCOPE_INVALID')
        if (type(self.flow_digest) is not str or len(self.flow_digest) != 64 or
            any(ch not in '0123456789abcdef' for ch in self.flow_digest)):
            raise ValueError('P45_FLOW_SCOPE_INVALID')
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError('P45_GENERATION_SCOPE_INVALID')
        if type(self.protocol_build) is not str or not self.protocol_build:
            raise ValueError('P45_BUILD_SCOPE_INVALID')

@dataclass(frozen=True, slots=True)
class LegacyFightObservation:
    kind: str
    evidence: EvidenceRef
    fight_id: int
    actor_id: int | None = None
    round_number: int | None = None
    wire_turn_index: int | None = None
    ready: bool | None = None
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)
    def __post_init__(self):
        if self.kind not in _EVENT_TYPES or not isinstance(self.evidence, EvidenceRef):
            raise ValueError('P45_OBSERVATION_KIND_OR_EVIDENCE_INVALID')
        if type(self.fight_id) is not int or not 0 < self.fight_id < 2**63:
            raise ValueError('P45_FIGHT_ID_INVALID')
        if self.actor_id is not None and (type(self.actor_id) is not int or self.actor_id == 0 or abs(self.actor_id)>=2**63):
            raise ValueError('P45_ACTOR_ID_INVALID')
        if self.round_number is not None and (type(self.round_number) is not int or not 0 < self.round_number <= 1_000_000):
            raise ValueError('P45_ROUND_INVALID')
        if self.wire_turn_index is not None and (type(self.wire_turn_index) is not int or not 0 <= self.wire_turn_index <= 100_000):
            raise ValueError('P45_TURN_INDEX_INVALID')
        if self.ready is not None and type(self.ready) is not bool:
            raise ValueError('P45_READY_INVALID')
        if self.kind == 'ROUND_OBSERVED':
            if self.round_number is None or any(x is not None for x in (self.actor_id, self.wire_turn_index,self.ready)):
                raise ValueError('P45_ROUND_SHAPE_INVALID')
        elif self.kind == 'TURN_OWNER_OBSERVED':
            if self.actor_id is None or self.ready is not None:
                raise ValueError('P45_OWNER_SHAPE_INVALID')
        elif self.kind == 'TURN_END_OBSERVED':
            if self.actor_id is None or any(x is not None for x in (self.ready,self.round_number,self.wire_turn_index)):
                raise ValueError('P45_END_SHAPE_INVALID')
        elif self.kind == 'FIGHT_READY_OBSERVED':
            if self.actor_id is None or self.ready is None or any(x is not None for x in (self.round_number,self.wire_turn_index)):
                raise ValueError('P45_READY_SHAPE_INVALID')

@dataclass(frozen=True, slots=True)
class LegacyFightResult:
    status: str
    adapter_id: str
    protocol_build: str
    wire_name: str
    observations: tuple[LegacyFightObservation,...] = ()
    failure_code: str | None = None
    canonical_commits: int = field(default=0,init=False)
    physical_input_sent: bool = field(default=False,init=False)
    def __post_init__(self):
        if self.status not in ('OBSERVATIONS_ONLY','NO_MAPPING','QUARANTINED','BUILD_MISMATCH','SCOPE_UNVERIFIED'):
            raise ValueError('P45_RESULT_STATUS_INVALID')
        if (self.status == 'OBSERVATIONS_ONLY') != bool(self.observations):
            raise ValueError('P45_RESULT_OBSERVATIONS_INVALID')
        if len(self.observations)>4 or any(
            (x.evidence.adapter_id,x.evidence.protocol_build,x.evidence.wire_name) !=
            (self.adapter_id,self.protocol_build,self.wire_name) for x in self.observations):
            raise ValueError('P45_RESULT_PROVENANCE_INVALID')
        if self.status=='QUARANTINED' and not self.failure_code:
            raise ValueError('P45_QUARANTINE_CODE_MISSING')
