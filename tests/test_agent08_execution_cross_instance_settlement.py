"""Independent Chat 08 regression for cross-instance settlement races.

A durable execution ledger must not lose cumulative authoritative outcome proofs
merely because two Execution service instances reconcile the same action at once.
Per-instance locks cannot establish this invariant.
"""
from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
import unittest
from unittest.mock import patch

from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
import anka_execution.service as service_module
from anka_execution.service import DefinitiveExecutionService
from tests.test_m11_execution import (
    command, state, client, permit, evidence,
    StatePort, ClientPort, MechanicsPort, CoordinationPort,
)


class TestAgent08CrossInstanceSettlement(unittest.TestCase):
    def test_two_services_cannot_lose_cumulative_partial_outcome_proofs(self):
        with TemporaryDirectory() as td:
            c = command(8801)
            ledger = DefinitiveExecutionLedger(Path(td) / "shared.sqlite3")

            def make_service():
                service = DefinitiveExecutionService(
                    run_id="run-m11",
                    run_generation=2,
                    ledger=ledger,
                    arbiter=HostInputArbiter(),
                    state_reader=StatePort(state(c)),
                    client=ClientPort(client(c)),
                    mechanics=MechanicsPort(MechanicsResult("LEGAL")),
                    coordination=CoordinationPort(permit(c)),
                    driver=FakePhysicalInputDriver("sent"),
                    clock_ns=lambda: 50,
                )
                service.arm(authority_generation=9)
                return service

            # Both services are valid/armed before any unresolved action exists.
            first = make_service()
            second = make_service()
            self.assertEqual(first.submit(c).status, "PENDING")

            proof_a = evidence(c, 8801, proofs=("SPELL_CAST_CONFIRMED",))
            proof_b = evidence(
                c, 8802, proofs=("RESOURCE_DELTA_OR_TURN_PROGRESS",)
            )

            # Force both service instances to correlate from the same durable
            # PENDING snapshot before either one applies its result.
            real_correlate = service_module.correlate
            gate = Barrier(2)

            def synchronized_correlate(*args, **kwargs):
                verdict = real_correlate(*args, **kwargs)
                gate.wait(timeout=2)
                return verdict

            errors = []

            def settle(service, proof):
                try:
                    service.reconcile(c.action_id, proof)
                except BaseException as exc:
                    errors.append(exc)

            with patch.object(service_module, "correlate", synchronized_correlate):
                a = Thread(target=settle, args=(first, proof_a), daemon=True)
                b = Thread(target=settle, args=(second, proof_b), daemon=True)
                a.start()
                b.start()
                a.join(timeout=3)
                b.join(timeout=3)

            self.assertFalse(a.is_alive())
            self.assertFalse(b.is_alive())
            self.assertEqual(errors, [])

            final = ledger.get(c.action_id)
            self.assertEqual(
                final.status,
                "SETTLED_SUCCESS",
                "Cross-instance reconciliation lost one authoritative partial proof. "
                "The durable ledger must make cumulative proof settlement atomic, "
                "not rely only on a per-service lock.",
            )
            self.assertEqual(final.unresolved_obligations, ())


if __name__ == "__main__":
    unittest.main()
