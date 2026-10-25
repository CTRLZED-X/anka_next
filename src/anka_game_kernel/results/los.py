from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class LineOfSightResult(MechanicResult):
    visible: bool | None = None
    trace: tuple[CellId, ...] = ()
    static_blocker: CellId | None = None
    occupied_blocker: CellId | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        visible: bool,
        trace: tuple[CellId, ...],
        static_blocker: CellId | None = None,
        occupied_blocker: CellId | None = None,
        explanation: str | None = None,
    ) -> "LineOfSightResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            visible=visible,
            trace=trace,
            static_blocker=static_blocker,
            occupied_blocker=occupied_blocker,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        trace: tuple[CellId, ...],
        missing_input: str,
        explanation: str | None = None,
    ) -> "LineOfSightResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            visible=None,
            trace=trace,
            explanation=(
                explanation
                or "LoS trace is supported, but required static map data is missing."
            ),
        )

    @classmethod
    def unsupported(cls, *, explanation: str) -> "LineOfSightResult":
        return cls(
            certainty=Certainty.UNSUPPORTED,
            visible=None,
            trace=(),
            explanation=explanation,
        )
