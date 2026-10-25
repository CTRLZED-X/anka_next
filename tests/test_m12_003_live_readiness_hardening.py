from __future__ import annotations

import contextlib
import io
import re
import os
import tempfile
import unittest
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

from anka_app.cli import ROOT
from anka_app.configuration import load_user_config
from anka_app.ingress_readiness import _windows_sample
from anka_app.startup_acceptance import blockers_for, boundary_for
from anka_capture.windows_flows import TcpEndpoint
from anka_capture.windows_live import WindowsLiveCapture
from anka_client.win32_inventory import NativeWindowsInventory
from anka_contracts.client import WindowObservation, WindowScan
from anka_execution.drivers.windows_input import (
    PointerTransaction,
    WindowsActionScopeEnablement,
    WindowsInputDisabled,
    WindowsPointerInputDriver,
)
from anka_execution.service import DefinitiveExecutionService, ExecutionServiceRejected, _target_fingerprint
from anka_execution.definitive_ledger import DefinitiveExecutionLedger
from anka_contracts.action import ActionCommand
from anka_contracts.execution import ExecutionClientAttestation, ExecutionCoordinationPermit, ExecutionStateView, InputLease
from anka_contracts.mechanics import MechanicsResult
from anka_contracts.coordination import MemberPartyObservation, PartyRosterMember
from anka_contracts.workflow import MissionConfigSpec, WorkflowSignal
from anka_coordination.coordinator import PartyCoordinatorService
from anka_workflow.compiler import compile_mission
from anka_workflow.engine import MissionWorkflow
from anka_observability.api import LocalDiagnostics
from anka_canonical.writer import CanonicalWriter, ExactReleaseAdmissionPolicy, CanonicalWriterFenced
from anka_live_state.projector import StateProjector
from anka_protocol.sdk.runtime import ProtocolTransaction, TransactionResult
from anka_protocol.registry.registry import ProtocolRegistry
from anka_app.run_authority import RunAuthorityRejected, acquire_start_authority
from tests.test_m6_m7_canonical_state import ADAPTER as M6_ADAPTER, BUILD as M6_BUILD, fight_bootstrap

CFG = load_user_config(ROOT / 'config/user.json')


def win(pid=10, created=20, hwnd=None):
    return WindowObservation(hwnd or pid, pid, created, 'Dofus.exe', 'Dofus', 1280, 649, 96, False, True, None, '3.7.11.11')


class _InventorySequence:
    def __init__(self, scans):
        self.scans = list(scans)
        self.i = 0
    def scan(self):
        value = self.scans[min(self.i, len(self.scans)-1)]
        self.i += 1
        return value


class _Owner:
    def snapshot(self):
        return (TcpEndpoint('10.0.0.2', 50000, '203.0.113.5', 443, 10, 5),)


class _PointerApi:
    def __init__(self, *, down=True):
        self.down = down
        self.up_calls = 0
    def set_cursor(self, x, y): return True
    def left_down(self): return self.down
    def left_up(self):
        self.up_calls += 1
        return True


def _command(n=1):
    return ActionCommand(
        f'action-m12-003-{n}', 'run-m12-003', 'acct-cra', 'client-cra', 7, 11,
        f'{n:064x}'[-64:], 'END_TURN', 100, (('actor_id','41'),), ('TURN_OWNER_CHANGED',),
        basis_snapshot_id='snap-plan', party_id='party-main', basis_party_generation=3,
        basis_permit_generation=5, actor_id=41,
    )


def _state(c):
    return ExecutionStateView('snap-current','a'*64,c.account_id,c.client_instance_id,c.fight_epoch,c.turn_epoch,
        101,c.actor_id,c.actor_id,'HEALTHY',(('ap','KNOWN'),('actor_cell','KNOWN')),False)


def _client(c):
    return ExecutionClientAttestation('clientatt-good',c.account_id,c.client_instance_id,'fixture-build',10,20,30,4,6,8,9,
        100,200,True,True,True,True,True,True,True,_target_fingerprint(c),('client-evidence',))


def _permit(c):
    return ExecutionCoordinationPermit('party-main',c.account_id,c.fight_epoch,c.turn_epoch,3,5,True,'PERMIT_GRANTED',('permit-evidence',))


class _SinglePort:
    def __init__(self, value): self.value = value
    def current_for_action(self, _): return self.value
    def attest_for_action(self, _): return self.value
    def validate_action(self, *_): return self.value
    def permit_for_action(self, _): return self.value


class _Driver:
    mode='FAKE'
    def send(self, *_):
        raise AssertionError('driver must not be reached in arbiter acquire failure test')


class _AcquireFaultArbiter:
    def acquire(self, *_a, **_k): raise RuntimeError('host arbiter broke')
    def release(self, _): raise AssertionError('release without lease')


class _ReleaseFaultArbiter:
    def __init__(self): self.lease = None
    def acquire(self, action_id, account_id, *, now_ns=None):
        from anka_contracts.execution import InputLease
        self.lease = InputLease('lease-test',1,action_id,account_id,now_ns or 1)
        return self.lease
    def release(self, _lease): raise RuntimeError('release broke')


class _SentDriver:
    mode='FAKE'
    def send(self, command, client, lease, guard):
        from anka_contracts.execution import DriverSendReceipt
        if not guard(): return DriverSendReceipt(command.action_id,'NOT_SENT',0,'GUARD_REJECT')
        return DriverSendReceipt(command.action_id,'SENT',0,'FAKE_SENT')



class _BlockingSniffer:
    def __init__(self, stop_started, release_stop, **_kwargs):
        self.stop_started=stop_started;self.release_stop=release_stop
    def start(self): return None
    def stop(self):
        self.stop_started.set()
        if not self.release_stop.wait(timeout=2):raise RuntimeError('TEST_STOP_TIMEOUT')


class _Recorder:
    def __init__(self):self.close_calls=0;self.incomplete=0
    def mark_incomplete(self):self.incomplete+=1
    def close(self):
        self.close_calls+=1
        return {'status':'RECORDED_UNCERTIFIED'}


class _AuthorityBackend:
    def __init__(self):self.held=False;self.closed=0
    def acquire(self,_name):
        if self.held:raise RunAuthorityRejected('START_RUN_AUTHORITY_ALREADY_HELD')
        self.held=True;return object()
    def close(self,_handle):self.held=False;self.closed+=1

class TestM12003LiveReadinessHardening(unittest.TestCase):
    def test_pre_capture_process_generation_drift_blocks_before_sniffer(self):
        first=WindowScan(100,(win(10,20),win(11,21)))
        drift=WindowScan(101,(win(10,99),win(11,21)))
        inventory=_InventorySequence((first,drift))
        with patch('anka_client.win32_inventory.NativeWindowsInventory', return_value=inventory), \
             patch('anka_capture.windows_flows.WindowsTcpOwnership', return_value=_Owner()), \
             patch('anka_capture.windows_live.capture_bounded_sample') as capture:
            with self.assertRaisesRegex(RuntimeError,'PROCESS_GENERATION_CHANGED_BEFORE_CAPTURE'):
                _windows_sample(CFG)
            capture.assert_not_called()

    def test_pre_capture_drift_maps_to_client_owned_blocker(self):
        host={'platform':'WINDOWS','candidate_windows':2,'issues':[],
              'capture':{'scapy_installed':True,'npcap_driver':'DETECTED_UNVERIFIED','server_port_candidates':1,
                         'interface_resolution':'RESOLVED'}}
        ingress={'status':'FAILED','error_code':'PROCESS_GENERATION_CHANGED_BEFORE_CAPTURE','capture_attempted':True}
        codes=blockers_for(host,ingress)
        self.assertIn('START_CLIENT_PROCESS_GENERATION_DRIFT',codes)
        self.assertEqual(boundary_for('START_CLIENT_PROCESS_GENERATION_DRIFT'),'client.host_observation')

    def test_enabled_windows_action_scope_requires_evidence_binding(self):
        with self.assertRaisesRegex(ValueError,'WINDOWS_ACTION_SCOPE_EVIDENCE_HASHES_REQUIRED'):
            WindowsActionScopeEnablement('actionscope-test','3.7.11.11',frozenset({'END_TURN'}),True)

    def test_windows_driver_rejects_release_config_or_run_mismatch(self):
        h1='1'*64;h2='2'*64;h3='3'*64
        scope=WindowsActionScopeEnablement('actionscope-test','3.7.11.11',frozenset({'END_TURN'}),True,h1,h2,h3,'run-test',9)
        with patch('anka_execution.drivers.windows_input.os.name','nt'), \
             patch('anka_execution.drivers.windows_input._CtypesPointerApi', return_value=_PointerApi()):
            with self.assertRaisesRegex(WindowsInputDisabled,'WINDOWS_INPUT_SCOPE_EVIDENCE_MISMATCH'):
                WindowsPointerInputDriver(scope,current_release_manifest_sha256='4'*64,current_config_sha256=h2,
                                          current_acceptance_receipt_sha256=h3,current_run_id='run-test',current_run_generation=9)
            with self.assertRaisesRegex(WindowsInputDisabled,'WINDOWS_INPUT_SCOPE_RUN_MISMATCH'):
                WindowsPointerInputDriver(scope,current_release_manifest_sha256=h1,current_config_sha256=h2,
                                          current_acceptance_receipt_sha256=h3,current_run_id='run-other',current_run_generation=9)
            with self.assertRaisesRegex(WindowsInputDisabled,'WINDOWS_INPUT_SCOPE_EVIDENCE_MISMATCH'):
                WindowsPointerInputDriver(scope,current_release_manifest_sha256=h1,current_config_sha256=h2,
                                          current_acceptance_receipt_sha256='4'*64,current_run_id='run-test',current_run_generation=9)
            driver=WindowsPointerInputDriver(scope,current_release_manifest_sha256=h1,current_config_sha256=h2,
                                             current_acceptance_receipt_sha256=h3,current_run_id='run-test',current_run_generation=9)
            self.assertEqual(driver.enablement.acceptance_receipt_sha256,h3)

    def test_windows_driver_revalidates_final_lease_client_proofs_and_target(self):
        h1='1'*64;h2='2'*64;h3='3'*64;c=_command(88);good_client=_client(c)
        scope=WindowsActionScopeEnablement('actionscope-test','fixture-build',frozenset({'END_TURN'}),True,h1,h2,h3,'run-m12-003',9)
        with patch('anka_execution.drivers.windows_input.os.name','nt'), \
             patch('anka_execution.drivers.windows_input._CtypesPointerApi', return_value=_PointerApi()):
            driver=WindowsPointerInputDriver(scope,current_release_manifest_sha256=h1,current_config_sha256=h2,
                                             current_acceptance_receipt_sha256=h3,current_run_id='run-m12-003',current_run_generation=9)
            wrong_lease=InputLease('lease-wrong',1,'action-other','acct-cra',1)
            with self.assertRaisesRegex(WindowsInputDisabled,'INPUT_LEASE_MISMATCH'):
                driver.send(c,good_client,wrong_lease,lambda:True)
            lease=InputLease('lease-good',1,c.action_id,c.account_id,1)
            bad_scope=ExecutionClientAttestation('clientatt-badscope','acct-other',c.client_instance_id,'fixture-build',10,20,30,4,6,8,9,
                100,200,True,True,True,True,True,True,True,_target_fingerprint(c),('client-evidence',))
            with self.assertRaisesRegex(WindowsInputDisabled,'CLIENT_MISMATCH'):
                driver.send(c,bad_scope,lease,lambda:True)
            bad_proof=ExecutionClientAttestation('clientatt-badproof',c.account_id,c.client_instance_id,'fixture-build',10,20,30,4,6,8,9,
                100,200,True,True,False,True,True,True,True,_target_fingerprint(c),('client-evidence',))
            with self.assertRaisesRegex(WindowsInputDisabled,'CLIENT_PROOFS_MISSING'):
                driver.send(c,bad_proof,lease,lambda:True)
            bad_target=ExecutionClientAttestation('clientatt-badtarget',c.account_id,c.client_instance_id,'fixture-build',10,20,30,4,6,8,9,
                100,200,True,True,True,True,True,True,True,'f'*64,('client-evidence',))
            with self.assertRaisesRegex(WindowsInputDisabled,'TARGET_MISMATCH'):
                driver.send(c,bad_target,lease,lambda:True)

    def test_pointer_ambiguous_down_best_effort_releases_button(self):
        api=_PointerApi(down=False)
        r=PointerTransaction(api).execute('action-test',10,20,lambda:True)
        self.assertEqual(r.delivery,'MAY_HAVE_SENT')
        self.assertEqual(r.detail,'LEFT_DOWN_DELIVERY_AMBIGUOUS')
        self.assertEqual(api.up_calls,1)

    def _service(self, td, c, arbiter, driver):
        return DefinitiveExecutionService(
            run_id='run-m12-003',run_generation=2,
            ledger=DefinitiveExecutionLedger(Path(td)/'exec.sqlite3'),arbiter=arbiter,
            state_reader=_SinglePort(_state(c)),client=_SinglePort(_client(c)),
            mechanics=_SinglePort(MechanicsResult('LEGAL')),coordination=_SinglePort(_permit(c)),
            driver=driver,clock_ns=lambda:50)

    def test_arbiter_acquire_fault_disarms_and_requires_new_service(self):
        c=_command(1)
        with tempfile.TemporaryDirectory() as td:
            svc=self._service(td,c,_AcquireFaultArbiter(),_Driver());svc.arm(authority_generation=9)
            out=svc.submit(c)
            self.assertEqual(out.status,'REJECTED_NOT_SENT')
            self.assertTrue(out.reason.startswith('INPUT_ARBITER_ACQUIRE_FAILED:'))
            self.assertFalse(svc.armed);self.assertIsNotNone(svc.last_safety_fault)
            with self.assertRaisesRegex(ExecutionServiceRejected,'SAFETY_FAULT_REQUIRES_NEW_SERVICE_INSTANCE'):
                svc.arm(authority_generation=10)

    def test_arbiter_release_fault_preserves_outcome_but_disarms_future_input(self):
        c=_command(2)
        with tempfile.TemporaryDirectory() as td:
            svc=self._service(td,c,_ReleaseFaultArbiter(),_SentDriver());svc.arm(authority_generation=9)
            out=svc.submit(c)
            self.assertEqual(out.status,'PENDING')
            self.assertFalse(svc.armed)
            self.assertEqual(svc.last_safety_fault,'INPUT_ARBITER_RELEASE_FAILED:RuntimeError')
            with self.assertRaisesRegex(ExecutionServiceRejected,'SAFETY_FAULT_REQUIRES_NEW_SERVICE_INSTANCE'):
                svc.arm(authority_generation=10)

    def test_keyboard_interrupt_is_clean_exit_130_with_interrupted_evidence(self):
        import anka_app.cli as cli
        with tempfile.TemporaryDirectory() as td:
            real = LocalDiagnostics(Path(td))
            with patch.object(cli,'LocalDiagnostics',return_value=real), patch.object(cli,'_command',side_effect=KeyboardInterrupt):
                output=io.StringIO()
                with contextlib.redirect_stdout(output):
                    code=cli.main(['start'])
            text=output.getvalue()
            self.assertEqual(code,130)
            self.assertIn('ANKA_STATUS=INTERRUPTED',text)
            self.assertIn('ANKA_FAILURE=USER_INTERRUPTED',text)
            import json
            manifest=json.loads((real.folder/'run_state.json').read_text())
            self.assertEqual(manifest['state'],'INTERRUPTED')

    def test_observe_only_start_source_explicitly_marks_not_sent(self):
        source=(ROOT/'src/anka_app/cli.py').read_text(encoding='utf-8')
        for event in ('start.static_preflight_passed','client.windows_candidate_accepted',
                      'capture.ingress_evidence_collected','protocol.current_build_observation_completed',
                      'start.observe_only_blocked'):
            pos=source.index("'"+event+"'")
            fragment=source[pos:pos+800]
            self.assertIn("physical_input_state='NOT_SENT'",fragment,event)

    def test_win32_inspect_rejects_hwnd_pid_change_and_closes_process_handle(self):
        import ctypes
        from ctypes import wintypes as wt
        inv=NativeWindowsInventory.__new__(NativeWindowsInventory)
        inv.c=ctypes;inv.wt=wt;inv.get_dpi=lambda _hwnd:96;inv._product_version=lambda _p:'3.7.11.11'
        class User:
            def __init__(self):self.pid_calls=0
            def GetWindowThreadProcessId(self,hwnd,p):
                self.pid_calls+=1;p._obj.value=10 if self.pid_calls==1 else 11;return 1
            def GetClientRect(self,hwnd,p):
                p._obj.left=0;p._obj.top=0;p._obj.right=1280;p._obj.bottom=649;return 1
            def IsIconic(self,hwnd):return 0
            def GetForegroundWindow(self):return hwnd_value
        class Kernel:
            def __init__(self):self.closed=0
            def OpenProcess(self,*_):return 123
            def QueryFullProcessImageNameW(self,h,flags,buf,length):buf.value='C:/Dofus.exe';return 1
            def GetProcessTimes(self,h,created,exit_,kernel,user):
                created._obj.dwHighDateTime=0;created._obj.dwLowDateTime=20;return 1
            def CloseHandle(self,h):self.closed+=1;return 1
        hwnd_value=99;inv.user=User();inv.kernel=Kernel()
        with self.assertRaisesRegex(OSError,'WINDOW_PROCESS_CHANGED_DURING_INSPECTION'):
            inv._inspect(hwnd_value,'Dofus')
        self.assertEqual(inv.kernel.closed,1)


    def test_coordination_public_mutation_is_serialized_across_threads(self):
        roster=(PartyRosterMember('acct-cra','client-cra',41,'leader'),
                PartyRosterMember('acct-enu','client-enu',42,'follower'))
        service=PartyCoordinatorService('party-thread',roster)
        original=service._observe_unlocked
        guard=threading.Lock();active=0;peak=0
        def wrapped(self, observation):
            nonlocal active,peak
            with guard:
                active+=1;peak=max(peak,active)
            try:
                time.sleep(0.005)
                return original(observation)
            finally:
                with guard:active-=1
        service._observe_unlocked=types.MethodType(wrapped,service)
        observations=[]
        for i in range(12):
            account='acct-cra' if i%2==0 else 'acct-enu';actor=41 if account=='acct-cra' else 42
            observations.append(MemberPartyObservation(f'coordobs-thread-{i}',account,
                'client-cra' if account=='acct-cra' else 'client-enu',actor,i+1,i+1,1,1,'fight-thread',190580738,
                'FIGHT_ACTIVE',41,True,True,True,'HEALTHY',(f'ev-thread-{i}',),False))
        threads=[threading.Thread(target=service.observe,args=(o,)) for o in observations]
        for t in threads:t.start()
        for t in threads:t.join(timeout=2)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(peak,1)

    def test_workflow_transition_application_is_serialized_across_threads(self):
        spec=MissionConfigSpec('sufokia_direction_cycle',1,8,2,3,False,True,'a'*64)
        plan=compile_mission(spec,ROOT/'assets/workflow/routes.json',watchdog_budget_ticks=10,recovery_budget=1)
        workflow=MissionWorkflow('run-thread-workflow',plan)
        original=workflow._apply_unlocked
        guard=threading.Lock();active=0;peak=0
        def wrapped(self, signal):
            nonlocal active,peak
            with guard:
                active+=1;peak=max(peak,active)
            try:
                time.sleep(0.005)
                return original(signal)
            finally:
                with guard:active-=1
        workflow._apply_unlocked=types.MethodType(wrapped,workflow)
        # Multiple competing START signals are intentionally concurrent: exactly
        # one may advance CREATED->PREFLIGHT; the others are safely serialized/rejected.
        signals=[WorkflowSignal(f'wfsig-thread-{i}','START',i,(f'ev-{i}',)) for i in range(10)]
        results=[];rlock=threading.Lock()
        def run(sig):
            r=workflow.apply(sig)
            with rlock:results.append(r)
        threads=[threading.Thread(target=run,args=(sig,)) for sig in signals]
        for t in threads:t.start()
        for t in threads:t.join(timeout=2)
        self.assertTrue(all(not t.is_alive() for t in threads))
        self.assertEqual(peak,1)
        self.assertEqual(sum(r.status=='APPLIED' for r in results),1)
        self.assertEqual(workflow.snapshot().phase,'PREFLIGHT')


    def test_canonical_single_connection_serializes_concurrent_callers(self):
        with tempfile.TemporaryDirectory() as td:
            writer=CanonicalWriter(Path(td)/'canonical.sqlite',projector=StateProjector(),
                admission_policy=ExactReleaseAdmissionPolicy(((M6_ADAPTER,M6_BUILD),)))
            try:
                results=[];errors=[];lock=threading.Lock();barrier=threading.Barrier(8)
                def run():
                    try:
                        barrier.wait(timeout=2)
                        result=writer.commit_candidate_batch(fight_bootstrap())
                        with lock:results.append(result.status)
                    except Exception as exc:
                        with lock:errors.append(exc)
                threads=[threading.Thread(target=run) for _ in range(8)]
                for t in threads:t.start()
                for t in threads:t.join(timeout=3)
                self.assertTrue(all(not t.is_alive() for t in threads))
                self.assertFalse(errors,errors)
                self.assertEqual(results.count('COMMITTED'),1)
                self.assertEqual(results.count('IDEMPOTENT_DUPLICATE'),7)
                self.assertEqual(writer.audit()['events'],4)
            finally:writer.close()

    def test_canonical_close_is_idempotent_and_post_close_is_fenced(self):
        with tempfile.TemporaryDirectory() as td:
            writer=CanonicalWriter(Path(td)/'canonical.sqlite',projector=StateProjector(),
                admission_policy=ExactReleaseAdmissionPolicy(((M6_ADAPTER,M6_BUILD),)))
            writer.close();writer.close()
            with self.assertRaisesRegex(CanonicalWriterFenced,'CANONICAL_WRITER_CLOSED'):
                writer.current_cursor()

    def test_capture_concurrent_stop_waits_for_single_quiesce_before_evidence_seal(self):
        stop_started=threading.Event();release_stop=threading.Event();rec=_Recorder()
        def factory(**kwargs):return _BlockingSniffer(stop_started,release_stop,**kwargs)
        live=WindowsLiveCapture(interface=None,server_ports=(443,),sniffer_factory=factory,
                                require_windows=False,evidence_recorder=rec)
        live.start()
        first=threading.Thread(target=live.stop);second=threading.Thread(target=live.stop)
        first.start();self.assertTrue(stop_started.wait(timeout=1));second.start()
        time.sleep(.03)
        self.assertTrue(second.is_alive(),'second stop must wait for real sniffer shutdown')
        self.assertEqual(rec.close_calls,0,'evidence must not seal while callback source can still run')
        release_stop.set();first.join(timeout=2);second.join(timeout=2)
        self.assertFalse(first.is_alive());self.assertFalse(second.is_alive())
        self.assertEqual(rec.close_calls,1)

    def test_capture_hung_backend_stop_is_bounded_and_does_not_seal_evidence(self):
        stop_started=threading.Event();never_release=threading.Event();rec=_Recorder()
        def factory(**kwargs):return _BlockingSniffer(stop_started,never_release,**kwargs)
        live=WindowsLiveCapture(interface=None,server_ports=(443,),sniffer_factory=factory,
                                require_windows=False,evidence_recorder=rec,lifecycle_timeout_seconds=.05)
        live.start()
        started=time.monotonic()
        with self.assertRaisesRegex(RuntimeError,'LIVE_CAPTURE_STOP_TIMEOUT'):
            live.stop()
        self.assertLess(time.monotonic()-started,.5)
        self.assertTrue(stop_started.is_set())
        self.assertEqual(rec.close_calls,0,'unproven quiescence must never seal raw evidence')
        self.assertGreaterEqual(rec.incomplete,1)
        # The timeout is sticky for this capture generation; later cleanup cannot
        # silently reinterpret the same source as successfully quiesced.
        with self.assertRaisesRegex(RuntimeError,'LIVE_CAPTURE_STOP_TIMEOUT'):
            live.stop()
        self.assertEqual(rec.close_calls,0)

    def test_protocol_transaction_process_is_serialized_per_connection_context(self):
        tx=ProtocolTransaction(None,None)
        guard=threading.Lock();active=0;peak=0
        def fake(_envelope):
            nonlocal active,peak
            with guard:active+=1;peak=max(peak,active)
            try:
                time.sleep(.004)
                return TransactionResult('TEST',None,None,False)
            finally:
                with guard:active-=1
        tx._process_unlocked=fake
        threads=[threading.Thread(target=tx.process,args=(object(),)) for _ in range(10)]
        for t in threads:t.start()
        for t in threads:t.join(timeout=2)
        self.assertTrue(all(not t.is_alive() for t in threads));self.assertEqual(peak,1)

    def test_protocol_registry_public_read_honors_registry_serialization_lock(self):
        registry=ProtocolRegistry();entered=threading.Event();finished=threading.Event()
        registry._lock.acquire()
        def read():
            entered.set();registry.releases();finished.set()
        t=threading.Thread(target=read);t.start();self.assertTrue(entered.wait(timeout=1))
        time.sleep(.02);self.assertFalse(finished.is_set())
        registry._lock.release();t.join(timeout=2)
        self.assertTrue(finished.is_set())

    def test_run_authority_lease_is_exclusive_and_idempotently_released(self):
        backend=_AuthorityBackend();first=acquire_start_authority(backend=backend,require_windows=False)
        with self.assertRaisesRegex(RunAuthorityRejected,'START_RUN_AUTHORITY_ALREADY_HELD'):
            acquire_start_authority(backend=backend,require_windows=False)
        first.close();first.close();self.assertEqual(backend.closed,1)
        second=acquire_start_authority(backend=backend,require_windows=False);second.close()
        self.assertEqual(backend.closed,2)

    def test_second_start_authority_failure_blocks_before_command_body(self):
        import anka_app.cli as cli
        with tempfile.TemporaryDirectory() as td:
            diag=LocalDiagnostics(Path(td))
            with patch.object(cli,'LocalDiagnostics',return_value=diag), \
                 patch('anka_app.run_authority.acquire_start_authority',side_effect=RunAuthorityRejected('START_RUN_AUTHORITY_ALREADY_HELD')), \
                 patch.object(cli,'_command') as command:
                output=io.StringIO()
                with contextlib.redirect_stdout(output):code=cli.main(['start'])
            self.assertEqual(code,40);command.assert_not_called()
            self.assertIn('ANKA_FAILURE=START_RUN_AUTHORITY_ALREADY_HELD',output.getvalue())

    def test_start_revalidation_rejects_config_change(self):
        import anka_app.cli as cli
        a=types.SimpleNamespace(sha256='a'*64);b=types.SimpleNamespace(sha256='b'*64)
        with patch.object(cli,'load_user_config',return_value=b), \
             patch.object(cli,'_release_integrity_check',return_value={'manifest_sha256':'c'*64}):
            with self.assertRaisesRegex(RuntimeError,'START_CONFIG_CHANGED_DURING_OBSERVATION'):
                cli._revalidate_start_identity(object(),a,{'manifest_sha256':'c'*64})

    def test_start_revalidation_rejects_release_change(self):
        import anka_app.cli as cli
        a=types.SimpleNamespace(sha256='a'*64)
        with patch.object(cli,'load_user_config',return_value=a), \
             patch.object(cli,'_release_integrity_check',return_value={'manifest_sha256':'d'*64}):
            with self.assertRaisesRegex(RuntimeError,'START_RELEASE_CHANGED_DURING_OBSERVATION'):
                cli._revalidate_start_identity(object(),a,{'manifest_sha256':'c'*64})

    def test_version_is_not_older_than_m12_003(self):
        text=(ROOT/'PROJECT_INFO.txt').read_text()
        m=re.search(r'^PROJECT_VERSION=ANKA_NEXT_M12_(\d{3})$',text,re.MULTILINE)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)),3)


if __name__=='__main__':unittest.main()
