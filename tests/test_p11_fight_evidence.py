"""P11 adversarial fixture-only acceptance: journal/turn/coordination boundaries."""
from __future__ import annotations
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3, unittest
from anka_contracts.state import OfflineStateEvent
from anka_contracts.fight_audit import AccountExpectation
from anka_canonical.journal import SQLiteFixtureJournal,JournalError,JournalIntegrityError
from anka_live_state.reducer import apply_offline_event
from anka_live_state.fight_trace import trace_fight_events
from anka_coordination.fight_audit import compare_fight_views
from anka_app.fight_offline import fight_demo, fight_audit,parse_expectations


def event(n,kind,*,session='cra-session',account='cra',gen=1,fight='f1',**kwargs):
    return OfflineStateEvent(f'{session}-{n}',session,account,gen,fight,n,kind,**kwargs)

def fixture(j,session='cra-session',account='cra',actor=777,owner=777,fight='f1',gen=1,resources=True):
    data=[('FIGHT_STARTED',{}),('ACTOR_SEEN',{'actor_id':777}),('ACTOR_SEEN',{'actor_id':888})]
    if resources:
        data += [('ACTOR_RESOURCE_SET',{'actor_id':actor,'resource':'AP','value':11}),
                 ('ACTOR_RESOURCE_SET',{'actor_id':actor,'resource':'MP','value':5})]
    data += [('TURN_STARTED',{'actor_id':owner})]
    for n,(kind,kw) in enumerate(data,1):
        j.append_fixture(event(n,kind,session=session,account=account,gen=gen,fight=fight,**kw))
    return len(data)

class TestHistoryAndRecovery(unittest.TestCase):
    def setUp(self):
        self.t=TemporaryDirectory();self.p=Path(self.t.name)/'state.sqlite3'
    def tearDown(self):self.t.cleanup()
    def open(self,ro=False):return SQLiteFixtureJournal(self.p,reducer=apply_offline_event,read_only=ro)
    def test_audited_history_multiple_sessions_no_authority(self):
        with self.open() as j:
            fixture(j);fixture(j,'enu-session','enu',888)
            result=j.audited_evidence(('cra-session','enu-session'))
            self.assertEqual(result['audit']['events'],12)
            self.assertFalse(result['actionable'])
            self.assertEqual(result['views']['enu-session']['events'][-1].kind,'TURN_STARTED')
            self.assertEqual(result['views']['cra-session']['snapshot']['turn_owner_id'],777)
    def test_read_only_evidence_method(self):
        with self.open() as j:fixture(j)
        with self.open(True) as j:
            self.assertEqual(j.audited_evidence(('cra-session',))['audit']['status'],'PASS')
    def test_no_silent_truncated_history(self):
        with self.open() as j:
            fixture(j)
            with self.assertRaisesRegex(JournalError,'LIMIT_EXCEEDED'):
                j.audited_evidence(('cra-session',),max_events_per_session=5)
            self.assertEqual(j.audit()['events'],6)
    def test_duplicate_and_invalid_session_list(self):
        with self.open() as j:
            for items in ((),('s','s'),('s',)*17,('s',42)):
                with self.assertRaises(ValueError):j.audited_evidence(items)
            for limit in (True,0,-1,60000):
                with self.assertRaises(ValueError):j.audited_evidence(('s',),max_events_per_session=limit)
    def test_audit_detects_corruption_before_returning_views(self):
        with self.open() as j:fixture(j)
        with sqlite3.connect(self.p) as c:
            c.execute("UPDATE events SET event_json='{}' WHERE sequence=4")
        with self.assertRaises(JournalIntegrityError):self.open(True)
    def test_read_transaction_same_snapshot_against_parallel_writer(self):
        with self.open() as reader:
            fixture(reader)
        with self.open(True) as reader:
            original=reader.audit
            def audit_then_write(*args,**kwargs):
                value=original(*args,**kwargs)
                with self.open() as writer:
                    writer.append_fixture(event(7,'TURN_ENDED',actor_id=777))
                return value
            reader.audit=audit_then_write
            result=reader.audited_evidence(('cra-session',))
            self.assertEqual(len(result['views']['cra-session']['events']),6)
            self.assertEqual(result['views']['cra-session']['snapshot']['revision'],6)
        with self.open(True) as reader:
            self.assertEqual(reader.snapshot('cra-session')['revision'],7)
    def test_cannot_import_historical_candidate_as_fixture(self):
        from anka_contracts.canonical import CanonicalDraft,EvidenceRef
        from hashlib import sha256
        draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',777,EvidenceRef('Dofus 3.7.10.10','history','jtk',1,1,sha256(b'f').hexdigest()),resource='AP',value=11)
        with self.open() as j:
            with self.assertRaises(TypeError):j.append_fixture(draft)

class TestFightTracing(unittest.TestCase):
    def test_ap_before_turn_is_not_immediately_declared_stale(self):
        events=(event(1,'FIGHT_STARTED'),event(2,'ACTOR_SEEN',actor_id=777),
                event(3,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
                event(4,'TURN_STARTED',actor_id=777))
        result=trace_fight_events(events)
        self.assertEqual(result['active_owner'],777)
        self.assertEqual(result['earlier_fight_resource_coverage']['fields'],['AP'])
        self.assertEqual(result['current_turn_resource_coverage']['fields'],[])
        self.assertFalse(result['actionable'])
    def test_resources_after_turn_recorded_separately(self):
        es=(event(1,'FIGHT_STARTED'),event(2,'ACTOR_SEEN',actor_id=777),
            event(3,'TURN_STARTED',actor_id=777),
            event(4,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
            event(5,'ACTOR_RESOURCE_SET',actor_id=777,resource='MP',value=5))
        trace=trace_fight_events(es)
        self.assertEqual(trace['current_turn_resource_coverage']['fields'],['AP','MP'])
    def test_turn_owner_handoff_trace(self):
        es=(event(1,'FIGHT_STARTED'),event(2,'TURN_STARTED',actor_id=777),
            event(3,'TURN_ENDED',actor_id=777),event(4,'TURN_STARTED',actor_id=888))
        trace=trace_fight_events(es)
        self.assertEqual((trace['turns'],trace['active_owner'],trace['start_sequence']),(2,888,4))
    def test_new_fight_epoch_resets_resources(self):
        es=(event(1,'FIGHT_STARTED'),event(2,'ACTOR_RESOURCE_SET',actor_id=777,resource='AP',value=11),
            event(3,'FIGHT_ENDED'),event(4,'FIGHT_STARTED',fight='f2'),
            event(5,'TURN_STARTED',fight='f2',actor_id=888))
        trace=trace_fight_events(es)
        self.assertEqual(trace['last_resource_sequences'],{})
        self.assertEqual(trace['turns'],1)
    def test_reject_invalid_sequence_and_bad_inputs(self):
        with self.assertRaises(TypeError):trace_fight_events([event(1,'FIGHT_STARTED')])
        with self.assertRaises(ValueError):trace_fight_events((event(1,'FIGHT_STARTED'),event(3,'TURN_STARTED',actor_id=777)))

class TestCrossAccountBoundaries(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.db=Path(self.tmp.name)/'f.sqlite3'
        self.expected=(AccountExpectation('cra-session','cra',1,777),AccountExpectation('enu-session','enu',1,888))
    def tearDown(self):self.tmp.cleanup()
    def prepare(self,**kw):
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event) as j:
            fixture(j)
            fixture(j,'enu-session','enu',888,**kw)
    def run_audit(self,expected=None):
        return fight_audit(self.db,expected or self.expected)
    def test_aligned_but_never_authoritative(self):
        self.prepare()
        r=self.run_audit()
        self.assertEqual(r['status'],'ALIGNED_SIMULATED_ONLY')
        self.assertFalse(r['fight']['shared_live_event_proof'])
        self.assertFalse(r['fight']['authoritative'])
        self.assertFalse(r['physical_input_sent'])
    def test_conflicting_owner_detected(self):
        self.prepare(owner=888)
        self.assertIn('TURN_OWNER_CONFLICT',self.run_audit()['fight']['reasons'])
    def test_conflicting_fight_detected(self):
        self.prepare(fight='other-fight')
        self.assertIn('FIGHT_ID_CONFLICT',self.run_audit()['fight']['reasons'])
    def test_account_generation_mismatch_detected(self):
        self.prepare()
        expected=(self.expected[0],replace(self.expected[1],account_generation=2))
        self.assertIn('ACCOUNT_IDENTITY_OR_GENERATION_MISMATCH',self.run_audit(expected)['fight']['reasons'])
    def test_missing_session_and_actor_rejected(self):
        self.prepare()
        expected=(self.expected[0],AccountExpectation('lost-session','lost',1,999))
        self.assertIn('MISSING_SESSION_SNAPSHOT',self.run_audit(expected)['fight']['reasons'])
        expected=(self.expected[0],replace(self.expected[1],local_actor_id=999))
        self.assertIn('LOCAL_ACTOR_NOT_OBSERVED',self.run_audit(expected)['fight']['reasons'])
    def test_owner_missing_case(self):
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event) as j:
            j.append_fixture(event(7,'TURN_ENDED',actor_id=777))
        self.assertIn('TURN_OWNER_UNPROVEN',self.run_audit()['fight']['reasons'])
    def test_reject_duplicate_account_role(self):
        self.prepare()
        with self.assertRaises(ValueError):self.run_audit((self.expected[0],self.expected[0]))
    def test_no_snapshot_attestation_cannot_appear_aligned(self):
        from anka_coordination.fight_audit import compare_fight_views
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event,read_only=True) as j:
            batch=j.audited_evidence(('cra-session','enu-session'))
        views={name:{'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
               for name,item in batch['views'].items()}
        result=compare_fight_views(self.expected,views)
        self.assertEqual(result.status,'BLOCKED_INCONSISTENT')
        self.assertFalse(result.same_database_snapshot)
        self.assertIn('MULTI_SESSION_SNAPSHOT_NOT_ATTESTED',result.reasons)
    def test_stale_turn_trace_rejected(self):
        from anka_coordination.fight_audit import compare_fight_views
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event,read_only=True) as j:
            batch=j.audited_evidence(('cra-session','enu-session'))
        views={name:{'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
               for name,item in batch['views'].items()}
        views['enu-session']['trace']['last_sequence'] -= 1
        result=compare_fight_views(self.expected,views,same_database_snapshot=True)
        self.assertIn('TURN_TRACE_SNAPSHOT_MISMATCH',result.reasons)
    def test_conflicting_account_scopes_in_trace(self):
        es=(event(1,'FIGHT_STARTED'),event(2,'ACTOR_SEEN',session='enu-session',account='enu',actor_id=777))
        with self.assertRaisesRegex(ValueError,'TRACE_SEQUENCE_INVALID'):
            trace_fight_events(es)
    def test_untrusted_authority_rejected_even_with_aligned_owners(self):
        from anka_coordination.fight_audit import compare_fight_views
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event,read_only=True) as j:
            batch=j.audited_evidence(('cra-session','enu-session'))
        views={name:{'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
               for name,item in batch['views'].items()}
        views['enu-session']['snapshot']['authority']='CERTIFIED_FAKE'
        result=compare_fight_views(self.expected,views,same_database_snapshot=True)
        self.assertIn('UNSUPPORTED_STATE_AUTHORITY',result.reasons)
    def test_cli_demo_no_physical_input(self):
        from anka_app.cli import main
        import io
        from contextlib import redirect_stdout
        buf=io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(['fight-demo']),0)
        line=next(x for x in buf.getvalue().splitlines() if x.startswith('ANKA_RESULT='))
        import json
        payload=json.loads(line.split('=',1)[1])
        self.assertFalse(payload['physical_input_sent'])
        self.assertEqual(payload['divergent_handoff']['status'],'BLOCKED_INCONSISTENT')
    def test_cli_invalid_args_produce_failure_evidence(self):
        from anka_app.cli import main
        import io
        from contextlib import redirect_stdout
        buf=io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(main(['fight-audit']),40)
        self.assertIn('ANKA_STATUS=BLOCKED',buf.getvalue())
        self.assertIn('ANKA_BUNDLE=',buf.getvalue())
    def test_divergence_writes_verifiable_incident(self):
        from anka_observability.api import LocalDiagnostics
        from anka_observability.bundle import verify_incident
        with TemporaryDirectory() as out:
            observer=LocalDiagnostics(Path(out))
            demo=fight_demo(observer=observer)
            path=Path(demo['incident_bundle'])
            self.assertTrue(path.is_file())
            self.assertEqual(verify_incident(path)['status'],'PASS')
            observer.finish('CLOSED')
    def test_failed_diagnostic_sink_does_not_change_audit_result(self):
        class BrokenSink:
            def record(self,*args,**kwargs):raise OSError('full drive')
        self.prepare(owner=888)
        output=fight_audit(self.db,self.expected,observer=BrokenSink())
        self.assertEqual(output['status'],'BLOCKED_INCONSISTENT')
        self.assertIn('TURN_OWNER_CONFLICT',output['fight']['reasons'])
        self.assertEqual(output['incident_bundle'],'UNAVAILABLE_DIAGNOSTICS_SINK_FAILURE')
    def test_only_setup_and_start_are_operator_launchers(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual({p.name for p in root.glob('*.bat')}, {'setup.bat','start.bat'})
        for file in ('setup.bat','start.bat'):
            body=(root/file).read_text()
            self.assertIn('tools\\windows\\_entry.bat', body)
            self.assertNotIn('input_driver',body)
        self.assertTrue((root/'tools/windows/_entry.bat').is_file())
    def test_demo_detects_handoff_divergence(self):
        demo=fight_demo()
        self.assertEqual(demo['aligned']['status'],'ALIGNED_SIMULATED_ONLY')
        self.assertEqual(demo['divergent_handoff']['status'],'BLOCKED_INCONSISTENT')
        self.assertIn('TURN_OWNER_CONFLICT',demo['divergent_handoff']['fight']['reasons'])
        self.assertFalse(demo['physical_input_sent'])
    def test_cli_inconsistent_audit_reports_nonzero_exit_and_incident(self):
        from anka_app.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        from json import loads
        self.prepare(owner=888)
        out=StringIO()
        with redirect_stdout(out):
            status=main(['fight-audit',str(self.db), 'cra-session:cra:1:777',
                         'enu-session:enu:1:888'])
        self.assertEqual(status,10)
        self.assertIn('ANKA_STATUS=BLOCKED_INCONSISTENT',out.getvalue())
        payload=loads(next(line.split('=',1)[1] for line in out.getvalue().splitlines()
                           if line.startswith('ANKA_RESULT=')))
        self.assertIn('TURN_OWNER_CONFLICT',payload['fight']['reasons'])
        self.assertTrue(Path(payload['incident_bundle']).is_file())
        self.assertFalse(payload['physical_input_sent'])

    def test_cli_aligned_synthetic_audit_exits_zero_without_live_readiness(self):
        from anka_app.cli import main
        from contextlib import redirect_stdout
        from io import StringIO
        from json import loads
        self.prepare()
        out=StringIO()
        with redirect_stdout(out):
            status=main(['fight-audit',str(self.db), 'cra-session:cra:1:777',
                         'enu-session:enu:1:888'])
        self.assertEqual(status,0)
        payload=loads(next(line.split('=',1)[1] for line in out.getvalue().splitlines()
                           if line.startswith('ANKA_RESULT=')))
        self.assertEqual(payload['status'],'ALIGNED_SIMULATED_ONLY')
        self.assertFalse(payload['fight']['actionable'])
        self.assertFalse(payload['live_ready'])

    def test_bad_view_shape_fails_closed_with_reason_not_unhandled_exception(self):
        from anka_coordination.fight_audit import compare_fight_views
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event,read_only=True) as j:
            batch=j.audited_evidence(('cra-session','enu-session'))
        views={name:{'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
               for name,item in batch['views'].items()}
        for invalid in (None,[],7):
            damaged={key:{'snapshot':dict(value['snapshot']), 'trace':value['trace']}
                     for key,value in views.items()}
            damaged['enu-session']['snapshot']['actors']=invalid
            result=compare_fight_views(self.expected,damaged,same_database_snapshot=True)
            self.assertEqual(result.status,'BLOCKED_INCONSISTENT')
            self.assertIn('ACTOR_STATE_INVALID',result.reasons)
            self.assertIn('TURN_OWNER_NOT_OBSERVED',result.reasons)
            self.assertFalse(result.actionable)

    def test_malformed_local_actor_state_is_named_and_non_authoritative(self):
        self.prepare()
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event,read_only=True) as j:
            batch=j.audited_evidence(('cra-session','enu-session'))
        views={name:{'snapshot':item['snapshot'],'trace':trace_fight_events(item['events'])}
               for name,item in batch['views'].items()}
        views['enu-session']['snapshot']['actors']['888']=None
        report=compare_fight_views(self.expected,views,same_database_snapshot=True)
        self.assertIn('LOCAL_ACTOR_NOT_OBSERVED',report.reasons)
        views['enu-session']['snapshot']['actors']['888']='corrupted actor'
        report=compare_fight_views(self.expected,views,same_database_snapshot=True)
        self.assertIn('LOCAL_ACTOR_STATE_INVALID',report.reasons)

    def test_partial_actor_has_explicit_missing_fields_without_fake_readiness(self):
        self.prepare(resources=False)
        result=self.run_audit()
        self.assertEqual(result['status'],'ALIGNED_SIMULATED_ONLY')
        enu=next(a for a in result['fight']['accounts'] if a['account_id']=='enu')
        self.assertIn('AP',enu['missing_decision_fields'])
        self.assertIn('cell_id',enu['missing_decision_fields'])
        self.assertTrue(enu['missing_decision_fields'])
        self.assertFalse(result['fight']['actionable'])

    def test_invalid_expectation_types_rejected_as_contract_errors(self):
        from anka_coordination.fight_audit import compare_fight_views
        for invalid in ((None,),('not an expectation',),[self.expected[0]],()):
            with self.assertRaisesRegex(ValueError,'FIGHT_AUDIT_ACCOUNTS_INVALID'):
                compare_fight_views(invalid,{})
        with self.assertRaisesRegex(TypeError,'FIGHT_AUDIT_VIEWS_REQUIRED'):
            compare_fight_views(self.expected,None)
        with self.assertRaisesRegex(ValueError,'FIGHT_AUDIT_SNAPSHOT_FLAG_INVALID'):
            compare_fight_views(self.expected,{},same_database_snapshot=1)

    def test_new_systems_keep_dependency_boundaries(self):
        import ast
        root=Path(__file__).resolve().parents[1]/'src'
        forbidden={
            'anka_coordination':{'anka_app','anka_canonical','anka_capture','anka_client',
                                 'anka_protocol','anka_live_state','anka_execution',
                                 'anka_decision','anka_observability'},
            'anka_live_state':{'anka_app','anka_canonical','anka_capture','anka_protocol',
                               'anka_execution','anka_coordination'},
            'anka_contracts':{'anka_app','anka_canonical','anka_capture','anka_protocol',
                              'anka_execution','anka_coordination','anka_live_state'},
        }
        for package,blocked in forbidden.items():
            for source in (root/package).rglob('*.py'):
                tree=ast.parse(source.read_text(encoding='utf-8'))
                imports=[node.module for node in ast.walk(tree)
                         if isinstance(node,ast.ImportFrom) and node.module]
                imports.extend(name.name for node in ast.walk(tree)
                               if isinstance(node,ast.Import) for name in node.names)
                for module in imports:
                    self.assertFalse(any(module==bad or module.startswith(bad+'.')
                                         for bad in blocked),(source.name,module))

    def test_cli_expectation_parser_fail_closed(self):
        self.assertEqual(parse_expectations(['s:a:1:7'])[0].local_actor_id,7)
        for broken in ([],['oops'],['s:a:x:7'],['s:a:1:7:extra']):
            with self.assertRaises(ValueError):parse_expectations(broken)

if __name__=='__main__':unittest.main()
