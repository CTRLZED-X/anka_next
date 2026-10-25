from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SourceKind(StrEnum):
    USER_SUPPLIED_STATIC = "user_supplied_static"
    PRIMARY_EXTRACTION = "primary_extraction"
    SECONDARY_EXTRACTION = "secondary_extraction"
    VERIFIED_MANUAL = "verified_manual"
    HISTORICAL_REFERENCE = "historical_reference"
    INFERENCE = "inference"


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    SOURCE_VALIDATED = "source_validated"
    CROSS_CHECKED = "cross_checked"
    MANUALLY_VERIFIED = "manually_verified"


@dataclass(frozen=True, slots=True)
class Provenance:
    source_kind: SourceKind
    source_name: str
    source_version: str | None
    source_file: str | None
    source_record_id: str | None
    game_version: str | None
    verification_status: VerificationStatus
    source_hash: str | None = None
    importer_version: str | None = None
    normalizer_version: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        if not self.source_name.strip():
            raise ValueError("source_name must not be empty")
