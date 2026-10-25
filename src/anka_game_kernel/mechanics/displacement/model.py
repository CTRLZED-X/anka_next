from __future__ import annotations

from enum import StrEnum


class DisplacementBlockReason(StrEnum):
    STATIC_NOT_WALKABLE = "static_not_walkable"
    NON_WALKABLE_DURING_FIGHT = "non_walkable_during_fight"
    OCCUPIED = "occupied"
    MAP_BOUNDARY = "map_boundary"
