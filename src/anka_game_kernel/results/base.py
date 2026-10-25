from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty


@dataclass(frozen=True, slots=True)
class MechanicResult:
    certainty: Certainty
    missing_inputs: tuple[str, ...] = ()
    explanation: str | None = None

    def __post_init__(self) -> None:
        if self.certainty is Certainty.DETERMINISTIC and self.missing_inputs:
            raise ValueError("deterministic results cannot have missing inputs")
