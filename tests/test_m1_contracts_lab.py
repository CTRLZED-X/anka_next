"""M1 Q2 definitive contract/port/Verification Lab tests."""
from __future__ import annotations
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from anka_app.cli import ROOT
from anka_contracts.action import ActionCommand, ActionOutcome, PhysicalAttempt
from anka_contracts.client import ClientIdentity, ProjectionEvidence
from anka_contracts.coordination import MemberCursor, PartyCoherenceFrame, TurnPermit
from anka_contracts.decision import ActionPlan, DecisionFrame, PlannerResult
from anka_contracts.diagnostics import DiagnosticEvent, now_utc
from anka_contracts.errors import FailureRecord
from anka_contracts.evidence import EvidencePointer
from anka_contracts.ids import InvocationId, AccountId, ActionKey, FightEpoch
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.state import FieldProof, StateSnapshotIdentity
from anka_contracts.versions import RuntimeVersions, SchemaVersion
from anka_contracts.wire import WireEnvelope
from tests.lab.fakes import VirtualClock, FaultInjector, InjectedFault, FakeStateReader, FakeKernelQueries, FakeClientProjection, FakeActionExecutor, CountingInputDriver
from tests.lab.zero_input_stack import run_zero_input_contract_stack
from anka_contracts.verification import VerificationCheck, VerificationCounts, VerificationReceipt


class M1ContractTests(unittest.TestCase):
    def evidence(self):
        return EvidencePointer('evidence-1','AUTHORITY_COMMITTED','anka_canonical','cursor:7','a'*64,'fight:1')

    def snapshot(self):
        return StateSnapshotIdentity('snap-1','run-1','acct-cra','client-cra',1,2,3,7,9,'b'*64,
            '3.7.x','adapter-historical','reducer-v1','kernel-v1','data-v1','HEALTHY',
            (FieldProof('turn_owner','PROVEN',(self.evidence(),),''),))

    def frame_plan(self):
        frame=DecisionFrame('frame-1','run-1','acct-cra',2,3,'snap-1',7,'FIGHT_PROGRESS')
        plan=ActionPlan('plan-1','c'*64,'END_TURN',(),('NEXT_TURN_OWNER',),'snap-1',7)
        return frame,plan

    def command(self):
        return ActionCommand('action-1','run-1','acct-cra','client-cra',2,3,'c'*64,'END_TURN',7,(),('NEXT_TURN_OWNER',),100)

    def test_definitive_contract_families_exist(self):
        names={'ids.py','versions.py','evidence.py','wire.py','canonical.py','state.py','mechanics.py','decision.py','action.py','coordination.py','workflow.py','client.py','diagnostics.py','errors.py'}
        self.assertTrue(names.issubset({p.name for p in (ROOT/'src'/'anka_contracts').glob('*.py')}))
        port_names={'wire_sink.py','canonical_admission.py','committed_event_reader.py','state_reader.py','state_projector.py','kernel_queries.py','decision_planner.py','action_executor.py','party_coordinator.py','client_projection.py','diagnostics_sink.py','control_commands.py'}
        self.assertTrue(port_names.issubset({p.name for p in (ROOT/'src'/'anka_contracts'/'ports').glob('*.py')}))

    def test_typed_ids_reject_user_visible_unscoped_strings(self):
        self.assertEqual(str(InvocationId('inv-123')),'inv-123')
        self.assertEqual(str(AccountId('acct-cra')),'acct-cra')
        self.assertEqual(int(FightEpoch(3)),3)
        self.assertEqual(str(ActionKey('a'*64)),'a'*64)
        with self.assertRaises(ValueError): AccountId('Curseni')
        with self.assertRaises(ValueError): ActionKey('not-a-digest')

    def test_unknown_evidence_cannot_authorize(self):
        unknown=EvidencePointer('evidence-u','UNKNOWN','anka_protocol','message:missing')
        self.assertFalse(unknown.can_authorize)
        self.assertTrue(self.evidence().can_authorize)

    def test_wire_contract_contains_transport_not_game_semantics(self):
        wire=WireEnvelope('capture-1','client-cra','conn-1','server_to_client',0,1,'2026-10-22T00:00:00Z',10,b'abc')
        self.assertEqual(wire.payload,b'abc')
        self.assertFalse(any(name.lower() in {'ap','mp','hp','spell_id'} for name in wire.__dataclass_fields__))

    def test_state_unknown_is_explicit_not_zero(self):
        unknown=FieldProof('ap','UNKNOWN',(), 'not observed')
        self.assertEqual(unknown.status,'UNKNOWN')
        with self.assertRaises(ValueError): FieldProof('ap','PROVEN',(), '')

    def test_planner_result_distinguishes_wait_no_action_fault_and_plan(self):
        frame,plan=self.frame_plan()
        self.assertEqual(PlannerResult('PLAN',plan=plan).disposition,'PLAN')
        self.assertEqual(PlannerResult('WAIT',required_evidence=('TURN_OWNER',),reason='owner missing').disposition,'WAIT')
        self.assertEqual(PlannerResult('NO_ACTION',reason='no legal candidate').disposition,'NO_ACTION')
        self.assertEqual(PlannerResult('FAULT',reason='planner failure',failure_code='PLANNER_FAILED').disposition,'FAULT')
        with self.assertRaises(ValueError): PlannerResult('WAIT',reason='missing list')

    def test_ambiguous_send_can_never_be_marked_retryable(self):
        with self.assertRaises(ValueError): ActionOutcome('action-1','attempt-1','UNCERTAIN',('evidence-1',),True)
        outcome=ActionOutcome('action-1','attempt-1','UNCERTAIN',('evidence-1',),False,('SERVER_OUTCOME',))
        self.assertFalse(outcome.retry_eligible)
        with self.assertRaises(ValueError): FailureRecord('SEND_UNCERTAIN','anka_execution','driver.send','SAFETY','ACCOUNT_BLOCK','action','MAY_HAVE_SENT',True,('evidence-1',),'unknown send')

    def test_physical_attempt_distinguishes_send_states_from_success(self):
        attempt=PhysicalAttempt('attempt-1','action-1',1,'client-cra',2,3,'prepare-1','SENT',10,11)
        self.assertEqual(attempt.send_state,'SENT')
        self.assertFalse(hasattr(attempt,'success'))

    def test_cross_account_frame_is_vector_not_fake_global_revision(self):
        members=(MemberCursor('acct-cra','client-cra',7,4,2,3,True),MemberCursor('acct-enu','client-enu',11,9,2,3,True))
        frame=PartyCoherenceFrame('party-1',2,members,True,'ACTIVE','acct-cra',5)
        self.assertEqual([m.canonical_cursor for m in frame.members],[7,11])
        self.assertFalse(hasattr(frame,'global_canonical_revision'))
        with self.assertRaises(ValueError): PartyCoherenceFrame('party-1',2,members,True,'ACTIVE','acct-other',5)

    def test_diagnostic_envelope_roundtrip_carries_owner_cursor_and_input_state(self):
        event=DiagnosticEvent(1,'evt-1','execution.preflight_rejected','ERROR',now_utc(),1,1,'inv-1','run-1',
            owner_system='anka_execution',physical_input_state='NOT_SENT',canonical_cursor=7,boundary='pre_input_authorization',failure_code='WINDOW_FOCUS_MISMATCH')
        self.assertEqual(DiagnosticEvent.from_dict(event.to_dict()),event)

    def test_runtime_versions_are_independent(self):
        versions=RuntimeVersions('m1-dev','a'*64,None,None,SchemaVersion(1,0),'state-v1','kernel-v1','data-v1',None,SchemaVersion(1,0),SchemaVersion(1,0))
        payload=versions.to_dict()
        self.assertIsNone(payload['observed_client_build'])
        self.assertEqual(payload['canonical_schema']['major'],1)

    def test_verification_lab_fakes_and_virtual_clock_have_zero_os_input(self):
        snap=self.snapshot(); frame,plan=self.frame_plan(); command=self.command()
        state=FakeStateReader({'acct-cra':snap})
        kernel=FakeKernelQueries(MechanicsResult('LEGAL'))
        identity=ClientIdentity('client-cra','acct-cra',10,20,30,1,'PROVEN',9,'PROVEN',None,1280,649,96)
        projection=ProjectionEvidence('client-cra',1,None,1,'cell','42',100,200,5,True)
        client=FakeClientProjection({'acct-cra':identity},{('acct-cra','cell','42'):projection})
        outcome=ActionOutcome('action-1',None,'REJECTED_NOT_SENT',(),True)
        executor=FakeActionExecutor(outcome)
        self.assertEqual(state.current_snapshot('acct-cra'),snap)
        self.assertEqual(kernel.validate_plan(frame,plan).status,'LEGAL')
        self.assertEqual(client.project('acct-cra','cell','42'),projection)
        self.assertEqual(executor.submit(command).status,'REJECTED_NOT_SENT')
        clock=VirtualClock(10); self.assertEqual(clock.advance_ns(5),15)
        driver=CountingInputDriver(); self.assertEqual(driver.send('CLICK',(1,2)),'FAKE_ACCEPTED_NO_OS_INPUT'); self.assertEqual(len(driver.calls),1)
        source=(ROOT/'tests'/'lab'/'fakes.py').read_text()
        for forbidden in ('pyautogui','pynput','SendInput','mouse_event','SetCursorPos'):
            self.assertNotIn(forbidden,source)

    def test_fault_injector_is_deterministic(self):
        fault=FaultInjector('commit')
        fault('prepare')
        with self.assertRaisesRegex(InjectedFault,'commit'): fault('commit')
        self.assertEqual(fault.hit,['prepare','commit'])

    def test_fake_full_stack_contract_walk_has_zero_physical_input(self):
        result=run_zero_input_contract_stack()
        self.assertEqual(result.physical_input_count,0)
        self.assertEqual(result.state_reads,1)
        self.assertEqual(result.kernel_queries,1)
        self.assertEqual(result.identity_reads,1)
        self.assertEqual(result.projection_reads,1)
        self.assertEqual(result.execution_submissions,1)
        self.assertEqual(result.outcome_status,'REJECTED_NOT_SENT')

    def test_verification_receipt_schema_roundtrip_and_unsatisfied_pass_rejected(self):
        check=VerificationCheck('CONTRACT_ROUNDTRIP','PASS','fixture passed')
        receipt=VerificationReceipt(1,'Q2','M1','PASS','2026-10-22T00:00:00Z','a'*64,None,None,'3.13.5',None,None,None,None,None,None,None,
            VerificationCounts(passed=1),VerificationCounts(passed=1),(('platform','test'),),1,0,'FAKE_ONLY',(check,),('offline-only',),())
        self.assertEqual(VerificationReceipt.from_dict(receipt.to_dict()),receipt)
        bad=VerificationCheck('MISSING_CURRENT_BUILD','MISSING_EVIDENCE','not available')
        with self.assertRaises(ValueError):
            VerificationReceipt(1,'Q2','M1','PASS','2026-10-22T00:00:00Z','a'*64,None,None,'3.13.5',None,None,None,None,None,None,None,
                VerificationCounts(missing_evidence=1),VerificationCounts(),(('platform','test'),),1,0,'FAKE_ONLY',(bad,),('offline-only',),())



class TestMilestoneReceipt(unittest.TestCase):
    def test_milestone_receipt_cannot_hide_unverified_scope(self):
        from anka_contracts.verification import MilestoneReceipt, VerificationCheck, VerificationCounts
        common=dict(schema_version=1,milestone_id='M3',verification_scope='offline client foundation',
            generated_utc='2026-01-01T00:00:00+00:00',source_tree_sha256='a'*64,
            test_counts=VerificationCounts(passed=1),duration_ms=1,physical_input_count=0,
            physical_input_state='DISABLED',checks=(VerificationCheck('M3_OFFLINE','PASS','offline proof'),),
            known_limitations=('Windows host not accepted.',))
        r=MilestoneReceipt(status='PASS',**common)
        self.assertEqual(MilestoneReceipt.from_dict(r.to_dict()),r)
        with self.assertRaisesRegex(ValueError,'PASS_MILESTONE_HAS_UNSATISFIED_EVIDENCE'):
            MilestoneReceipt(status='PASS',**{**common,'checks':(VerificationCheck('M3_WINDOWS','MISSING_EVIDENCE','not run'),)})

if __name__=='__main__': unittest.main()
