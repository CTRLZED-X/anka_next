"""Kernel-facing pure mechanics contract; results never grant input authority."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Protocol, Any

Legality = Literal["LEGAL", "ILLEGAL", "INDETERMINATE"]


@dataclass(frozen=True, slots=True)
class MechanicsResult:
    status: Legality
    reason: str = ""
    value: Any = None

    def __post_init__(self):
        if self.status not in ("LEGAL", "ILLEGAL", "INDETERMINATE"):
            raise ValueError("INVALID_MECHANICS_STATUS")
        if type(self.reason) is not str or len(self.reason) > 512:
            raise ValueError("INVALID_MECHANICS_REASON")
        if self.status != "LEGAL" and not self.reason:
            raise ValueError("MECHANICS_REASON_REQUIRED")
