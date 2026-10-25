"""Stable evidence/proof vocabulary.  Observation is not authority."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal
import re

EvidenceClass = Literal[
    "AUTHORITY_COMMITTED", "OBSERVED_EXTERNAL", "DERIVED", "HEURISTIC",
    "UNKNOWN", "STALE", "CONFLICTING", "MISSING",
]
EVIDENCE_CLASSES = frozenset({
    "AUTHORITY_COMMITTED", "OBSERVED_EXTERNAL", "DERIVED", "HEURISTIC",
    "UNKNOWN", "STALE", "CONFLICTING", "MISSING",
})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class EvidencePointer:
    evidence_id: str
    classification: EvidenceClass
    source_system: str
    source_ref: str
    artifact_sha256: str | None = None
    scope: str | None = None

    def __post_init__(self):
        if type(self.evidence_id) is not str or not self.evidence_id.startswith("evidence-") or len(self.evidence_id) > 128:
            raise ValueError("INVALID_EVIDENCE_ID")
        if self.classification not in EVIDENCE_CLASSES:
            raise ValueError("INVALID_EVIDENCE_CLASS")
        if type(self.source_system) is not str or not self.source_system.startswith("anka_") or len(self.source_system) > 64:
            raise ValueError("INVALID_EVIDENCE_SOURCE")
        if type(self.source_ref) is not str or not 1 <= len(self.source_ref) <= 256:
            raise ValueError("INVALID_EVIDENCE_REF")
        if self.artifact_sha256 is not None and not _HEX64.fullmatch(self.artifact_sha256):
            raise ValueError("INVALID_EVIDENCE_HASH")
        if self.scope is not None and not 1 <= len(self.scope) <= 256:
            raise ValueError("INVALID_EVIDENCE_SCOPE")

    @property
    def can_authorize(self) -> bool:
        return self.classification == "AUTHORITY_COMMITTED"

    def to_dict(self) -> dict:
        return asdict(self)
