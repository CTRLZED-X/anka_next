from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event,Thread
import sqlite3,unittest

from anka_contracts.action import ActionCommand
from anka_contracts.execution import (ExecutionClientAttestation,ExecutionCoordinationPermit,
    ExecutionOutcomeEvidence,ExecutionStateView,DriverSendReceipt)
from anka_contracts.mechanics import MechanicsResult
from anka_execution.arbiter import HostInputArbiter,InputLeaseBusy
from anka_execution.definitive_ledger import DefinitiveExecutionLedger,DefinitiveExecutionLedgerError
from anka_execution.drivers.fake_input import FakePhysicalInputDriver
from anka_execution.drivers.windows_input import WindowsActionScopeEnablement,WindowsPointerInputDriver,WindowsInputDisabled,PointerTransaction
from anka_execution.service import DefinitiveExecutionService,_target_fingerprint

class Seq:
    def __init__(self,*values):self.values=list(values);self.i=0
    def next(self):
        if not self.values:raise RuntimeError('NO_FIXTURE')
        v=self.values[min(self.i,len(self.values)-1)];self.i+=1
        if isinstance(v,BaseException):raise v
        return v
class StatePort:
    def __init__(self,*v):self.s=Seq(*v)
    def current_for_action(self,c):return self.s.next()
class ClientPort:
    def __init__(self,*v):self.s=Seq(*v)
    def attest_for_action(self,c):return self.s.next()
class MechanicsPort:
    def __init__(self,*v):self.s=Seq(*v)
    def validate_action(self,c,state):return self.s.next()
class CoordinationPort:
    def __init__(self,*v):self.s=Seq(*v)
    def permit_for_action(self,c):return self.s.next()


def command(n=1,kind='CAST',*,deadline=None,action_key=None,actor=41):
    target=(('spell_id','1234'),('grade','3'),('target_cell','250')) if kind=='CAST' else ((('actor_id',str(actor)),) if kind=='END_TURN' else (('target_cell','250'),))
    proofs=('SPELL_CAST_CONFIRMED','RESOURCE_DELTA_OR_TURN_PROGRESS') if kind=='CAST' else (('TURN_OWNER_CHANGED',) if kind=='END_TURN' else ('ACTOR_CELL_CHANGED',))
    return ActionCommand(f'action-m11-{n}','run-m11','acct-cra','client-cra',7,11,action_key or f'{n:064x}'[-64:],kind,100,target,proofs,deadline_monotonic_ns=deadline,basis_snapshot_id='snap-plan',party_id='party-main',basis_party_generation=3,basis_permit_generation=5,actor_id=actor)

def state(c:ActionCommand,**kw):
    d=dict(snapshot_id='snap-current',snapshot_sha256='a'*64,account_id=c.account_id,client_instance_id=c.client_instance_id,fight_epoch=c.fight_epoch,turn_epoch=c.turn_epoch,canonical_cursor=101,actor_id=c.actor_id,turn_owner_actor_id=c.actor_id,health='HEALTHY',required_proofs=(('ap','KNOWN'),('actor_cell','KNOWN'),('loadout','KNOWN')),invalidating_change_since_basis=False);d.update(kw);return ExecutionStateView(**d)
def permit(c:ActionCommand,**kw):
    d=dict(party_id='party-main',account_id=c.account_id,fight_epoch=c.fight_epoch,turn_epoch=c.turn_epoch,party_generation=3,permit_generation=5,allowed=True,reason='PERMIT_GRANTED',evidence_ids=('permit-evidence',));d.update(kw);return ExecutionCoordinationPermit(**d)
def client(c:ActionCommand,**kw):
    d=dict(attestation_id='clientatt-good',account_id=c.account_id,client_instance_id=c.client_instance_id,observed_client_build='fixture-build',pid=10,process_created_100ns=20,hwnd=30,window_generation=4,projection_generation=6,calibration_generation=8,loadout_generation=9,pixel_x=100,pixel_y=200,identity_proven=True,class_proven=True,foreground_proven=True,visible_proven=True,geometry_proven=True,projection_proven=True,loadout_binding_proven=True,semantic_target_fingerprint=_target_fingerprint(c),evidence_ids=('client-evidence',));d.update(kw);return ExecutionClientAttestation(**d)
def evidence(c:ActionCommand,n=1,**kw):
    d=dict(evidence_id=f'outcome-{n}',account_id=c.account_id,client_instance_id=c.client_instance_id,fight_epoch=c.fight_epoch,observed_turn_epoch=c.turn_epoch,canonical_cursor=110+n,result='CONFIRMATION',proofs=c.expected_outcome_proofs,authoritative=True,correlated_action_id=None,actor_id=c.actor_id);d.update(kw);return ExecutionOutcomeEvidence(**d)

class M11Case(unittest.TestCase):
    def setUp(self):self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    def make(self,c,*,driver=None,states=None,clients=None,mechanics=None,permits=None,clock=None,arm=True):
        ledger=DefinitiveExecutionLedger(Path(self.temp.name)/f'{c.action_id}.sqlite3');arb=HostInputArbiter();drv=driver or FakePhysicalInputDriver('sent')
        svc=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=ledger,arbiter=arb,state_reader=StatePort(*(states or (state(c),))),client=ClientPort(*(clients or (client(c),))),mechanics=MechanicsPort(*(mechanics or (MechanicsResult('LEGAL'),))),coordination=CoordinationPort(*(permits or (permit(c),))),driver=drv,clock_ns=clock or (lambda:50))
        if arm:svc.arm(authority_generation=9)
        return svc,ledger,drv,arb

    def test_good_send_is_pending_not_success(self):
        c=command();svc,l,d,_=self.make(c);o=svc.submit(c)
        self.assertEqual(o.status,'PENDING');self.assertFalse(o.retry_eligible);self.assertEqual(d.call_count,1);self.assertEqual(svc.physical_input_count,0);self.assertEqual(l.get(c.action_id).status,'PENDING')

    def test_execution_owns_minimum_outcome_policy(self):
        c=command(4)
        weak=replace(c,expected_outcome_proofs=('SPELL_CAST_CONFIRMED',))
        svc,_,d,_=self.make(weak);o=svc.submit(weak)
        self.assertEqual(o.reason,'EXECUTION_OUTCOME_POLICY_UNDERSPECIFIED');self.assertEqual(d.call_count,0)

    def test_stale_epoch_rejected_zero_driver(self):
        c=command();svc,l,d,_=self.make(c,states=(state(c,turn_epoch=12),));o=svc.submit(c)
        self.assertEqual((o.status,o.reason,d.call_count),('REJECTED_NOT_SENT','ACTION_EPOCH_STALE',0))

    def test_state_invalidation_and_actor_owner_mismatch_rejected(self):
        c=command();svc,_,d,_=self.make(c,states=(state(c,invalidating_change_since_basis=True),));self.assertEqual(svc.submit(c).reason,'ACTION_BASIS_INVALIDATED');self.assertEqual(d.call_count,0)
        c2=command(2);svc2,_,d2,_=self.make(c2,states=(state(c2,turn_owner_actor_id=42),));self.assertEqual(svc2.submit(c2).reason,'TURN_OWNER_NOT_PROVEN_FOR_ACTOR');self.assertEqual(d2.call_count,0)

    def test_focus_projection_and_cast_loadout_rejected(self):
        for i,changes in enumerate(({'foreground_proven':False},{'projection_proven':False},{'loadout_binding_proven':False}),10):
            c=command(i);svc,_,d,_=self.make(c,clients=(client(c,**changes),));self.assertEqual(svc.submit(c).status,'REJECTED_NOT_SENT');self.assertEqual(d.call_count,0)

    def test_kernel_illegal_and_indeterminate_rejected(self):
        for i,m in enumerate((MechanicsResult('ILLEGAL','blocked'),MechanicsResult('INDETERMINATE','missing')),20):
            c=command(i);svc,_,d,_=self.make(c,mechanics=(m,));o=svc.submit(c);self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertTrue(o.reason.startswith('KERNEL_'));self.assertEqual(d.call_count,0)

    def test_coordination_denial_and_generation_stale_rejected(self):
        c=command(30);svc,_,d,_=self.make(c,permits=(permit(c,allowed=False,reason='NOT_CURRENT_TURN_OWNER',evidence_ids=()),));self.assertIn('NOT_CURRENT_TURN_OWNER',svc.submit(c).reason);self.assertEqual(d.call_count,0)
        c2=command(31);svc2,_,d2,_=self.make(c2,permits=(permit(c2,permit_generation=6),));self.assertEqual(svc2.submit(c2).reason,'COORDINATION_PERMIT_GENERATION_STALE');self.assertEqual(d2.call_count,0)

    def test_external_context_change_after_prepare_is_proven_not_sent(self):
        c=command(40);a=client(c);b=client(c,attestation_id='clientatt-new',window_generation=5)
        svc,l,d,_=self.make(c,clients=(a,b));o=svc.submit(c)
        self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(d.call_count,0);self.assertEqual(l.get(c.action_id).send_state,'NOT_SENT')

    def test_mid_driver_guard_change_stops_before_fake_send(self):
        c=command(41);good=client(c);bad=client(c,attestation_id='clientatt-drift',foreground_proven=False)
        # initial, final, first driver guard, second driver guard
        svc,l,d,_=self.make(c,driver=FakePhysicalInputDriver('guard-twice'),clients=(good,good,good,bad))
        o=svc.submit(c);self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(l.get(c.action_id).send_state,'NOT_SENT');self.assertEqual(svc.physical_input_count,0)

    def test_driver_proven_before_send_vs_ambiguous_after(self):
        c=command(50);svc,l,d,_=self.make(c,driver=FakePhysicalInputDriver('raise-before'));o=svc.submit(c);self.assertEqual((o.status,o.retry_eligible),('REJECTED_NOT_SENT',True));self.assertEqual(l.get(c.action_id).status,'REJECTED_NOT_SENT')
        c2=command(51);svc2,l2,d2,_=self.make(c2,driver=FakePhysicalInputDriver('raise-after'));o2=svc2.submit(c2);self.assertEqual((o2.status,o2.retry_eligible),('UNCERTAIN',False));self.assertEqual(l2.get(c2.action_id).send_state,'MAY_HAVE_SENT')

    def test_ledger_failure_after_driver_entry_never_becomes_retryable_not_sent(self):
        c=command(52);svc,l,_,_=self.make(c,driver=FakePhysicalInputDriver('raise-after'))
        def broken_mark_uncertain(*_args,**_kwargs):raise OSError('ledger unavailable')
        l.mark_uncertain=broken_mark_uncertain
        o=svc.submit(c)
        self.assertEqual(o.status,'UNCERTAIN');self.assertFalse(o.retry_eligible)
        self.assertTrue(o.reason.startswith('EXECUTION_LEDGER_UNAVAILABLE_AFTER_DRIVER:'))
        self.assertFalse(svc.armed);self.assertEqual(svc.last_safety_fault,o.reason)
        with self.assertRaisesRegex(Exception,'SAFETY_FAULT_REQUIRES_NEW_SERVICE_INSTANCE'):
            svc.arm(authority_generation=10)

    def test_ambiguous_send_blocks_any_new_dispatch(self):
        c=command(60);svc,l,d,_=self.make(c,driver=FakePhysicalInputDriver('may-have-sent'));self.assertEqual(svc.submit(c).status,'UNCERTAIN')
        c2=command(61);o=svc.submit(c2);self.assertEqual(o.reason,'UNRESOLVED_ACTION_FENCE');self.assertEqual(d.call_count,1)

    def test_restart_prepare_is_not_sent_but_send_started_is_uncertain(self):
        c=command(70);ledger=DefinitiveExecutionLedger(Path(self.temp.name)/'exec.sqlite3');ledger.prepare(c,2,9)
        svc=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=ledger,arbiter=HostInputArbiter(),state_reader=StatePort(state(c)),client=ClientPort(client(c)),mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(permit(c)),driver=FakePhysicalInputDriver())
        self.assertEqual(ledger.get(c.action_id).status,'REJECTED_NOT_SENT');svc.arm(authority_generation=10)
        # Separate ledger representing crash after entering external boundary.
        path2=Path(self.temp.name)/'exec2.sqlite3';l2=DefinitiveExecutionLedger(path2);c2=command(71);l2.prepare(c2,2,9);l2.mark_send_started(c2.action_id,'attempt-crash')
        svc2=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=l2,arbiter=HostInputArbiter(),state_reader=StatePort(state(c2)),client=ClientPort(client(c2)),mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(permit(c2)),driver=FakePhysicalInputDriver())
        self.assertEqual(l2.get(c2.action_id).status,'UNCERTAIN');self.assertFalse(svc2.armed)
        with self.assertRaisesRegex(Exception,'UNRESOLVED_ACTIONS_BLOCK_ARM'):svc2.arm(authority_generation=10)

    def test_partial_then_complete_authoritative_outcome(self):
        c=command(80);svc,l,_,_=self.make(c);self.assertEqual(svc.submit(c).status,'PENDING')
        partial=evidence(c,1,proofs=('SPELL_CAST_CONFIRMED',));o=svc.reconcile(c.action_id,partial);self.assertEqual(o.status,'CONFIRMED_UNSETTLED');self.assertIn('RESOURCE_DELTA_OR_TURN_PROGRESS',o.unresolved_obligations)
        complete=evidence(c,2);o2=svc.reconcile(c.action_id,complete);self.assertEqual(o2.status,'SETTLED_SUCCESS');self.assertFalse(l.unresolved())


    def test_partial_proofs_accumulate_across_separate_observations(self):
        c=command(81);svc,l,_,_=self.make(c);self.assertEqual(svc.submit(c).status,'PENDING')
        first=svc.reconcile(c.action_id,evidence(c,1,proofs=('SPELL_CAST_CONFIRMED',)))
        self.assertEqual(first.status,'CONFIRMED_UNSETTLED')
        self.assertEqual(first.unresolved_obligations,('RESOURCE_DELTA_OR_TURN_PROGRESS',))
        second=svc.reconcile(c.action_id,evidence(c,2,proofs=('RESOURCE_DELTA_OR_TURN_PROGRESS',)))
        self.assertEqual(second.status,'SETTLED_SUCCESS');self.assertFalse(l.unresolved())

    def test_weak_evidence_never_regresses_partial_or_terminal_status(self):
        c=command(82);svc,l,_,_=self.make(c);svc.submit(c)
        partial=svc.reconcile(c.action_id,evidence(c,1,proofs=('SPELL_CAST_CONFIRMED',)))
        self.assertEqual(partial.status,'CONFIRMED_UNSETTLED')
        weak=svc.reconcile(c.action_id,evidence(c,2,result='INCONCLUSIVE',proofs=()))
        self.assertEqual(weak.status,'CONFIRMED_UNSETTLED')
        ignored=svc.reconcile(c.action_id,evidence(c,3,authoritative=False,proofs=()))
        self.assertEqual(ignored.status,'CONFIRMED_UNSETTLED')
        done=svc.reconcile(c.action_id,evidence(c,4,proofs=('RESOURCE_DELTA_OR_TURN_PROGRESS',)))
        self.assertEqual(done.status,'SETTLED_SUCCESS')
        after=svc.reconcile(c.action_id,evidence(c,5,authoritative=False,proofs=()))
        self.assertEqual(after.status,'SETTLED_SUCCESS');self.assertEqual(l.get(c.action_id).status,'SETTLED_SUCCESS')

    def test_inconclusive_evidence_does_not_downgrade_uncertain_send(self):
        c=command(83);svc,l,_,_=self.make(c,driver=FakePhysicalInputDriver('may-have-sent'))
        self.assertEqual(svc.submit(c).status,'UNCERTAIN')
        o=svc.reconcile(c.action_id,evidence(c,1,result='INCONCLUSIVE',proofs=()))
        self.assertEqual(o.status,'UNCERTAIN');self.assertEqual(l.get(c.action_id).send_state,'MAY_HAVE_SENT')

    def test_wrong_scope_old_cursor_actor_and_non_authoritative_do_not_settle(self):
        cases=(dict(fight_epoch=8),dict(canonical_cursor=100),dict(actor_id=999),dict(authoritative=False))
        for i,change in enumerate(cases,90):
            c=command(i);svc,l,_,_=self.make(c);svc.submit(c);o=svc.reconcile(c.action_id,evidence(c,i,**change));self.assertEqual(o.status,'PENDING');self.assertEqual(l.get(c.action_id).status,'PENDING')

    def test_authoritative_failure_is_terminal_not_auto_retry(self):
        c=command(100);svc,l,_,_=self.make(c);svc.submit(c);o=svc.reconcile(c.action_id,evidence(c,1,result='FAILURE',proofs=('SERVER_REJECTED',)));self.assertEqual((o.status,o.retry_eligible),('PROVEN_FAILURE',False));self.assertFalse(l.unresolved())

    def test_outcome_can_arrive_before_driver_returns(self):
        entered=Event();release=Event()
        class BlockingDriver:
            mode='FAKE_ONLY'
            def send(self,cmd,cl,lease,guard):
                self.guard=guard;self.asserted=guard();entered.set();release.wait(5);return DriverSendReceipt(cmd.action_id,'SENT',0,'LATE_DRIVER_RETURN')
        c=command(110);drv=BlockingDriver();svc,l,_,_=self.make(c,driver=drv);box={}
        t=Thread(target=lambda:box.setdefault('outcome',svc.submit(c)));t.start();self.assertTrue(entered.wait(2));early=svc.reconcile(c.action_id,evidence(c,1));self.assertEqual(early.status,'SETTLED_SUCCESS');release.set();t.join(3);self.assertFalse(t.is_alive());self.assertEqual(box['outcome'].status,'SETTLED_SUCCESS');self.assertEqual(l.get(c.action_id).status,'SETTLED_SUCCESS')

    def test_raced_ahead_outcome_wins_over_all_late_driver_results(self):
        cases=('NOT_SENT','MAY_HAVE_SENT','RAISE_NOT_SENT','RAISE_MAY_HAVE_SENT')
        for offset,mode in enumerate(cases,111):
            with self.subTest(mode=mode):
                entered=Event();release=Event()
                class BlockingDriver:
                    mode='FAKE_ONLY'
                    def send(self,cmd,cl,lease,guard):
                        self.asserted=guard();entered.set();release.wait(5)
                        if mode=='RAISE_NOT_SENT':raise InputDriverFailure('LATE_PROVEN_NOT_SENT',may_have_sent=False)
                        if mode=='RAISE_MAY_HAVE_SENT':raise InputDriverFailure('LATE_AMBIGUOUS_FAILURE',may_have_sent=True)
                        return DriverSendReceipt(cmd.action_id,mode,0,'LATE_'+mode)
                c=command(offset);drv=BlockingDriver();svc,l,_,_=self.make(c,driver=drv);box={}
                t=Thread(target=lambda:box.setdefault('outcome',svc.submit(c)))
                t.start();self.assertTrue(entered.wait(2))
                early=svc.reconcile(c.action_id,evidence(c,offset));self.assertEqual(early.status,'SETTLED_SUCCESS')
                release.set();t.join(3);self.assertFalse(t.is_alive())
                self.assertEqual(box['outcome'].status,'SETTLED_SUCCESS')
                self.assertFalse(box['outcome'].retry_eligible)
                self.assertEqual(l.get(c.action_id).status,'SETTLED_SUCCESS')
                l.audit()

    def test_ledger_prepare_fence_is_atomic_under_concurrency(self):
        path=Path(self.temp.name)/'race.sqlite3';l=DefinitiveExecutionLedger(path)
        results=[]
        def worker(c):
            try:l.prepare(c,2,9);results.append(('ok',c.action_id))
            except Exception as exc:results.append((str(exc),c.action_id))
        a=command(111);b=replace(command(112),account_id='acct-enu',client_instance_id='client-enu')
        t1=Thread(target=worker,args=(a,));t2=Thread(target=worker,args=(b,));t1.start();t2.start();t1.join();t2.join()
        self.assertEqual(sum(x[0]=='ok' for x in results),1)
        self.assertEqual(len(l.unresolved()),1)
        self.assertTrue(any('UNRESOLVED_ACTION_FENCE' in x[0] for x in results if x[0]!='ok'))

    def test_host_wide_arbiter_serializes_accounts(self):
        a=HostInputArbiter();l=a.acquire('action-a','acct-cra',now_ns=1)
        with self.assertRaises(InputLeaseBusy):a.acquire('action-b','acct-enu',now_ns=2)
        a.release(l);l2=a.acquire('action-b','acct-enu',now_ns=3);self.assertGreater(l2.lease_epoch,l.lease_epoch);a.release(l2)

    def test_deadline_and_disarm_reject_without_driver(self):
        c=command(120,deadline=40);svc,_,d,_=self.make(c,clock=lambda:50);self.assertEqual(svc.submit(c).reason,'ACTION_DEADLINE_EXPIRED');self.assertEqual(d.call_count,0)
        c2=command(121);svc2,_,d2,_=self.make(c2);svc2.disarm();self.assertEqual(svc2.submit(c2).reason,'INPUT_AUTHORITY_DISARMED');self.assertEqual(d2.call_count,0)

    def test_duplicate_semantic_key_cannot_be_blindly_reissued(self):
        key='f'*64;c=command(130,action_key=key);svc,l,d,_=self.make(c,states=(state(c,turn_epoch=12),));self.assertEqual(svc.submit(c).status,'REJECTED_NOT_SENT')
        c2=command(131,action_key=key);o=svc.submit(c2);self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(d.call_count,0)

    def test_restart_pending_is_not_resent_and_settled_restart_can_rearm(self):
        c=command(135);l=DefinitiveExecutionLedger(Path(self.temp.name)/'pending.sqlite3');l.prepare(c,2,9);l.mark_send_started(c.action_id,'attempt-pending');l.mark_sent(c.action_id)
        d=FakePhysicalInputDriver();svc=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=l,arbiter=HostInputArbiter(),state_reader=StatePort(state(c)),client=ClientPort(client(c)),mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(permit(c)),driver=d)
        self.assertEqual(l.get(c.action_id).status,'PENDING');self.assertEqual(d.call_count,0)
        with self.assertRaisesRegex(Exception,'UNRESOLVED_ACTIONS_BLOCK_ARM'):svc.arm(authority_generation=10)
        settled=svc.reconcile(c.action_id,evidence(c,135));self.assertEqual(settled.status,'SETTLED_SUCCESS')
        svc2=DefinitiveExecutionService(run_id='run-m11',run_generation=2,ledger=l,arbiter=HostInputArbiter(),state_reader=StatePort(state(c)),client=ClientPort(client(c)),mechanics=MechanicsPort(MechanicsResult('LEGAL')),coordination=CoordinationPort(permit(c)),driver=d)
        svc2.arm(authority_generation=11);self.assertTrue(svc2.armed);self.assertEqual(d.call_count,0)

    def test_build_pixel_and_loadout_generation_drift_after_prepare_are_not_sent(self):
        drifts=(
            {'observed_client_build':'other-build'},
            {'pixel_x':101},
            {'loadout_generation':10},
        )
        for i,changed in enumerate(drifts,1330):
            c=command(i);first=client(c);second=client(c,attestation_id=f'clientatt-context-drift-{i}',**changed)
            svc,l,d,_=self.make(c,clients=(first,second));o=svc.submit(c)
            self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(d.call_count,0);self.assertEqual(l.get(c.action_id).send_state,'NOT_SENT')

    def test_window_hwnd_and_geometry_drift_after_prepare_are_not_sent(self):
        for i,changed in enumerate(({'hwnd':31},{'geometry_proven':False}),136):
            c=command(i);first=client(c);second=client(c,attestation_id=f'clientatt-drift-{i}',**changed)
            svc,l,d,_=self.make(c,clients=(first,second));o=svc.submit(c);self.assertEqual(o.status,'REJECTED_NOT_SENT');self.assertEqual(d.call_count,0);self.assertEqual(l.get(c.action_id).send_state,'NOT_SENT')

    def test_ledger_tamper_is_detected(self):
        c=command(140);l=DefinitiveExecutionLedger(Path(self.temp.name)/'exec.sqlite3');l.prepare(c,2,9);self.assertEqual(len(l.audit()),1)
        with sqlite3.connect(l.path) as con:
            con.execute('DROP TRIGGER execution_events_no_update');con.execute("UPDATE events SET record_hash='tampered' WHERE seq=1")
        with self.assertRaises(DefinitiveExecutionLedgerError):l.audit()

    def test_split_pointer_transaction_rechecks_guard_and_releases_after_down(self):
        class Api:
            def __init__(self):self.events=[]
            def set_cursor(self,x,y):self.events.append(('move',x,y));return True
            def left_down(self):self.events.append(('down',));return True
            def left_up(self):self.events.append(('up',));return True
        api=Api();checks=iter((True,True,False));tx=PointerTransaction(api)
        r=tx.execute('action-m11-pointer',100,200,lambda:next(checks))
        self.assertEqual(r.delivery,'MAY_HAVE_SENT');self.assertEqual(r.detail,'GUARD_CHANGED_AFTER_MOUSE_DOWN')
        self.assertEqual(api.events,[('move',100,200),('down',),('up',)])

    def test_split_pointer_transaction_proven_pre_move_rejection_is_not_sent(self):
        class Api:
            def __init__(self):self.events=[]
            def set_cursor(self,x,y):self.events.append(('move',x,y));return True
            def left_down(self):self.events.append(('down',));return True
            def left_up(self):self.events.append(('up',));return True
        api=Api();r=PointerTransaction(api).execute('action-m11-pre',1,2,lambda:False)
        self.assertEqual((r.delivery,r.physical_input_count),('NOT_SENT',0));self.assertEqual(api.events,[])

    def test_split_pointer_transaction_success_is_three_external_operations(self):
        class Api:
            def __init__(self):self.events=[]
            def set_cursor(self,x,y):self.events.append(('move',x,y));return True
            def left_down(self):self.events.append(('down',));return True
            def left_up(self):self.events.append(('up',));return True
        api=Api();r=PointerTransaction(api).execute('action-m11-ok',3,4,lambda:True)
        self.assertEqual((r.delivery,r.physical_input_count),('SENT',3));self.assertEqual(api.events,[('move',3,4),('down',),('up',)])

    def test_ledger_immutable_action_projection_tamper_is_detected(self):
        c=command(141);l=DefinitiveExecutionLedger(Path(self.temp.name)/'immutable.sqlite3');l.prepare(c,2,9);self.assertEqual(len(l.audit()),1)
        with sqlite3.connect(l.path) as con:
            con.execute("UPDATE actions SET command_json=? WHERE action_id=?",(command(142).to_dict().__str__(),c.action_id))
        with self.assertRaises(DefinitiveExecutionLedgerError):l.audit()

    def test_windows_driver_is_disabled_without_explicit_scope(self):
        scope=WindowsActionScopeEnablement('actionscope-test','fixture-build',frozenset({'CAST'}),False)
        with self.assertRaisesRegex(WindowsInputDisabled,'DISABLED'):WindowsPointerInputDriver(scope)

if __name__=='__main__':unittest.main()
