from __future__ import annotations

from dataclasses import dataclass
import math

from anka_game_kernel.domain.ids import EffectId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class EffectDefinition:
    effect_id: EffectId
    description_id: int
    effect_power_rate: float
    name: str
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.description_id < 0:
            raise ValueError("effect description_id cannot be negative")
        if not math.isfinite(self.effect_power_rate):
            raise ValueError("effect_power_rate must be finite")
