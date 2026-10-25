"""P19 deterministic test doubles; this module intentionally cannot send OS input."""
from __future__ import annotations
from anka_contracts.execution_flow import OfflineActionIntent
from anka_contracts.execution_simulation import OfflineWindowObservation, OfflineDriverReceipt


class OfflineDriverFailure(RuntimeError):
    pass


class OfflineWindowFeed:
    """Returns scripted read-only snapshots; no Windows APIs are used."""
    def __init__(self, *observations: OfflineWindowObservation):
        if not observations or any(type(x) is not OfflineWindowObservation for x in observations):
            raise ValueError('P19_WINDOW_FIXTURES_REQUIRED')
        self._observations = observations
        self.read_count = 0

    def read(self) -> OfflineWindowObservation:
        if self.read_count >= len(self._observations):
            raise OfflineDriverFailure('P19_WINDOW_REATTESTATION_MISSING')
        index = self.read_count
        self.read_count += 1
        return self._observations[index]


class OfflineFakeInputDriver:
    """Accepts *only* offline intent objects. NEVER imports or uses Windows inputs.

    A SIMULATED_INPUT means the fake driver was called, not that anything physical
    occurred. The separate Ledger requires separately supplied synthetic evidence.
    """
    CASES = frozenset(('simulated-input', 'no-input', 'raise-before', 'raise-after'))

    def __init__(self, scenario: str = 'simulated-input'):
        if scenario not in self.CASES: raise ValueError('P19_FAKE_DRIVER_CASE_UNKNOWN')
        self.scenario = scenario
        self.attempted_action_ids: set[str] = set()
        self.attempt_count = 0

    def attempt(self, intent: OfflineActionIntent) -> OfflineDriverReceipt:
        if type(intent) is not OfflineActionIntent:
            raise OfflineDriverFailure('P19_FAKE_DRIVER_INTENT_INVALID')
        if intent.action_id in self.attempted_action_ids:
            raise OfflineDriverFailure('P19_FAKE_DRIVER_DUPLICATE_ATTEMPT')
        self.attempted_action_ids.add(intent.action_id)
        self.attempt_count += 1
        if self.scenario == 'raise-before':
            raise OfflineDriverFailure('P19_FAKE_DRIVER_RAISED_BEFORE_ATTEMPT')
        if self.scenario == 'raise-after':
            raise OfflineDriverFailure('P19_FAKE_DRIVER_RAISED_AFTER_POSSIBLE_ATTEMPT')
        return OfflineDriverReceipt(intent.action_id,
            'NO_INPUT' if self.scenario == 'no-input' else 'SIMULATED_INPUT',
            0 if self.scenario == 'no-input' else 1)
