"""P19 *offline-only* input-driver simulation contracts. Not an IO permission API."""
from __future__ import annotations
from dataclasses import dataclass


def _token(value: object) -> bool:
    return type(value) is str and 1 <= len(value) <= 120 and value.isascii() and all(
        c.isalnum() or c in '_.:-' for c in value)


@dataclass(frozen=True, slots=True)
class OfflineWindowObservation:
    account_id: str
    client_id: str
    window_generation: int
    character_verified: bool
    foreground_verified: bool
    calibration_verified: bool
    synthetic_only: bool = True
    physical_input_permitted: bool = False

    def __post_init__(self):
        if (not _token(self.account_id) or not _token(self.client_id)
            or type(self.window_generation) is not int or self.window_generation < 1
            or any(type(v) is not bool for v in (self.character_verified, self.foreground_verified,
                    self.calibration_verified))):
            raise ValueError('P19_WINDOW_OBSERVATION_INVALID')
        if self.synthetic_only is not True or self.physical_input_permitted is not False:
            raise ValueError('P19_AUTHORITY_FORGERY')

    def to_dict(self) -> dict:
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class OfflineDriverReceipt:
    action_id: str
    result: str
    fake_attempt_count: int
    physical_input_sent: bool = False
    synthetic_only: bool = True
    actionable: bool = False

    def __post_init__(self):
        if (not _token(self.action_id) or self.result not in ('SIMULATED_INPUT', 'NO_INPUT')
            or type(self.fake_attempt_count) is not int or self.fake_attempt_count not in (0, 1)):
            raise ValueError('P19_DRIVER_RECEIPT_INVALID')
        if (self.physical_input_sent is not False or self.synthetic_only is not True
                or self.actionable is not False):
            raise ValueError('P19_AUTHORITY_FORGERY')

    def to_dict(self):
        return {f: getattr(self, f) for f in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class OfflineDispatchReport:
    action_id: str
    action_status: str
    boundary: str
    reason: str
    fake_attempt_count: int
    evidence_ids: tuple[str, ...] = ()
    synthetic_only: bool = True
    actionable: bool = False
    physical_input_sent: bool = False

    def __post_init__(self):
        if (not _token(self.action_id) or self.action_status not in
                ('CANCELLED', 'DISPATCH_UNCERTAIN', 'CONFIRMED', 'REJECTED')
                or self.boundary not in ('PRE_DISPATCH', 'POST_DISPATCH', 'SETTLEMENT')
                or not _token(self.reason)
                or type(self.fake_attempt_count) is not int or self.fake_attempt_count not in (0, 1)
                or type(self.evidence_ids) is not tuple
                or any(not _token(x) for x in self.evidence_ids)):
            raise ValueError('P19_DISPATCH_REPORT_INVALID')
        if self.synthetic_only is not True or self.actionable is not False or self.physical_input_sent is not False:
            raise ValueError('P19_AUTHORITY_FORGERY')

    def to_dict(self):
        return {f: (list(getattr(self, f)) if f == 'evidence_ids' else getattr(self, f))
                for f in self.__dataclass_fields__}
