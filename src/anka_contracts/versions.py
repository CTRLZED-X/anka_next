"""Independent version/build identities used across system boundaries."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import re

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+ -]{0,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _safe(value: str, code: str) -> None:
    if type(value) is not str or not _SAFE.fullmatch(value):
        raise ValueError(code)


@dataclass(frozen=True, slots=True)
class SchemaVersion:
    major: int
    minor: int = 0
    def __post_init__(self):
        if type(self.major) is not int or type(self.minor) is not int or self.major < 1 or self.minor < 0:
            raise ValueError("INVALID_SCHEMA_VERSION")


@dataclass(frozen=True, slots=True)
class RuntimeVersions:
    release_id: str
    source_tree_sha256: str
    observed_client_build: str | None
    protocol_adapter_release: str | None
    canonical_schema: SchemaVersion
    state_reducer_revision: str
    kernel_ruleset: str
    game_data_revision: str
    calibration_generation: str | None
    config_schema: SchemaVersion
    incident_schema: SchemaVersion

    def __post_init__(self):
        _safe(self.release_id, "INVALID_RELEASE_ID")
        if not _HEX64.fullmatch(self.source_tree_sha256):
            raise ValueError("INVALID_SOURCE_TREE_HASH")
        for value, code in (
            (self.observed_client_build, "INVALID_CLIENT_BUILD"),
            (self.protocol_adapter_release, "INVALID_ADAPTER_RELEASE"),
            (self.state_reducer_revision, "INVALID_REDUCER_REVISION"),
            (self.kernel_ruleset, "INVALID_KERNEL_RULESET"),
            (self.game_data_revision, "INVALID_GAME_DATA_REVISION"),
            (self.calibration_generation, "INVALID_CALIBRATION_GENERATION"),
        ):
            if value is not None:
                _safe(value, code)

    def to_dict(self) -> dict:
        return asdict(self)
