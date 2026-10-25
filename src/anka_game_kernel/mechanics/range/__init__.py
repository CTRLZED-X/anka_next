"""Generic deterministic spell-range mechanics."""

from anka_game_kernel.mechanics.range.model import RangeFailureReason, RangeSpec
from anka_game_kernel.mechanics.range.service import RangeService
from anka_game_kernel.results.range import RangeResult

__all__ = ["RangeFailureReason", "RangeResult", "RangeService", "RangeSpec"]
