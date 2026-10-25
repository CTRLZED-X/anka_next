"""P19 offline fake-driver composition with durable uncertainty before an attempt.

There is deliberately no injected arbitrary input-driver Protocol here. Only the
exact OfflineFakeInputDriver is accepted to prevent an accidental live adapter.
"""
from __future__ import annotations
from anka_contracts.execution_flow import OfflineActionIntent, OfflineOutcomeEvidence
from anka_contracts.execution_simulation import OfflineWindowObservation, OfflineDispatchReport
from anka_execution.fake_input import OfflineFakeInputDriver, OfflineWindowFeed, OfflineDriverFailure
from anka_execution.ledger import OfflineExecutionLedger, ExecutionLedgerRejected


class OfflineDispatchRejected(ValueError):
    pass


def _preflight(intent: OfflineActionIntent, snapshot: OfflineWindowObservation) -> str | None:
    if intent.account_id != snapshot.account_id or intent.client_id != snapshot.client_id:
        return 'P19_WINDOW_ACCOUNT_MISMATCH'
    if intent.window_generation != snapshot.window_generation:
        return 'P19_WINDOW_GENERATION_CHANGED'
    if not snapshot.character_verified:
        return 'P19_CHARACTER_NOT_VERIFIED'
    if not snapshot.foreground_verified:
        return 'P19_WINDOW_FOCUS_NOT_VERIFIED'
    if not snapshot.calibration_verified:
        return 'P19_CALIBRATION_NOT_VERIFIED'
    return None


class OfflineDispatchCoordinator:
    """P19 fake-only ordering: PREPARE -> guard -> durable boundary -> guard -> fake attempt.

    In a future live executor, an actual focus check would be needed at the real
    input point, not only at a prior snapshot. This class does not grant authority.
    """
    def __init__(self, ledger: OfflineExecutionLedger, driver: OfflineFakeInputDriver,
                 windows: OfflineWindowFeed):
        if type(ledger) is not OfflineExecutionLedger or ledger.read_only:
            raise OfflineDispatchRejected('P19_WRITABLE_LEDGER_REQUIRED')
        if type(driver) is not OfflineFakeInputDriver or type(windows) is not OfflineWindowFeed:
            raise OfflineDispatchRejected('P19_FAKE_ONLY_RUNTIME')
        self.ledger = ledger
        self.driver = driver
        self.windows = windows

    def run(self, intent: OfflineActionIntent, *, evidence: OfflineOutcomeEvidence | None = None,
            fault_point: str | None = None) -> OfflineDispatchReport:
        if type(intent) is not OfflineActionIntent:
            raise OfflineDispatchRejected('P19_INTENT_REQUIRED')
        if evidence is not None and type(evidence) is not OfflineOutcomeEvidence:
            raise OfflineDispatchRejected('P19_OFFLINE_EVIDENCE_REQUIRED')
        if fault_point not in (None, 'after_prepared', 'after_boundary', 'after_fake_attempt'):
            raise OfflineDispatchRejected('P19_UNKNOWN_FAULT_POINT')
        # A durable prepare must precede all attempts, even fixture-only attempts.
        self.ledger.prepare(intent)
        if fault_point == 'after_prepared':
            raise OfflineDriverFailure('P19_INJECTED_CRASH_AFTER_PREPARE')
        first = self.windows.read()
        error = _preflight(intent, first)
        if error is not None:
            audit = self.ledger.cancel_before_dispatch(intent.action_id)
            return OfflineDispatchReport(intent.action_id,audit.status,'PRE_DISPATCH',error,0)
        # Critical persistent point. Any crash after this MUST NOT trigger retry.
        try:
            self.ledger.mark_dispatch_boundary(intent.action_id)
        except ExecutionLedgerRejected as exc:
            if str(exc) != 'P18_GLOBAL_DISPATCH_BUSY':
                raise
            # The second actor never reached the dispatch boundary; release its
            # PREPARED slot. The previously uncertain action remains untouched.
            audit = self.ledger.cancel_before_dispatch(intent.action_id)
            return OfflineDispatchReport(intent.action_id,audit.status,'PRE_DISPATCH',
                                         'P19_GLOBAL_DISPATCH_BUSY',0)
        if fault_point == 'after_boundary':
            raise OfflineDriverFailure('P19_INJECTED_CRASH_AFTER_BOUNDARY')
        second = self.windows.read()
        error = _preflight(intent, second)
        if error is not None:
            return OfflineDispatchReport(intent.action_id,'DISPATCH_UNCERTAIN','POST_DISPATCH',error,0)
        try:
            receipt = self.driver.attempt(intent)
        except OfflineDriverFailure as exc:
            return OfflineDispatchReport(intent.action_id,'DISPATCH_UNCERTAIN',
                                         'POST_DISPATCH',str(exc),0)
        if fault_point == 'after_fake_attempt':
            raise OfflineDriverFailure('P19_INJECTED_CRASH_AFTER_FAKE_ATTEMPT')
        # A fake driver result alone is NOT an observed outcome.
        if receipt.result == 'NO_INPUT':
            return OfflineDispatchReport(intent.action_id,'DISPATCH_UNCERTAIN','POST_DISPATCH',
                                         'P19_FAKE_NO_INPUT_NOT_PROOF',0)
        if evidence is None:
            return OfflineDispatchReport(intent.action_id,'DISPATCH_UNCERTAIN','POST_DISPATCH',
                                         'P19_NO_INDEPENDENT_OUTCOME_EVIDENCE',1)
        # This call applies all P18 exact-scope and freshness checks atomically.
        # On error, P18 retains DISPATCH_UNCERTAIN; caller must not retry.
        audit = self.ledger.record_outcome(evidence)
        return OfflineDispatchReport(intent.action_id,audit.status,'SETTLEMENT',
                                     'P19_FIXTURE_OUTCOME_ONLY',1,audit.evidence_ids)
