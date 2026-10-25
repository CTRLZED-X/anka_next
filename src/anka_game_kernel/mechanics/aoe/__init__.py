"""Generic deterministic area-of-effect mechanics."""

from anka_game_kernel.mechanics.aoe.model import AreaShape, AreaSpec
from anka_game_kernel.mechanics.aoe.service import AoEService
from anka_game_kernel.results.aoe import AoEResult

__all__ = ["AoEResult", "AoEService", "AreaShape", "AreaSpec"]
