"""Pure, deterministic fixture transition logic: no game IO and no clocks."""
from __future__ import annotations


class ExecutionTransitionRejected(ValueError):
    pass


def next_status(status: str | None, event: str) -> str:
    transitions = {
        (None, 'PREPARED'): 'PREPARED',
        ('PREPARED', 'DISPATCH_BOUNDARY_COMMITTED'): 'DISPATCH_UNCERTAIN',
        ('PREPARED', 'CANCELLED_BEFORE_DISPATCH'): 'CANCELLED',
        ('DISPATCH_UNCERTAIN', 'OUTCOME_ACCEPTED'): 'CONFIRMED',
        ('DISPATCH_UNCERTAIN', 'OUTCOME_REJECTED'): 'REJECTED',
        ('DISPATCH_UNCERTAIN', 'OUTCOME_INCONCLUSIVE'): 'DISPATCH_UNCERTAIN',
    }
    result = transitions.get((status, event))
    if result is None:
        raise ExecutionTransitionRejected('P18_ILLEGAL_TRANSITION')
    return result


def reason_for(status: str) -> str:
    return {
        'PREPARED': 'PREPARED_NO_DISPATCH',
        'DISPATCH_UNCERTAIN': 'UNCERTAIN_SEND_NO_AUTO_RETRY',
        'CONFIRMED': 'FIXTURE_OBSERVATION_ACCEPTED_NOT_LIVE_PROOF',
        'REJECTED': 'FIXTURE_OBSERVATION_REJECTED_NOT_LIVE_PROOF',
        'CANCELLED': 'CANCELLED_BEFORE_DISPATCH',
    }[status]
