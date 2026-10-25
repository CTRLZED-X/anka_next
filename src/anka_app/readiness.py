"""Evidence-based live-readiness report; purely descriptive and fail closed.

There is deliberately no grant(), promote(), or input-enable pathway here. A
successful synthetic test never certifies a real Windows/client capability.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LiveReadiness:
    blockers: tuple[str, ...]
    current_build_certified: bool = False
    physical_input_enabled: bool = False
    live_ready: bool = False

    def to_dict(self) -> dict:
        return {'status': 'LIVE_BLOCKED', 'live_ready': False,
                'physical_input_enabled': False, 'current_build_certified': False,
                'blockers': list(self.blockers),
                'basis': 'DEFINITIVE_M12_OFFLINE_EVIDENCE_ONLY_Q10_TO_Q13_UNACCEPTED'}


def assess_live_readiness() -> LiveReadiness:
    """Every blocker is an outstanding requirement of the current source.

    No caller-provided booleans or JSON setting can mark an unimplemented
    runtime as ready. Update this list only after actual integration/evidence.
    """
    return LiveReadiness((
        'WINDOW_IDENTITY_AND_CALIBRATION_HOST_UNVERIFIED',
        'WINDOW_NETWORK_ACCOUNT_FLOW_OWNERSHIP_UNVERIFIED',
        'CURRENT_CLIENT_SEMANTIC_ADAPTER_UNCERTIFIED',
        'CURRENT_BUILD_CANONICAL_ADMISSION_NOT_ACCEPTED',
        'CURRENT_CLIENT_AUTHORITATIVE_FIGHT_STATE_NOT_ACCEPTED',
        'CURRENT_CLIENT_DECISION_EXECUTION_SCOPE_NOT_ACCEPTED',
        'WINDOWS_PHYSICAL_INPUT_SCOPE_NOT_ACCEPTED',
        'CURRENT_CLIENT_SERVER_OUTCOME_CONFIRMATION_NOT_ACCEPTED',
        'REAL_CRA_ENU_END_TO_END_ACCEPTANCE_NOT_COMPLETED',
    ))
