from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RangeFailureReason(StrEnum):
    MIN_RANGE = "min_range"
    MAX_RANGE = "max_range"
    NOT_IN_LINE = "not_in_line"
    NOT_IN_DIAGONAL = "not_in_diagonal"
    NOT_IN_LINE_OR_DIAGONAL = "not_in_line_or_diagonal"


@dataclass(frozen=True, slots=True)
class RangeSpec:
    min_range: int
    max_range: int
    modifiable: bool = False
    cast_in_line: bool = False
    cast_in_diagonal: bool = False

    def __post_init__(self) -> None:
        if self.min_range < 0:
            raise ValueError("min_range must be >= 0")
        if self.max_range < self.min_range:
            raise ValueError("max_range must be >= min_range")
