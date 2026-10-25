from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import StateId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class StateDefinition:
    state_id: StateId
    name_id: int
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.name_id < 0:
            raise ValueError("state name_id cannot be negative")
        if not self.name.strip():
            raise ValueError("state name must not be empty")
