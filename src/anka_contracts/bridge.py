"""Read-only P44 native coordinate-bridge evidence contracts.

These values are *not* actor/character identity, spell-slot verification, physical
input permission, canonical truth, or current-client acceptance.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any


class BridgeEvidenceReader(Protocol):
    def get_json(self, port: int, route: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class BridgeIdentityReport:
    status: str
    reason: str
    process_id: int | None = None
    process_created_100ns: int | None = None
    bridge_port: int | None = None
    map_id: int | None = None
    map_generation: int | None = None
    coordinate_generation: int | None = None
    window_process_matched: bool = False
    character_identity_verified: bool = False
    input_certified: bool = False


@dataclass(frozen=True, slots=True)
class CellProjection:
    cell_id: int
    client_x: int
    client_y: int
    inside_viewport: bool
    source_verified: bool
    projectable: bool


@dataclass(frozen=True, slots=True)
class BridgeMapReport:
    status: str
    reason: str
    map_id: int | None = None
    map_generation: int | None = None
    coordinate_generation: int | None = None
    client_size: tuple[int, int] | None = None
    cells: tuple[CellProjection, ...] = ()
    source_verified: bool = False
    live_certified: bool = False
    input_certified: bool = False
