"""P18 system tests: synthetic only; no physical output is ever allowed."""
from __future__ import annotations
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
from unittest.mock import patch
from anka_contracts.execution_flow import OfflineActionIntent,OfflineOutcomeEvidence,OfflineActionAudit
from anka_execution.ledger import OfflineExecutionLedger,ExecutionLedgerRejected,ExecutionLedgerIntegrityError
from anka_execution.settlement import next_status,ExecutionTransitionRejected
from anka_app.execution_offline import fixture_intent,fixture_evidence,execution_demo,execution_audit


class TestContract(unittest.TestCase):
    def test_fixture_non_executable(self):
        i=fixture_intent(); e=fixture_evidence(i)
        self.assertFalse(i.physical_input_permitted);self.assertFalse(i.actionable)
        self.assertFalse(e.authoritative);self.assertFalse(e.physical_input_permitted)

    def test_forbid_forged_intent(self):
        i=fixture_intent()
        for kw in ({'synthetic_only':False},{'actionable':True},{'physical_input_permitted':True}):
            with self.assertRaisesRegex(ValueError,'P18_AUTHORITY_FORGERY'):
                replace(i,**kw)

    def test_forbid_forged_outcome(self):
        e=fixture_evidence(fixture_intent())
        for kw in ({'synthetic_only':False},{'authoritative':True},{'physical_input_permitted':True}):
            with self.assertRaisesRegex(ValueError,'P18_OUTCOME_AUTHORITY_FORGERY'):
                replace(e,**kw)

    def test_forbid_forged_report(self):
        a=OfflineActionAudit('action','PREPARED','PREPARED_NO_DISPATCH',1,())
        for kw in ({'synthetic_only':False},{'actionable':True},{'physical_input_permitted':True}):
            with self.assertRaisesRegex(ValueError,'P18_REPORT_AUTHORITY_FORGERY'):
                replace(a,**kw)

    def test_strict_boolean_numeric_rejection(self):
        i=fixture_intent()
        for kw in ({'window_generation':True},{'state_revision':True},{'actor_id':True},{'target_cell':True},
                   {'window_generation':0},{'state_revision':-1},{'kind':'UNSUPPORTED'},{'action_key':'not valid'}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):replace(i,**kw)

    def test_evidence_bad_scope_types(self):
        e=fixture_evidence(fixture_intent())
        for kw in ({'observed_revision':False},{'window_generation':True},{'account_id':'not good'},
                   {'outcome':'UNPROVEN'},{'actor_id':0}):
            with self.subTest(kw=kw),self.assertRaises(ValueError):replace(e,**kw)

    def test_pure_transition_table(self):
        self.assertEqual(next_status(None,'PREPARED'),'PREPARED')
        self.assertEqual(next_status('PREPARED','DISPATCH_BOUNDARY_COMMITTED'),'DISPATCH_UNCERTAIN')
        self.assertEqual(next_status('DISPATCH_UNCERTAIN','OUTCOME_INCONCLUSIVE'),'DISPATCH_UNCERTAIN')
        self.assertEqual(next_status('DISPATCH_UNCERTAIN','OUTCOME_ACCEPTED'),'CONFIRMED')
        for st,ev in [('PREPARED','OUTCOME_ACCEPTED'),('CONFIRMED','DISPATCH_BOUNDARY_COMMITTED'),
                      ('DISPATCH_UNCERTAIN','CANCELLED_BEFORE_DISPATCH'),('REJECTED','OUTCOME_ACCEPTED')]:
            with self.assertRaises(ExecutionTransitionRejected):next_status(st,ev)


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='anka-p18-tests-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'db.sqlite3'
        self.ledger=OfflineExecutionLedger(self.path)
        self.intent=fixture_intent()

    def _prepare_dispatch(self):
        self.ledger.prepare(self.intent)
        return self.ledger.mark_dispatch_boundary(self.intent.action_id)

    def test_prepare_has_no_send(self):
        a=self.ledger.prepare(self.intent)
        self.assertEqual((a.status,a.event_count),('PREPARED',1))
        self.assertFalse(a.to_dict()['physical_input_permitted'])

    def test_reopen_preserves_uncertainty(self):
        self._prepare_dispatch()
        reopened=OfflineExecutionLedger(self.path)
        self.assertEqual(reopened.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')
        with self.assertRaises(ExecutionTransitionRejected):reopened.mark_dispatch_boundary(self.intent.action_id)

    def test_only_fixture_evidence_can_settle(self):
        self._prepare_dispatch()
        a=self.ledger.record_outcome(fixture_evidence(self.intent))
        self.assertEqual(a.status,'CONFIRMED');self.assertEqual(a.evidence_ids,('p18-fixture-evidence-1',))
        self.assertTrue(a.synthetic_only);self.assertFalse(a.actionable)

    def test_server_reject_fixture_is_not_success(self):
        self._prepare_dispatch()
        a=self.ledger.record_outcome(fixture_evidence(self.intent,'REJECTED'))
        self.assertEqual(a.status,'REJECTED')

    def test_inconclusive_stays_uncertain(self):
        self._prepare_dispatch()
        self.ledger.record_outcome(fixture_evidence(self.intent,'INCONCLUSIVE'))
        self.assertEqual(self.ledger.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')
        with self.assertRaises(ExecutionTransitionRejected):self.ledger.mark_dispatch_boundary(self.intent.action_id)
        self.assertEqual(self.ledger.record_outcome(fixture_evidence(self.intent,'ACCEPTED',evidence_id='another-proof')).status,'CONFIRMED')

    def test_no_confirmation_before_dispatch(self):
        self.ledger.prepare(self.intent)
        with self.assertRaises(ExecutionTransitionRejected):self.ledger.record_outcome(fixture_evidence(self.intent))
        self.assertEqual(self.ledger.audit(self.intent.action_id).event_count,1)

    def test_cancel_only_before_dispatch(self):
        self.ledger.prepare(self.intent)
        self.assertEqual(self.ledger.cancel_before_dispatch(self.intent.action_id).status,'CANCELLED')
        with self.assertRaises(ExecutionTransitionRejected):self.ledger.mark_dispatch_boundary(self.intent.action_id)

    def test_cannot_cancel_uncertain_send(self):
        self._prepare_dispatch()
        with self.assertRaises(ExecutionTransitionRejected):self.ledger.cancel_before_dispatch(self.intent.action_id)

    def test_exact_duplicate_id_never_reruns(self):
        self.ledger.prepare(self.intent)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'DUPLICATE_ACTION_ID'):
            self.ledger.prepare(self.intent)
        self.assertEqual(self.ledger.audit(self.intent.action_id).event_count,1)

    def test_logical_action_key_dedup_survives_settlement(self):
        self._prepare_dispatch(); self.ledger.record_outcome(fixture_evidence(self.intent))
        with self.assertRaisesRegex(ExecutionLedgerRejected,'DUPLICATE_LOGICAL_ACTION'):
            self.ledger.prepare(replace(self.intent,action_id='p18-another-id'))

    def test_same_client_conflicting_pending(self):
        self.ledger.prepare(self.intent)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'CLIENT_HAS_PENDING'):
            self.ledger.prepare(replace(self.intent,action_id='new-id',action_key='next-cast'))

    def test_global_single_dispatch(self):
        self._prepare_dispatch()
        other=replace(self.intent,action_id='enu-action',account_id='enu',client_id='window-2',
                      window_generation=2,actor_id=888,action_key='enu-action-key')
        self.ledger.prepare(other)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'GLOBAL_DISPATCH_BUSY'):
            self.ledger.mark_dispatch_boundary(other.action_id)
        self.assertEqual(self.ledger.audit(other.action_id).status,'PREPARED')
        self.ledger.record_outcome(fixture_evidence(self.intent))
        self.assertEqual(self.ledger.mark_dispatch_boundary(other.action_id).status,'DISPATCH_UNCERTAIN')

    def test_outcome_strict_scope(self):
        self._prepare_dispatch()
        e=fixture_evidence(self.intent)
        for field,new in [('account_id','enu'),('client_id','wrong'),('turn_id','other'),
                          ('fight_id','other'),('session_id','other'),('actor_id',888),('window_generation',2),('action_id','other')]:
            with self.subTest(field=field), self.assertRaises(ExecutionLedgerRejected):
                self.ledger.record_outcome(replace(e,**{field:new}))
        self.assertEqual(self.ledger.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')

    def test_stale_confirmation_rejected(self):
        self._prepare_dispatch()
        with self.assertRaisesRegex(ExecutionLedgerRejected,'STALE_OUTCOME'):
            self.ledger.record_outcome(replace(fixture_evidence(self.intent),observed_revision=7))

    def test_duplicate_evidence_not_committed(self):
        self._prepare_dispatch()
        e=fixture_evidence(self.intent,'INCONCLUSIVE')
        self.ledger.record_outcome(e)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'DUPLICATE_EVIDENCE'):
            self.ledger.record_outcome(e)
        self.assertEqual(self.ledger.audit(self.intent.action_id).event_count,3)

    def test_no_second_outcome_after_terminal(self):
        self._prepare_dispatch();self.ledger.record_outcome(fixture_evidence(self.intent))
        with self.assertRaises(ExecutionTransitionRejected):
            self.ledger.record_outcome(fixture_evidence(self.intent,'REJECTED',evidence_id='second-evidence'))

    def test_unknown_action_rejected(self):
        with self.assertRaisesRegex(ExecutionLedgerRejected,'UNKNOWN_ACTION'):
            self.ledger.mark_dispatch_boundary('missing')
        with self.assertRaisesRegex(ExecutionLedgerRejected,'UNKNOWN_ACTION'):
            self.ledger.audit('missing')

    def test_fault_injected_prepare_rolls_back(self):
        def boom(stage):
            if stage=='after_prepare_event_before_commit':raise RuntimeError('INJECTED_FAILURE')
        faulty=OfflineExecutionLedger(self.path,fault_hook=boom)
        with self.assertRaises(RuntimeError):faulty.prepare(self.intent)
        self.assertEqual(self.ledger.audit_all(),())

    def test_fault_injected_dispatch_rolls_back_both(self):
        self.ledger.prepare(self.intent)
        for breakpoint in ('after_event_before_status','after_status_before_commit'):
            def boom(stage):
                if stage==breakpoint:raise RuntimeError('INJECTED_FAILURE')
            with self.subTest(breakpoint=breakpoint):
                faulty=OfflineExecutionLedger(self.path,fault_hook=boom)
                with self.assertRaises(RuntimeError):faulty.mark_dispatch_boundary(self.intent.action_id)
                self.assertEqual(self.ledger.audit(self.intent.action_id).status,'PREPARED')
                self.assertEqual(self.ledger.audit(self.intent.action_id).event_count,1)

    def test_fault_injected_outcome_rolls_back_all(self):
        self._prepare_dispatch()
        for breakpoint in ('after_outcome_event_before_status','after_outcome_status_before_commit'):
            def boom(stage):
                if stage==breakpoint:raise RuntimeError('INJECTED_FAILURE')
            with self.subTest(breakpoint=breakpoint):
                faulty=OfflineExecutionLedger(self.path,fault_hook=boom)
                with self.assertRaises(RuntimeError):faulty.record_outcome(fixture_evidence(self.intent))
                self.assertEqual(self.ledger.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')
                self.assertEqual(self.ledger.audit(self.intent.action_id).event_count,2)

    def test_event_hash_corruption_detected(self):
        self._prepare_dispatch()
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TRIGGER forbid_event_update')
            con.execute("UPDATE action_events SET record_hash='tampered' WHERE sequence=1")
        with self.assertRaisesRegex(ExecutionLedgerIntegrityError,'CHAIN_CORRUPTED'):
            self.ledger.audit_all()

    def test_projection_tampering_detected(self):
        self.ledger.prepare(self.intent)
        with sqlite3.connect(self.path) as con:
            con.execute("UPDATE action_intents SET status='CONFIRMED'")
        with self.assertRaisesRegex(ExecutionLedgerIntegrityError,'PROJECTION_MISMATCH'):
            self.ledger.audit_all()

    def test_evidence_table_tampering_detected(self):
        self._prepare_dispatch();self.ledger.record_outcome(fixture_evidence(self.intent))
        with sqlite3.connect(self.path) as con:
            con.execute('DELETE FROM observed_evidence')
        with self.assertRaisesRegex(ExecutionLedgerIntegrityError,'EVIDENCE_TABLE_MISMATCH'):
            self.ledger.audit_all()

    def test_read_only_audit_does_not_modify_db(self):
        self._prepare_dispatch()
        before=self.path.read_bytes()
        audit=OfflineExecutionLedger(self.path,read_only=True)
        self.assertEqual(audit.audit(self.intent.action_id).status,'DISPATCH_UNCERTAIN')
        self.assertEqual(self.path.read_bytes(),before)
        with self.assertRaisesRegex(ExecutionLedgerRejected,'AUDIT_READ_ONLY'):
            audit.mark_dispatch_boundary(self.intent.action_id)

    def test_missing_read_only_db_rejected_and_not_created(self):
        missing=Path(self.temp.name)/'missing.sqlite3'
        with self.assertRaisesRegex(ExecutionLedgerRejected,'NOT_FOUND'):
            OfflineExecutionLedger(missing,read_only=True)
        self.assertFalse(missing.exists())

    def test_two_concurrent_dispatches_only_one_wins(self):
        a=replace(self.intent,action_id='cra-d',action_key='cra-key')
        b=replace(self.intent,action_id='enu-d',action_key='enu-key',client_id='window-2',account_id='enu',actor_id=888)
        self.ledger.prepare(a);self.ledger.prepare(b)
        def attempt(action):
            try:return self.ledger.mark_dispatch_boundary(action).status
            except ExecutionLedgerRejected:return 'BLOCKED'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,(a.action_id,b.action_id)))
        self.assertEqual(sorted(results),['BLOCKED','DISPATCH_UNCERTAIN'])
        self.assertEqual(sorted(r.status for r in self.ledger.audit_all()),['DISPATCH_UNCERTAIN','PREPARED'])

    def test_global_journal_sequence_gap_rejected(self):
        self._prepare_dispatch()
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TRIGGER forbid_event_delete')
            con.execute('DELETE FROM action_events WHERE sequence=1')
        with self.assertRaises(ExecutionLedgerIntegrityError):self.ledger.audit_all()

    def test_unknown_payload_or_authority_fails_audit(self):
        self._prepare_dispatch()
        with sqlite3.connect(self.path) as con:
            con.execute('DROP TRIGGER forbid_event_update')
            con.execute("UPDATE action_events SET payload='not-json' WHERE sequence=1")
        with self.assertRaises(ExecutionLedgerIntegrityError):self.ledger.audit_all()


class AppIntegration(unittest.TestCase):
    def test_happy_is_not_authority(self):
        result=execution_demo(scenario='accepted-fixture')
        self.assertEqual((result['status'],result['action']['status']),('RESEARCH_ONLY','CONFIRMED'))
        self.assertFalse(result['physical_input_sent'])

    def test_uncertain_diagnostics(self):
        result=execution_demo(scenario='uncertain-crash')
        self.assertEqual(result['status'],'BLOCKED_UNCERTAIN')
        self.assertEqual(result['action']['reason'],'UNCERTAIN_SEND_NO_AUTO_RETRY')

    def test_wrong_evidence_is_quarantined(self):
        result=execution_demo(scenario='wrong-evidence')
        self.assertEqual(result['rejection_code'],'P18_OUTCOME_SCOPE_MISMATCH')
        self.assertEqual(result['status'],'BLOCKED_UNCERTAIN')

    def test_duplicate_dispatch_is_rejected(self):
        result=execution_demo(scenario='duplicate-dispatch')
        self.assertEqual(result['rejection_code'],'P18_ILLEGAL_TRANSITION')

    def test_inconclusive_demo_is_uncertain(self):
        self.assertEqual(execution_demo(scenario='inconclusive')['status'],'BLOCKED_UNCERTAIN')

    def test_audit_reports_uncertain(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.sqlite3'
            ledger=OfflineExecutionLedger(path); intent=fixture_intent()
            ledger.prepare(intent);ledger.mark_dispatch_boundary(intent.action_id)
            report=execution_audit(path)
            self.assertEqual(report['status'],'BLOCKED_UNCERTAIN')
            self.assertEqual(report['uncertain_action_ids'],[intent.action_id])
            self.assertFalse(report['physical_input_sent'])

    def test_bad_demo_scenario_rejected(self):
        with self.assertRaises(ExecutionLedgerRejected):execution_demo(scenario='unknown')

    def test_no_imports_from_other_runtime_systems(self):
        root=Path(__file__).resolve().parents[1]
        for rel in ('src/anka_execution/ledger.py','src/anka_execution/settlement.py'):
            text=(root/rel).read_text()
            for banned in ('from anka_client','from anka_coordination','from anka_workflow',
                           'from anka_protocol','from anka_capture','from anka_decision',
                           'import pyautogui','import win32api'):
                self.assertNotIn(banned,text)

    def test_legacy_isolation_and_start_blocked(self):
        root=Path(__file__).resolve().parents[1]
        self.assertTrue((root/'src/anka_game_kernel/api/kernel.py').exists())
        self.assertIn('blockers_for(host,ingress', (root/'src/anka_app/cli.py').read_text())
        self.assertIn('LIVE_RUNTIME_NOT_IMPLEMENTED',(root/'src/anka_app/composition.py').read_text())


if __name__=='__main__':unittest.main()

class AdditionalHardening(unittest.TestCase):
    def test_weird_sqlite_filename_read_only(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'my#ledger?info.sqlite3'
            writer=OfflineExecutionLedger(path)
            writer.prepare(fixture_intent())
            self.assertEqual(OfflineExecutionLedger(path,read_only=True).audit_all()[0].status,'PREPARED')

    def test_malformed_outcome_not_silent(self):
        with TemporaryDirectory() as folder:
            db=OfflineExecutionLedger(Path(folder)/'audit.db')
            i=fixture_intent();db.prepare(i);db.mark_dispatch_boundary(i.action_id)
            for obj in ({'action_id':'bad'}, None, 'ACCEPTED'):
                with self.assertRaises(ExecutionLedgerRejected):db.record_outcome(obj)
            self.assertEqual(db.audit(i.action_id).status,'DISPATCH_UNCERTAIN')

    def test_tampered_evidence_scope_even_if_hashes_reset(self):
        # Re-signing a fabricated semantic event is NOT proof that it matches the intent.
        from anka_execution.ledger import _hash,_encode
        with TemporaryDirectory() as folder:
            path=Path(folder)/'forged.db';db=OfflineExecutionLedger(path)
            intent=fixture_intent();db.prepare(intent);db.mark_dispatch_boundary(intent.action_id)
            db.record_outcome(fixture_evidence(intent))
            with sqlite3.connect(path) as con:
                con.execute('DROP TRIGGER forbid_event_update')
                rows=con.execute('SELECT sequence,action_id,event_type,payload FROM action_events ORDER BY sequence').fetchall()
                previous='GENESIS'
                for seq,action,ev,payload in rows:
                    if ev=='OUTCOME_ACCEPTED':
                        altered=json.loads(payload);altered['account_id']='wrong-account';payload=_encode(altered)
                    h=_hash(seq,action,ev,payload,previous)
                    con.execute('UPDATE action_events SET payload=?,previous_hash=?,record_hash=? WHERE sequence=?',
                                (payload,previous,h,seq))
                    previous=h
            with self.assertRaisesRegex(ExecutionLedgerIntegrityError,'EVIDENCE_SCOPE_INVALID'):
                db.audit_all()

    def test_sqlite_read_only_cli_exit_code_conflict(self):
        from anka_app.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        with TemporaryDirectory() as folder:
            path=Path(folder)/'test.db';db=OfflineExecutionLedger(path)
            i=fixture_intent();db.prepare(i);db.mark_dispatch_boundary(i.action_id)
            out=StringIO()
            with redirect_stdout(out):code=main(['execution-audit',str(path)])
            self.assertEqual(code,10)
            self.assertIn('ANKA_STATUS=BLOCKED_UNCERTAIN',out.getvalue())

    def test_invalid_cli_demo_specific_error(self):
        from anka_app.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        out=StringIO()
        with redirect_stdout(out):code=main(['execution-demo','invalid'])
        self.assertEqual(code,40)
        self.assertIn('P18_DEMO_SCENARIO_INVALID',out.getvalue())

class VerifyTimeoutRegression(unittest.TestCase):
    def test_bounded_verify_timeout_has_diagnostic_event(self):
        from anka_app.verification_runner import VerificationRejected
        from anka_app.cli import _command
        class Sink:
            def __init__(self):self.events=[]
            def record(self,*args,**kwargs):self.events.append((args,kwargs))
        sink=Sink()
        with patch('anka_app.cli._preflight',return_value={}),patch('anka_app.verification_runner.verify_isolated',
                   side_effect=VerificationRejected('OFFLINE_TEST_SUITE_TIMEOUT', shard=2, modules=('test_foo',), output='test_foo ...')):
            with self.assertRaisesRegex(RuntimeError,'OFFLINE_TEST_SUITE_TIMEOUT'):
                _command('verify',sink,[])
        self.assertTrue(any(a[0]=='verification.suite_timed_out' for a,k in sink.events))
        self.assertIn('test_foo',str(sink.events))
