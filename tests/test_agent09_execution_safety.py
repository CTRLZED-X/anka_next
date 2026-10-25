from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import sqlite3
import unittest
from unittest.mock import patch

from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger, DefinitiveExecutionLedgerError
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.drivers.windows_input import PointerTransaction
import anka_execution.service as execution_service_module
from anka_execution.service import DefinitiveExecutionService, ExecutionServiceRejected
from tests.test_m11_execution import (
    command, state, client, permit, evidence,
    StatePort, ClientPort, MechanicsPort, CoordinationPort,
)


class Agent09ExecutionSafetyCase(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def make_service(self, c, *, ledger=None, driver=None, arm=True):
        ledger = ledger or DefinitiveExecutionLedger(Path(self.temp.name) / f"{c.action_id}.sqlite3")
        driver = driver or FakePhysicalInputDriver("sent")
        service = DefinitiveExecutionService(
            run_id="run-m11",
            run_generation=2,
            ledger=ledger,
            arbiter=HostInputArbiter(),
            state_reader=StatePort(state(c)),
            client=ClientPort(client(c)),
            mechanics=MechanicsPort(MechanicsResult("LEGAL")),
            coordination=CoordinationPort(permit(c)),
            driver=driver,
            clock_ns=lambda: 50,
        )
        if arm:
            service.arm(authority_generation=9)
        return service, ledger, driver

    def test_set_cursor_exception_is_ambiguous_not_retryable_not_sent(self):
        class RaisingPointerApi:
            def __init__(self):
                self.events = []

            def set_cursor(self, x, y):
                self.events.append(("move-attempt", x, y))
                raise OSError("native call returned ambiguously")

            def left_down(self):
                self.events.append(("down",))
                return True

            def left_up(self):
                self.events.append(("up",))
                return True

        api = RaisingPointerApi()
        result = PointerTransaction(api).execute("action-agent09-pointer", 101, 202, lambda: True)
        self.assertEqual(result.delivery, "MAY_HAVE_SENT")
        self.assertEqual(result.physical_input_count, 1)
        self.assertEqual(result.detail, "SET_CURSOR_DELIVERY_AMBIGUOUS")
        self.assertEqual(api.events, [("move-attempt", 101, 202)])

    def test_send_started_ledger_failure_before_driver_never_becomes_retryable(self):
        c = command(9001)
        service, ledger, driver = self.make_service(c)
        original_mark_send_started = ledger.mark_send_started

        def commit_then_raise(action_id, attempt_id):
            original_mark_send_started(action_id, attempt_id)
            raise OSError("lost ledger response after durable commit")

        def fail_uncertain(*_args, **_kwargs):
            raise OSError("ledger unavailable")

        ledger.mark_send_started = commit_then_raise
        ledger.mark_uncertain = fail_uncertain

        result = service.submit(c)
        self.assertEqual(result.status, "UNCERTAIN")
        self.assertFalse(result.retry_eligible)
        self.assertTrue(result.reason.startswith("EXECUTION_LEDGER_UNAVAILABLE_AFTER_SEND_STARTED:"))
        self.assertEqual(driver.call_count, 0)
        self.assertEqual(ledger.get(c.action_id).status, "SEND_STARTED")
        self.assertFalse(service.armed)
        self.assertEqual(service.last_safety_fault, result.reason)

    def test_corrupted_terminal_projection_cannot_bypass_restart_fence(self):
        c = command(9002)
        ledger = DefinitiveExecutionLedger(Path(self.temp.name) / "projection-tamper.sqlite3")
        ledger.prepare(c, 2, 9)
        ledger.mark_send_started(c.action_id, "attempt-agent09")

        # Simulate a damaged/re-written projection that hides unresolved SEND_STARTED
        # while leaving the append-only event history unchanged.
        with sqlite3.connect(ledger.path) as con:
            con.execute(
                "UPDATE actions SET status='SETTLED_SUCCESS', send_state='SENT' WHERE action_id=?",
                (c.action_id,),
            )

        with self.assertRaisesRegex(ExecutionServiceRejected, "EXECUTION_LEDGER_BOOTSTRAP_INTEGRITY_FAILED"):
            self.make_service(c, ledger=ledger, arm=False)

    def test_arm_reaudits_ledger_after_service_construction(self):
        c = command(9003)
        ledger = DefinitiveExecutionLedger(Path(self.temp.name) / "arm-tamper.sqlite3")
        service, _, _ = self.make_service(c, ledger=ledger, arm=False)
        ledger.prepare(c, 2, 9)
        ledger.mark_send_started(c.action_id, "attempt-agent09-arm")
        with sqlite3.connect(ledger.path) as con:
            con.execute(
                "UPDATE actions SET status='SETTLED_SUCCESS', send_state='SENT' WHERE action_id=?",
                (c.action_id,),
            )

        with self.assertRaisesRegex(ExecutionServiceRejected, "EXECUTION_LEDGER_INTEGRITY_FAILED"):
            service.arm(authority_generation=9)
        self.assertFalse(service.armed)

    def test_uncorrelated_future_turn_cast_proof_cannot_settle_current_action(self):
        c = command(9004)
        service, ledger, _ = self.make_service(c)
        self.assertEqual(service.submit(c).status, "PENDING")

        later = evidence(
            c,
            9004,
            observed_turn_epoch=c.turn_epoch + 1,
            correlated_action_id=None,
        )
        result = service.reconcile(c.action_id, later)
        self.assertEqual(result.status, "PENDING")
        self.assertEqual(result.reason, "OUTCOME_TURN_SCOPE_MISMATCH")
        self.assertEqual(ledger.get(c.action_id).status, "PENDING")

    def test_exact_action_correlation_can_accept_delayed_future_turn_proof(self):
        c = command(9005)
        service, ledger, _ = self.make_service(c)
        self.assertEqual(service.submit(c).status, "PENDING")

        delayed = evidence(
            c,
            9005,
            observed_turn_epoch=c.turn_epoch + 1,
            correlated_action_id=c.action_id,
        )
        result = service.reconcile(c.action_id, delayed)
        self.assertEqual(result.status, "SETTLED_SUCCESS")
        self.assertEqual(ledger.get(c.action_id).status, "SETTLED_SUCCESS")

    def test_audit_detects_all_safety_critical_projection_tampering(self):
        mutations = (
            ("action_key", "e" * 64),
            ("send_state", "NOT_SENT"),
            ("attempt_id", "attempt-tampered"),
            ("evidence_json", "[]"),
            ("obligations_json", "[]"),
            ("reason", "TAMPERED_REASON"),
        )
        for offset, (field, value) in enumerate(mutations, 9010):
            with self.subTest(field=field):
                c = command(offset)
                ledger = DefinitiveExecutionLedger(Path(self.temp.name) / f"tamper-{field}.sqlite3")
                ledger.prepare(c, 2, 9)
                ledger.mark_send_started(c.action_id, f"attempt-{offset}")
                ledger.audit()
                with sqlite3.connect(ledger.path) as con:
                    con.execute(f"UPDATE actions SET {field}=? WHERE action_id=?", (value, c.action_id))
                with self.assertRaises(DefinitiveExecutionLedgerError):
                    ledger.audit()

    def test_late_uncertainty_preserves_partial_authoritative_outcome(self):
        c = command(9020)
        ledger = DefinitiveExecutionLedger(Path(self.temp.name) / "partial-uncertain.sqlite3")
        ledger.prepare(c, 2, 9)
        ledger.mark_send_started(c.action_id, "attempt-partial")
        partial = evidence(c, 9020, proofs=("SPELL_CAST_CONFIRMED",))
        ledger.apply_outcome(
            c.action_id,
            "CONFIRMED_UNSETTLED",
            partial,
            "PARTIAL_OUTCOME_PROOF",
            ("RESOURCE_DELTA_OR_TURN_PROGRESS",),
        )

        result = ledger.mark_uncertain(c.action_id, "LATE_DRIVER_AMBIGUITY")
        self.assertEqual(result.status, "CONFIRMED_UNSETTLED")
        self.assertEqual(result.send_state, "MAY_HAVE_SENT")
        self.assertEqual(result.unresolved_obligations, ("RESOURCE_DELTA_OR_TURN_PROGRESS",))
        ledger.audit()

    def test_concurrent_outcome_proofs_are_serialized_and_accumulate(self):
        c = command(9021)
        service, ledger, _ = self.make_service(c)
        self.assertEqual(service.submit(c).status, "PENDING")

        first_entered = Event()
        release_first = Event()
        second_entered = Event()
        real_correlate = execution_service_module.correlate
        calls = []

        def slow_correlate(*args, **kwargs):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(2))
            else:
                second_entered.set()
            return real_correlate(*args, **kwargs)

        results = []
        errors = []

        def settle(proof):
            try:
                results.append(service.reconcile(c.action_id, proof))
            except Exception as exc:
                errors.append(exc)

        proof_a = evidence(c, 9021, proofs=("SPELL_CAST_CONFIRMED",))
        proof_b = evidence(c, 9022, proofs=("RESOURCE_DELTA_OR_TURN_PROGRESS",))

        with patch.object(execution_service_module, "correlate", slow_correlate):
            t1 = Thread(target=settle, args=(proof_a,), name="agent09-settle-a")
            t2 = Thread(target=settle, args=(proof_b,), name="agent09-settle-b")
            t1.start()
            self.assertTrue(first_entered.wait(2))
            t2.start()
            self.assertFalse(second_entered.wait(0.1))
            release_first.set()
            t1.join(2)
            t2.join(2)

        self.assertFalse(t1.is_alive())
        self.assertFalse(t2.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(second_entered.is_set())
        self.assertEqual(ledger.get(c.action_id).status, "SETTLED_SUCCESS")
        self.assertEqual(ledger.get(c.action_id).unresolved_obligations, ())
        ledger.audit()


if __name__ == "__main__":
    unittest.main()
