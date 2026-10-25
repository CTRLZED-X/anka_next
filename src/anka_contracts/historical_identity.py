"""P53 historical world-identity research contracts.

These objects prove only that a pinned *historical* Dofus 3.7.10.10 world
snapshot contained the configured character name on one captured flow.  They
are not current-client identity, CharacterEvidence, Canonical events, or input
authority.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from anka_contracts.canonical import EvidenceRef


@dataclass(frozen=True, slots=True)
class HistoricalIdentityScope:
    flow_digest: str
    generation: int
    protocol_build: str
    expected_character_name: str

    def __post_init__(self):
        if (type(self.flow_digest) is not str or len(self.flow_digest) != 64 or
                any(ch not in '0123456789abcdef' for ch in self.flow_digest)):
            raise ValueError('P53_FLOW_SCOPE_INVALID')
        if type(self.generation) is not int or self.generation < 0:
            raise ValueError('P53_GENERATION_SCOPE_INVALID')
        if type(self.protocol_build) is not str or not self.protocol_build:
            raise ValueError('P53_BUILD_SCOPE_INVALID')
        name=self.expected_character_name
        if (type(name) is not str or not 2 <= len(name.strip()) <= 40 or name != name.strip() or
                any(ord(ch) < 32 or ch in '/\\' for ch in name)):
            raise ValueError('P53_CHARACTER_SCOPE_INVALID')


@dataclass(frozen=True, slots=True)
class HistoricalIdentityObservation:
    evidence: EvidenceRef
    character_name: str
    actor_id: int
    cell_id: int
    map_id: int
    identity_source: str = field(default='JNJ_CHARACTER_NAME', init=False)
    authority: str = field(default='HISTORICAL_RESEARCH_ONLY', init=False)
    current_client_certified: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)

    def __post_init__(self):
        if not isinstance(self.evidence, EvidenceRef):
            raise ValueError('P53_IDENTITY_EVIDENCE_INVALID')
        if (type(self.character_name) is not str or not 2 <= len(self.character_name) <= 40 or
                self.character_name != self.character_name.strip()):
            raise ValueError('P53_IDENTITY_NAME_INVALID')
        if type(self.actor_id) is not int or self.actor_id == 0 or abs(self.actor_id) >= 2**63:
            raise ValueError('P53_IDENTITY_ACTOR_INVALID')
        if type(self.cell_id) is not int or not 0 <= self.cell_id <= 10_000_000:
            raise ValueError('P53_IDENTITY_CELL_INVALID')
        if type(self.map_id) is not int or not 0 < self.map_id < 2**63:
            raise ValueError('P53_IDENTITY_MAP_INVALID')


@dataclass(frozen=True, slots=True)
class HistoricalIdentityResult:
    status: str
    adapter_id: str
    protocol_build: str
    wire_name: str
    observations: tuple[HistoricalIdentityObservation, ...] = ()
    failure_code: str | None = None
    current_client_certified: bool = field(default=False, init=False)
    canonical_commits: int = field(default=0, init=False)
    physical_input_sent: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self):
        allowed={'OBSERVATIONS_ONLY','NO_MATCH','CAPABILITY_UNDECLARED','NO_MAPPING',
                 'BUILD_MISMATCH','SCOPE_UNVERIFIED','QUARANTINED'}
        if self.status not in allowed:
            raise ValueError('P53_IDENTITY_RESULT_STATUS_INVALID')
        if (self.status == 'OBSERVATIONS_ONLY') != bool(self.observations):
            raise ValueError('P53_IDENTITY_RESULT_OBSERVATIONS_INVALID')
        if len(self.observations) > 1:
            raise ValueError('P53_IDENTITY_RESULT_MULTIPLE_OBSERVATIONS')
        for obs in self.observations:
            if ((obs.evidence.adapter_id,obs.evidence.protocol_build,obs.evidence.wire_name) !=
                    (self.adapter_id,self.protocol_build,self.wire_name)):
                raise ValueError('P53_IDENTITY_RESULT_PROVENANCE_INVALID')
        if self.status == 'QUARANTINED' and not self.failure_code:
            raise ValueError('P53_IDENTITY_QUARANTINE_CODE_MISSING')
