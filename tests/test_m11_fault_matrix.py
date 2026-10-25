from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.service import DefinitiveExecutionService
from tests.test_m11_execution import command,state,client,permit,evidence,StatePort,ClientPort,MechanicsPort,CoordinationPort

class M11CrashCutMatrix(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def service(self,c,ledger,driver=None,states=None,clients=None,permits=None):
        return DefinitiveExecutionService(
            run_id='run-m11',run_generation=2,ledger=ledger,arbiter=HostInputArbiter(),
            state_reader=StatePort(*(states or (state(c),))),client=ClientPort(*(clients or (client(c),))),
            mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(*(permits or (permit(c),))),
            driver=driver or FakePhysicalInputDriver(),clock_ns=lambda:50)

    def test_cut_before_prepare_has_no_durable_action_and_can_arm(self):
        c=command(200);l=DefinitiveExecutionLedger(Path(self.temp.name)/'a.sqlite3');svc=self.service(c,l)
        self.assertEqual(l.unresolved(),());svc.arm(authority_generation=1);self.assertTrue(svc.armed)

    def test_cut_after_prepare_recovers_definitely_not_sent(self):
        c=command(201);l=DefinitiveExecutionLedger(Path(self.temp.name)/'b.sqlite3');l.prepare(c,2,1)
        svc=self.service(c,l);a=l.get(c.action_id)
        self.assertEqual((a.status,a.send_state),('REJECTED_NOT_SENT','NOT_SENT'));svc.arm(authority_generation=2)

    def test_cut_after_send_started_recovers_uncertain_and_blocks_arm(self):
        c=command(202);l=DefinitiveExecutionLedger(Path(self.temp.name)/'c.sqlite3');l.prepare(c,2,1);l.mark_send_started(c.action_id,'attempt-cut')
        svc=self.service(c,l);a=l.get(c.action_id)
        self.assertEqual((a.status,a.send_state),('UNCERTAIN','MAY_HAVE_SENT'))
        with self.assertRaisesRegex(Exception,'UNRESOLVED_ACTIONS_BLOCK_ARM'):svc.arm(authority_generation=2)

    def test_cut_after_driver_acceptance_remains_pending_without_resend(self):
        c=command(203);l=DefinitiveExecutionLedger(Path(self.temp.name)/'d.sqlite3');l.prepare(c,2,1);l.mark_send_started(c.action_id,'attempt-cut');l.mark_sent(c.action_id)
        drv=FakePhysicalInputDriver();svc=self.service(c,l,driver=drv)
        self.assertEqual(l.get(c.action_id).status,'PENDING');self.assertEqual(drv.call_count,0)
        with self.assertRaisesRegex(Exception,'UNRESOLVED_ACTIONS_BLOCK_ARM'):svc.arm(authority_generation=2)

    def test_cut_after_outcome_commit_before_workflow_can_rearm_without_resend(self):
        c=command(204);l=DefinitiveExecutionLedger(Path(self.temp.name)/'e.sqlite3');l.prepare(c,2,1);l.mark_send_started(c.action_id,'attempt-cut');l.mark_sent(c.action_id)
        l.apply_outcome(c.action_id,'SETTLED_SUCCESS',evidence(c,1),'EXPECTED_OUTCOME_PROOFS_SATISFIED',())
        drv=FakePhysicalInputDriver();svc=self.service(c,l,driver=drv);svc.arm(authority_generation=2)
        self.assertTrue(svc.armed);self.assertEqual(drv.call_count,0);self.assertEqual(l.get(c.action_id).status,'SETTLED_SUCCESS')

    def test_partial_outcome_survives_restart_and_later_proof_completes(self):
        c=command(205);l=DefinitiveExecutionLedger(Path(self.temp.name)/'f.sqlite3');svc=self.service(c,l);svc.arm(authority_generation=1);svc.submit(c)
        first=svc.reconcile(c.action_id,evidence(c,1,proofs=('SPELL_CAST_CONFIRMED',)));self.assertEqual(first.status,'CONFIRMED_UNSETTLED')
        svc2=self.service(c,l);self.assertEqual(l.get(c.action_id).status,'CONFIRMED_UNSETTLED')
        done=svc2.reconcile(c.action_id,evidence(c,2,proofs=('RESOURCE_DELTA_OR_TURN_PROGRESS',)))
        self.assertEqual(done.status,'SETTLED_SUCCESS')

    def test_latest_state_change_inside_driver_guard_prevents_fake_send(self):
        c=command(206);l=DefinitiveExecutionLedger(Path(self.temp.name)/'g.sqlite3');drv=FakePhysicalInputDriver('sent')
        svc=self.service(c,l,driver=drv,states=(state(c),state(c),state(c,invalidating_change_since_basis=True)))
        svc.arm(authority_generation=1);o=svc.submit(c)
        self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(drv.call_count,0);self.assertEqual(l.get(c.action_id).send_state,'NOT_SENT')

    def test_permit_generation_change_inside_guard_prevents_fake_send(self):
        c=command(207);l=DefinitiveExecutionLedger(Path(self.temp.name)/'h.sqlite3');drv=FakePhysicalInputDriver('sent')
        svc=self.service(c,l,driver=drv,permits=(permit(c),permit(c),permit(c,permit_generation=6)))
        svc.arm(authority_generation=1);o=svc.submit(c)
        self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(drv.call_count,0)

    def test_terminal_unresolved_never_makes_same_semantic_key_retry_eligible(self):
        c=command(208);l=DefinitiveExecutionLedger(Path(self.temp.name)/'i.sqlite3');svc=self.service(c,l,driver=FakePhysicalInputDriver('may-have-sent'));svc.arm(authority_generation=1)
        self.assertEqual(svc.submit(c).status,'UNCERTAIN');term=svc.terminalize_unresolved(c.action_id);self.assertFalse(term.retry_eligible)
        c2=replace(command(209),action_key=c.action_key);o=svc.submit(c2)
        self.assertEqual(o.status,'REJECTED_NOT_SENT')

if __name__=='__main__':unittest.main()
