from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.service import DefinitiveExecutionService
from tests.test_m11_execution import command,state,client,permit,StatePort,ClientPort,MechanicsPort,CoordinationPort

class M11SafetyMutationCase(unittest.TestCase):
    def setUp(self):self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def service(self,c,*,states,driver):
        l=DefinitiveExecutionLedger(Path(self.temp.name)/f'{c.action_id}.sqlite3')
        svc=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=l,arbiter=HostInputArbiter(),state_reader=StatePort(*states),client=ClientPort(client(c)),mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(permit(c)),driver=driver,clock_ns=lambda:50)
        svc.arm(authority_generation=1);return svc,l

    def test_mutating_latest_context_comparison_would_allow_forbidden_send(self):
        c=command(300);drv=FakePhysicalInputDriver('sent')
        svc,l=self.service(c,states=(state(c),state(c),state(c,invalidating_change_since_basis=True)),driver=drv)
        with patch.object(DefinitiveExecutionService,'_same_external_context',staticmethod(lambda a,b: True)):
            out=svc.submit(c)
        # The independent oracle says this mutated behavior is unsafe: a driver call
        # occurred even though the final state invalidated the plan.
        self.assertEqual(drv.call_count,1);self.assertEqual(out.status,'PENDING')
        self.assertNotEqual(l.get(c.action_id).send_state,'NOT_SENT')

    def test_mutating_minimum_outcome_policy_would_admit_under_specified_cast(self):
        from dataclasses import replace
        c=replace(command(301),expected_outcome_proofs=('SPELL_CAST_CONFIRMED',));drv=FakePhysicalInputDriver('sent')
        svc,_=self.service(c,states=(state(c),),driver=drv)
        with patch('anka_execution.service.validates_minimum_outcome_policy',lambda _:True):
            out=svc.submit(c)
        self.assertEqual(drv.call_count,1);self.assertEqual(out.status,'PENDING')

if __name__=='__main__':unittest.main()
