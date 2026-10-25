from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AreaShape(StrEnum):
    POINT = "point"
    LOZENGE = "lozenge"
    CROSS = "cross"
    DIAGONAL = "diagonal"
    FORK = "fork"
    CONE = "cone"
    LINE = "line"
    GLOBAL = "global"
    OUTSIDE_LOZENGE = "outside_lozenge"
    SQUARE = "square"


@dataclass(frozen=True, slots=True)
class AreaSpec:
    shape: AreaShape
    min_radius: int = 0
    radius: int = 0

    def __post_init__(self) -> None:
        if self.min_radius < 0:
            raise ValueError("min_radius must be >= 0")
        if self.radius < self.min_radius:
            raise ValueError("radius must be >= min_radius")
        if self.shape is AreaShape.POINT and (self.min_radius != 0 or self.radius != 0):
            raise ValueError("POINT area must have min_radius=0 and radius=0")
