from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.certainty import Certainty
from anka_game_kernel.domain.ids import CellId
from anka_game_kernel.mechanics.relocation.model import RelocationFailureReason
from anka_game_kernel.results.base import MechanicResult


@dataclass(frozen=True, slots=True)
class TeleportResult(MechanicResult):
    legal: bool | None = None
    source_cell: CellId | None = None
    destination_cell: CellId | None = None
    failure: RelocationFailureReason | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        legal: bool,
        source_cell: CellId,
        destination_cell: CellId,
        failure: RelocationFailureReason | None = None,
        explanation: str | None = None,
    ) -> "TeleportResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=legal,
            source_cell=source_cell,
            destination_cell=destination_cell,
            failure=failure,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        source_cell: CellId | None,
        destination_cell: CellId,
        explanation: str,
    ) -> "TeleportResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            legal=None,
            source_cell=source_cell,
            destination_cell=destination_cell,
            explanation=explanation,
        )


@dataclass(frozen=True, slots=True)
class SwapResult(MechanicResult):
    legal: bool | None = None
    first_destination: CellId | None = None
    second_destination: CellId | None = None

    @classmethod
    def deterministic(
        cls,
        *,
        first_destination: CellId,
        second_destination: CellId,
        explanation: str,
    ) -> "SwapResult":
        return cls(
            certainty=Certainty.DETERMINISTIC,
            legal=True,
            first_destination=first_destination,
            second_destination=second_destination,
            explanation=explanation,
        )

    @classmethod
    def incomplete(
        cls,
        *,
        missing_input: str,
        explanation: str,
    ) -> "SwapResult":
        return cls(
            certainty=Certainty.DETERMINISTIC_IF_CONTEXT_COMPLETE,
            missing_inputs=(missing_input,),
            legal=None,
            explanation=explanation,
        )
