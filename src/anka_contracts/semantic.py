"""Protocol-to-Canonical immutable transfer contract."""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.canonical import CanonicalDraft

@dataclass(frozen=True,slots=True)
class SemanticResult:
    status: str
    adapter_id: str
    protocol_build: str
    wire_name: str
    candidates: tuple[CanonicalDraft,...] = ()
    failure_code: str|None = None
    def __post_init__(self):
        if self.status not in ('CANDIDATES_ONLY','NO_SEMANTIC_MAPPING','QUARANTINED','BUILD_MISMATCH','CONTEXT_MISSING'):
            raise ValueError('SEMANTIC_STATUS_INVALID')
        if (self.status=='CANDIDATES_ONLY') != bool(self.candidates):
            raise ValueError('SEMANTIC_CANDIDATE_STATUS_INCONSISTENT')
        if self.status=='QUARANTINED' and not self.failure_code:
            raise ValueError('SEMANTIC_QUARANTINE_REQUIRES_REASON')
