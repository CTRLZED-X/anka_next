"""Stable structured error contract; free-form text is never the machine API."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Literal
import re

Severity = Literal["INFO","WARNING","ERROR","CRITICAL","SAFETY"]
ControlImpact = Literal["NONE","CAPABILITY_BLOCK","ACCOUNT_BLOCK","RUN_BLOCK","GLOBAL_BLOCK"]
PhysicalInputState = Literal["NOT_SENT","SEND_STARTED","SENT","MAY_HAVE_SENT","UNKNOWN"]
_CODE = re.compile(r"^[A-Z][A-Z0-9_]{2,95}$")


@dataclass(frozen=True, slots=True)
class FailureRecord:
    code: str
    owner_system: str
    boundary: str
    severity: Severity
    control_impact: ControlImpact
    scope: str
    physical_input_state: PhysicalInputState
    retry_eligible: bool
    evidence_ids: tuple[str, ...]
    human_message: str
    cause_code: str | None = None

    def __post_init__(self):
        if not _CODE.fullmatch(self.code) or (self.cause_code is not None and not _CODE.fullmatch(self.cause_code)):
            raise ValueError("INVALID_FAILURE_CODE")
        if not self.owner_system.startswith("anka_") or not self.boundary or not self.scope:
            raise ValueError("INVALID_FAILURE_OWNER_OR_SCOPE")
        if self.severity not in ("INFO","WARNING","ERROR","CRITICAL","SAFETY"):
            raise ValueError("INVALID_FAILURE_SEVERITY")
        if self.control_impact not in ("NONE","CAPABILITY_BLOCK","ACCOUNT_BLOCK","RUN_BLOCK","GLOBAL_BLOCK"):
            raise ValueError("INVALID_CONTROL_IMPACT")
        if self.physical_input_state not in ("NOT_SENT","SEND_STARTED","SENT","MAY_HAVE_SENT","UNKNOWN"):
            raise ValueError("INVALID_PHYSICAL_INPUT_STATE")
        if type(self.retry_eligible) is not bool or not 1 <= len(self.human_message) <= 1000:
            raise ValueError("INVALID_FAILURE_DETAIL")
        if self.physical_input_state in ("SEND_STARTED","SENT","MAY_HAVE_SENT") and self.retry_eligible:
            raise ValueError("BLIND_RETRY_FORBIDDEN")

    def to_dict(self) -> dict:
        d=asdict(self); d["evidence_ids"]=list(self.evidence_ids); return d
