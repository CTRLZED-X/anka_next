from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RelocationFailureReason(StrEnum):
    DESTINATION_NOT_WALKABLE = "destination_not_walkable"
    DESTINATION_NON_WALKABLE_DURING_FIGHT = "destination_non_walkable_during_fight"
    DESTINATION_OCCUPIED = "destination_occupied"


@dataclass(frozen=True, slots=True)
class TeleportSpec:
    require_walkable: bool = True
    require_fight_walkable: bool = True
    require_unoccupied: bool = True
