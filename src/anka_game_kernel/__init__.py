"""ANKA Game Kernel public package."""

from anka_game_kernel.api.kernel import GameKernel
from anka_game_kernel.config import ExternalGameDataConfig
from anka_game_kernel.errors import ExternalGameDataError
from anka_game_kernel.domain.live_requirements import (
    LiveObservationRequirement,
    LiveRequirementKind,
)
from anka_game_kernel.knowledge.spell_mechanics import load_bundled_spell_mechanics_pack

__version__ = "0.1.0a59"

__all__ = [
    "GameKernel",
    "ExternalGameDataConfig",
    "ExternalGameDataError",
    "LiveObservationRequirement",
    "LiveRequirementKind",
    "load_bundled_spell_mechanics_pack",
    "__version__",
]
