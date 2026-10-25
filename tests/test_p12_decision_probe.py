"""P12 deterministic, non-executable decision-feasibility regression tests."""
from __future__ import annotations
import ast, copy, json, subprocess, sys, unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from anka_contracts.decision import CastProbe,CastProbeReport
from anka_decision.probe import inspect_cast_probe
from anka_app.decision_offline import decision_demo, synthetic_decision_snapshot,reference_kernel
from anka_app.cli import ROOT


def probe(**changes):
    defaults=dict(session_id='cra-session',account_id='cra',account_generation=1,
                  fight_id='test-fight',minimum_revision=8,actor_id=777,spell_id=32435,
                  grade=3,target_cell=220)
    defaults.update(changes)
    return CastProbe(**defaults)


class TestP12Safety(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel=reference_kernel(ROOT)
    def run_probe(self,snap=None,p=None):
        return inspect_cast_probe(synthetic_decision_snapshot() if snap is None else snap,
                                  probe() if p is None else p,kernel=self.kernel)
    def test_current_good_synthetic_still_not_authoritative(self):
        r=self.run_probe()
        self.assertEqual(r.status,'RESEARCH_ONLY')
        self.assertIn('CURRENT_CLIENT_BUILD_UNCERTIFIED',r.reasons)
        self.assertIn('MAP_GEOMETRY_AND_LINE_OF_SIGHT_UNPROVEN',r.reasons)
        self.assertFalse(r.actionable)
        self.assertFalse(r.authoritative)
    def test_even_valid_ap_does_not_prove_legal_cast(self):
        self.assertNotEqual(self.run_probe().kernel_legality,'LEGAL')
    def test_ap_insufficient_is_rejected_using_real_kernel(self):
        r=self.run_probe(synthetic_decision_snapshot(ap=0))
        self.assertEqual(r.status,'REJECTED_BY_KERNEL')
        self.assertIn('KERNEL_NOT_ENOUGH_AP',r.reasons)
    def test_cooldown_active_rejected_using_real_kernel(self):
        r=self.run_probe(synthetic_decision_snapshot(cooldown=2))
        self.assertEqual(r.status,'REJECTED_BY_KERNEL')
        self.assertIn('KERNEL_COOLDOWN_ACTIVE',r.reasons)
    def test_missing_cast_count_survives_as_missing_kernel_input(self):
        self.assertIn('casts_this_turn',self.run_probe().missing_kernel_inputs)
    def test_wrong_session(self):
        self.assertIn('ACCOUNT_SCOPE_MISMATCH',self.run_probe(p=probe(session_id='enu-session')).reasons)
    def test_wrong_account(self):
        self.assertIn('ACCOUNT_SCOPE_MISMATCH',self.run_probe(p=probe(account_id='enu')).reasons)
    def test_process_generation_switch(self):
        self.assertIn('ACCOUNT_SCOPE_MISMATCH',self.run_probe(p=probe(account_generation=2)).reasons)
    def test_fight_change(self):
        self.assertIn('FIGHT_EPOCH_MISMATCH',self.run_probe(p=probe(fight_id='other')).reasons)
    def test_stale_revision(self):
        self.assertIn('STATE_REVISION_STALE',self.run_probe(p=probe(minimum_revision=9)).reasons)
    def test_owner_changed(self):
        snap=synthetic_decision_snapshot();snap['turn_owner_id']=888
        self.assertIn('TURN_OWNER_NOT_PROVEN',self.run_probe(snap).reasons)
    def test_phase_ended(self):
        snap=synthetic_decision_snapshot();snap['phase']='ENDED'
        self.assertIn('FIGHT_NOT_ACTIVE',self.run_probe(snap).reasons)
    def test_missing_actor(self):
        snap=synthetic_decision_snapshot();snap['actors']={}
        self.assertIn('ACTOR_STATE_MISSING',self.run_probe(snap).reasons)
    def test_missing_ap(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['AP']=None
        self.assertIn('ACTOR_AP_MISSING',self.run_probe(snap).reasons)
    def test_missing_cd(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['cooldowns']=None
        self.assertIn('ACTOR_COOLDOWNS_MISSING',self.run_probe(snap).reasons)
    def test_malformed_actor(self):
        snap=synthetic_decision_snapshot();snap['actors']={'777':'not an actor'}
        self.assertEqual(self.run_probe(snap).status,'BLOCKED_EVIDENCE')
    def test_malformed_cooldowns(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['cooldowns']=[['bad',4]]
        self.assertEqual(self.run_probe(snap).status,'BLOCKED_EVIDENCE')
    def test_duplicate_cooldown(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['cooldowns'].append([32435,2])
        self.assertIn('COOLDOWN_ID_DUPLICATED',self.run_probe(snap).reasons)
    def test_negative_ap(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['AP']=-1
        self.assertIn('ACTOR_RESOURCES_INVALID',self.run_probe(snap).reasons)
    def test_forged_bool_generation_and_owner(self):
        snap=synthetic_decision_snapshot();snap['account_generation']=True;snap['turn_owner_id']=True
        r=self.run_probe(snap)
        self.assertIn('ACCOUNT_SCOPE_MISMATCH',r.reasons)
        self.assertIn('TURN_OWNER_NOT_PROVEN',r.reasons)
    def test_revision_sequence_inconsistent(self):
        snap=synthetic_decision_snapshot();snap['last_sequence']=7
        self.assertIn('STATE_SEQUENCE_INCONSISTENT',self.run_probe(snap).reasons)
    def test_hp_exceeds_max(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['hp']=5000
        self.assertIn('ACTOR_HP_EXCEEDS_MAXIMUM',self.run_probe(snap).reasons)
    def test_ap_over_allowed_range(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['AP']=999999
        self.assertIn('ACTOR_RESOURCES_OUT_OF_RANGE',self.run_probe(snap).reasons)
    def test_negative_cooldown_identity(self):
        snap=synthetic_decision_snapshot();snap['actors']['777']['cooldowns']=[[-8,0]]
        self.assertIn('ACTOR_COOLDOWNS_INVALID',self.run_probe(snap).reasons)
    def test_untrusted_authoritative_claim_rejected(self):
        snap=synthetic_decision_snapshot();snap['actionable']=True
        self.assertIn('STATE_AUTHORITY_NOT_SYNTHETIC',self.run_probe(snap).reasons)
    def test_historical_wire_evidence_cannot_become_decision_snapshot(self):
        from anka_contracts.canonical import CanonicalDraft,EvidenceRef
        draft=CanonicalDraft('ACTOR_RESOURCE_ABSOLUTE',777,EvidenceRef('Dofus 3.7.10.10','history','jtk',1,1,'a'*64),resource='AP',value=11)
        self.assertEqual(inspect_cast_probe(draft,probe(),kernel=self.kernel).status,'BLOCKED_EVIDENCE')
    def test_unrecognized_spell(self):
        self.assertEqual(self.run_probe(p=probe(spell_id=123456789)).status,'BLOCKED_STATIC_DATA')
    def test_invalid_grade(self):
        self.assertEqual(self.run_probe(p=probe(grade=10)).status,'BLOCKED_STATIC_DATA')
    def test_report_cannot_turn_into_actuation_instruction(self):
        report=self.run_probe()
        with self.assertRaises(FrozenInstanceError):report.actionable=True
        self.assertNotIn('mouse',json.dumps(report.to_dict()).lower())
        self.assertNotIn('window',json.dumps(report.to_dict()).lower())
        self.assertFalse(report.to_dict()['physical_input_permitted'])
    def test_fields_strict_bool_and_token(self):
        for changed in ({'account_generation':True},{'minimum_revision':True},{'target_cell':False},
                        {'actor_id':0},{'grade':0},{'session_id':'bad name'},
                        {'fight_id':''},{'spell_id':0},{'target_cell':100001}):
            with self.subTest(changed=changed),self.assertRaises(ValueError):probe(**changed)
    def test_bad_probe_type(self):
        with self.assertRaises(TypeError):inspect_cast_probe({},'invalid',kernel=self.kernel)
    def test_no_mutation(self):
        snapshot=synthetic_decision_snapshot();same=copy.deepcopy(snapshot)
        self.run_probe(snapshot)
        self.assertEqual(snapshot,same)
    def test_demo_three_scenarios(self):
        result=decision_demo(root=ROOT)
        self.assertEqual(result['status'],'SYNTHETIC_PREVIEW_ONLY')
        self.assertEqual(result['reports']['insufficient_ap']['status'],'REJECTED_BY_KERNEL')
        self.assertEqual(result['reports']['cooldown_active']['status'],'REJECTED_BY_KERNEL')
        self.assertEqual(result['reports']['complete_synthetic']['status'],'RESEARCH_ONLY')
        self.assertFalse(result['physical_input_sent'])
    def test_decision_package_dependency_boundary(self):
        blocked={'anka_app','anka_capture','anka_protocol','anka_live_state','anka_canonical',
                 'anka_execution','anka_client','anka_coordination','anka_workflow','anka_observability'}
        for p in (ROOT/'src/anka_decision').rglob('*.py'):
            tree=ast.parse(p.read_text(encoding='utf8'))
            for node in ast.walk(tree):
                if isinstance(node,ast.Import):targets=[item.name for item in node.names]
                elif isinstance(node,ast.ImportFrom):targets=[node.module or '']
                else:continue
                self.assertFalse({name.split('.')[0] for name in targets}&blocked,(p,targets))
    def test_cli_demo(self):
        run=subprocess.run([sys.executable,'-m','anka_app.cli','decision-demo'],cwd=ROOT,
                            text=True,capture_output=True,timeout=20)
        self.assertEqual(run.returncode,0,run.stderr[-1500:])
        self.assertIn('SYNTHETIC_PREVIEW_ONLY',run.stdout)
    def test_start_still_blocked(self):
        run=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,
                            text=True,capture_output=True,timeout=20)
        self.assertEqual(run.returncode,40)
        self.assertIn('START_WINDOWS_REQUIRED',run.stdout)

if __name__=='__main__':unittest.main()

class TestDurableDecisionAudit(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory
        from anka_canonical.journal import SQLiteFixtureJournal
        from anka_live_state.reducer import apply_offline_event
        from anka_contracts.state import OfflineStateEvent
        self.tmp=TemporaryDirectory();self.db=Path(self.tmp.name)/'decision.sqlite3'
        events=[('FIGHT_STARTED',{}),('ACTOR_SEEN',{'actor_id':777}),
           ('ACTOR_HP_SET',{'actor_id':777,'value':2800,'maximum':3200}),
           ('ACTOR_RESOURCE_SET',{'actor_id':777,'resource':'AP','value':11}),
           ('ACTOR_RESOURCE_SET',{'actor_id':777,'resource':'MP','value':5}),
           ('ACTOR_POSITION_SET',{'actor_id':777,'value':215}),
           ('ACTOR_COOLDOWNS_SET',{'actor_id':777,'cooldowns':((32435,0),)}),
           ('TURN_STARTED',{'actor_id':777})]
        with SQLiteFixtureJournal(self.db,reducer=apply_offline_event) as journal:
            for n,(kind,kw) in enumerate(events,1):
                journal.append_fixture(OfflineStateEvent(f'p12-{n}','cra-session','cra',1,'test-fight',n,kind,**kw))
    def tearDown(self):self.tmp.cleanup()
    def test_audited_decision_research_only(self):
        from anka_app.decision_offline import decision_audit
        result=decision_audit(self.db,probe(),root=ROOT)
        self.assertEqual(result['journal_integrity'],'PASS')
        self.assertEqual(result['status'],'RESEARCH_ONLY')
        self.assertFalse(result['physical_input_sent'])
    def test_mismatched_account_blocked(self):
        from anka_app.decision_offline import decision_audit
        result=decision_audit(self.db,probe(account_id='enu'),root=ROOT)
        self.assertEqual(result['status'],'BLOCKED_EVIDENCE')
    def test_cli_readonly_db_not_rewritten(self):
        from hashlib import sha256
        before=sha256(self.db.read_bytes()).hexdigest()
        args=[str(self.db),'cra-session','cra','1','test-fight','8','777','32435','3','220']
        process=subprocess.run([sys.executable,'-m','anka_app.cli','decision-audit',*args],
                               cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stdout[-1500:])
        self.assertIn('RESEARCH_ONLY',process.stdout)
        self.assertEqual(sha256(self.db.read_bytes()).hexdigest(),before)
    def test_cli_conflict_nonzero(self):
        args=[str(self.db),'cra-session','enu','1','test-fight','8','777','32435','3','220']
        process=subprocess.run([sys.executable,'-m','anka_app.cli','decision-audit',*args],
                               cwd=ROOT,text=True,capture_output=True,timeout=20)
        self.assertEqual(process.returncode,10,process.stdout[-1500:])
        self.assertIn('BLOCKED_EVIDENCE',process.stdout)
    def test_corrupt_history_must_not_return_report(self):
        import sqlite3
        from anka_canonical.journal import JournalIntegrityError
        from anka_app.decision_offline import decision_audit
        from contextlib import closing
        with closing(sqlite3.connect(self.db)) as con:
            con.execute("UPDATE events SET event_json='{}' WHERE sequence=4")
            con.commit()
        with self.assertRaises(JournalIntegrityError):decision_audit(self.db,probe(),root=ROOT)
    def test_missing_journal_cannot_create_one(self):
        from anka_app.decision_offline import decision_audit
        path=Path(self.tmp.name)/'absent.sqlite3'
        with self.assertRaises(Exception):decision_audit(path,probe(),root=ROOT)
        self.assertFalse(path.exists())
    def test_parse_rejects_non_ints_and_bad_length(self):
        from anka_app.decision_offline import parse_decision_probe
        for args in (['x']*9,['x']*8,['cra-session','cra','oops','test-fight','8','777','32435','3','220']):
            with self.assertRaises(ValueError):parse_decision_probe(args)
