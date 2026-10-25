"""P9 negative tests: passing inputs NEVER confer live/gameplay authority."""
from __future__ import annotations
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import json, os, subprocess, sys, unittest
from anka_contracts.canonical import CanonicalDraft, EvidenceRef
from anka_contracts.state import OfflineStateEvent
from anka_canonical.qualification import ResearchContext, review_candidates, MAX_REVIEW_ITEMS
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event
from anka_live_state.quality import inspect_state_quality
from anka_app.quality_offline import quality_demo,quality_audit

ROOT=Path(__file__).resolve().parents[1]
BUILD='Dofus 3.7.10.10'
ADAPTER='historical_3_7_10_10'

def draft(*,message=1,packet=10,value=11,build=BUILD,adapter=ADAPTER,kind='ACTOR_RESOURCE_ABSOLUTE',actor=777):
    evidence=EvidenceRef(build,adapter,'jtk',packet,2,sha256(b'flow').hexdigest(),message_index=message)
    if kind=='ACTOR_RESOURCE_ABSOLUTE':
        return CanonicalDraft(kind,actor,evidence,resource='AP',value=value)
    if kind=='ACTOR_HP_ABSOLUTE':
        return CanonicalDraft(kind,actor,evidence,value=value,maximum=100)
    raise AssertionError('unsupported test fixture')

def context(*,build=BUILD,adapter=ADAPTER,transport='UNKNOWN',identity='UNKNOWN'):
    return ResearchContext(build,adapter,transport,identity)


def snapshot(*,complete=True):
    actor={'hp':100,'max_hp':100,'AP':11,'MP':5,'cell_id':215,'cooldowns':[]}
    if not complete: actor['MP']=None
    return {'schema':1,'session_id':'s1','account_id':'cra','account_generation':2,'fight_id':'f1',
            'revision':8,'last_sequence':8,'phase':'IN_FIGHT','turn_owner_id':777,
            'actors':{'777':actor},'authority':'SYNTHETIC_FIXTURE_ONLY','actionable':False}

def review_state(state=None,**kw):
    return inspect_state_quality(snapshot() if state is None else state,session_id='s1',
                                 account_id='cra',account_generation=2,actor_id=777,**kw)

class QualificationContracts(unittest.TestCase):
    def test_reject_empty_build(self):
        with self.assertRaises(ValueError): context(build='')
    def test_reject_invalid_adapter(self):
        with self.assertRaises(ValueError): context(adapter='')
    def test_reject_transport_typo(self):
        with self.assertRaises(ValueError): context(transport='PASSED')
    def test_reject_identity_typo(self):
        with self.assertRaises(ValueError): context(identity='CERTIFIED')
    def test_reject_context_none(self):
        with self.assertRaises(TypeError):review_candidates((draft(),),None)
    def test_reject_generator_to_preserve_bound(self):
        with self.assertRaises(TypeError):review_candidates((x for x in (draft(),)),context())
    def test_missing_candidates(self):
        result=review_candidates((),context())
        self.assertEqual(result.status,'RESEARCH_ONLY')
        self.assertIn('NO_CANDIDATES',result.reason_codes)
        self.assertFalse(result.actionable)
    def test_matching_research_never_certifies(self):
        result=review_candidates((draft(),),context(transport='OBSERVED_NO_GAPS',identity='INDEPENDENTLY_OBSERVED'))
        self.assertEqual(result.status,'RESEARCH_ONLY')
        self.assertIn('CURRENT_BUILD_SEMANTIC_CERTIFICATION_MISSING',result.reason_codes)
        self.assertIn('DRIVER_CAPTURE_COMPLETENESS_UNPROVEN',result.reason_codes)
        self.assertEqual(result.committed_events,0)
        self.assertFalse(result.live_state_mutated)
        self.assertFalse(result.actionable)
        self.assertNotIn('certified',result.to_dict())
    def test_missing_transport_and_account(self):
        result=review_candidates((draft(),),context())
        self.assertIn('TRANSPORT_EVIDENCE_MISSING',result.reason_codes)
        self.assertIn('ACCOUNT_IDENTITY_MISSING',result.reason_codes)
    def test_incomplete_transport_and_provisional_account(self):
        result=review_candidates((draft(),),context(transport='INCOMPLETE',identity='PROVISIONAL'))
        self.assertIn('TRANSPORT_INCOMPLETE',result.reason_codes)
        self.assertIn('ACCOUNT_IDENTITY_PROVISIONAL',result.reason_codes)
    def test_build_mismatch(self):
        result=review_candidates((draft(build='Dofus 4'),),context())
        self.assertEqual(result.status,'QUARANTINED')
        self.assertIn('BUILD_MISMATCH',result.reason_codes)
    def test_adapter_mismatch(self):
        result=review_candidates((draft(adapter='new_adapter'),),context())
        self.assertEqual(result.status,'QUARANTINED')
        self.assertIn('ADAPTER_MISMATCH',result.reason_codes)
    def test_duplicate_evidence(self):
        item=draft()
        result=review_candidates((item,item),context())
        self.assertIn('DUPLICATE_OBSERVATION',result.reason_codes)
        self.assertEqual(result.unique,1)
        self.assertEqual(result.status,'QUARANTINED')
    def test_conflicting_evidence(self):
        result=review_candidates((draft(value=11),draft(value=12)),context())
        self.assertIn('CONFLICTING_OBSERVATION',result.reason_codes)
        self.assertEqual(result.unique,1)
    def test_duplicate_packet_different_occurrence(self):
        result=review_candidates((draft(message=1),draft(message=2)),context())
        self.assertEqual(result.unique,2)
        self.assertNotIn('DUPLICATE_OBSERVATION',result.reason_codes)
    def test_distinct_sources_do_not_collide(self):
        result=review_candidates((draft(packet=10),draft(packet=11)),context())
        self.assertEqual(result.unique,2)
    def test_distinct_kinds_do_not_collide(self):
        result=review_candidates((draft(kind='ACTOR_RESOURCE_ABSOLUTE'), draft(kind='ACTOR_HP_ABSOLUTE')),context())
        self.assertEqual(result.unique,2)
        self.assertEqual(dict(result.kinds),{'ACTOR_RESOURCE_ABSOLUTE':1,'ACTOR_HP_ABSOLUTE':1})
    def test_wrong_candidate_type_is_quarantined(self):
        result=review_candidates((draft(),{'kind':'fake'}),context())
        self.assertEqual(result.status,'QUARANTINED')
        self.assertIn('NON_CANONICAL_DRAFT',result.reason_codes)
    def test_bounded_review(self):
        result=review_candidates([draft()]*(MAX_REVIEW_ITEMS+1),context())
        self.assertIn('REVIEW_CAPACITY_EXCEEDED',result.reason_codes)
        self.assertEqual(result.unique,0)

class StateQualityTests(unittest.TestCase):
    def test_everything_filled_still_not_authoritative(self):
        result=review_state()
        self.assertEqual(result.status,'SIMULATED_ONLY')
        self.assertEqual(result.missing_fields,())
        self.assertEqual(result.failures,('CURRENT_BUILD_EVIDENCE_NOT_CERTIFIED',))
        self.assertFalse(result.actionable)
        self.assertFalse(result.authoritative)
    def test_missing_snapshot(self):
        result=inspect_state_quality(None,session_id='s1',account_id='cra',account_generation=2,actor_id=777)
        self.assertIn('NO_SNAPSHOT',result.failures)
        self.assertEqual(result.status,'MISSING_EVIDENCE')
    def test_wrong_session(self):
        state=snapshot();state['session_id']='other'
        self.assertIn('ACCOUNT_OR_PROCESS_GENERATION_MISMATCH',review_state(state).failures)
    def test_wrong_account(self):
        state=snapshot();state['account_id']='enu'
        self.assertIn('ACCOUNT_OR_PROCESS_GENERATION_MISMATCH',review_state(state).failures)
    def test_wrong_generation(self):
        state=snapshot();state['account_generation']=3
        self.assertIn('ACCOUNT_OR_PROCESS_GENERATION_MISMATCH',review_state(state).failures)
    def test_stale_revision(self):
        self.assertIn('STALE_OR_INVALID_REVISION',review_state(minimum_revision=9).failures)
    def test_revision_boolean_is_invalid(self):
        state=snapshot();state['revision']=True
        self.assertIn('STALE_OR_INVALID_REVISION',review_state(state).failures)
    def test_wrong_authority(self):
        state=snapshot();state['authority']='CERTIFIED_LIVE'
        self.assertIn('UNSUPPORTED_STATE_AUTHORITY',review_state(state).failures)
    def test_actionable_flag_is_forgery(self):
        state=snapshot();state['actionable']=True
        result=review_state(state)
        self.assertIn('UNSUPPORTED_STATE_AUTHORITY',result.failures)
        self.assertFalse(result.actionable)
    def test_missing_actor(self):
        state=snapshot();state['actors']={}
        self.assertIn('ACTOR_NOT_OBSERVED',review_state(state).failures)
    def test_actor_dictionary_invalid(self):
        state=snapshot();state['actors']=[]
        self.assertIn('ACTOR_STATE_INVALID',review_state(state).failures)
    def test_missing_mp(self):
        result=review_state(snapshot(complete=False))
        self.assertIn('MP',result.missing_fields)
        self.assertIn('MISSING_DECISION_FIELDS',result.failures)
    def test_turn_not_started_yet(self):
        state=snapshot();state['turn_owner_id']=None
        self.assertIn('TURN_OWNER_UNPROVEN',review_state(state).failures)
    def test_other_actor_turn(self):
        state=snapshot();state['turn_owner_id']=999;state['actors']['999']={}
        self.assertIn('NOT_ACTOR_TURN',review_state(state).failures)
    def test_turn_owner_actor_not_present(self):
        state=snapshot();state['turn_owner_id']=999
        self.assertIn('TURN_OWNER_NOT_IN_ACTOR_SET',review_state(state).failures)
    def test_ended_fight_not_active(self):
        state=snapshot();state['phase']='ENDED'
        self.assertIn('NO_ACTIVE_FIGHT',review_state(state).failures)
    def test_dead_actor_not_plan_ready(self):
        state=snapshot();state['actors']['777']['hp']=0
        self.assertIn('ACTOR_DEFEATED',review_state(state).failures)
    def test_invalid_hp_consistency(self):
        state=snapshot();state['actors']['777']['hp']=101
        self.assertIn('HP_INCONSISTENT',review_state(state).failures)
    def test_invalid_scope_bool(self):
        with self.assertRaises(ValueError):inspect_state_quality(snapshot(),session_id='s1',account_id='cra',account_generation=False,actor_id=777)
    def test_invalid_min_revision(self):
        with self.assertRaises(ValueError):review_state(minimum_revision=0)
    def test_non_dict_snapshot(self):
        with self.assertRaises(TypeError):review_state([])

class P9Integration(unittest.TestCase):
    def test_demo_is_research_only(self):
        result=quality_demo()
        self.assertEqual(result['journal']['events'],8)
        self.assertEqual(result['committed_historical_candidates'],0)
        self.assertFalse(result['synthetic_state']['authoritative'])
        self.assertEqual(result['synthetic_state']['missing_fields'],[])
        self.assertFalse(result['physical_input_sent'])
    def test_read_only_audit(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'states.sqlite3'
            with SQLiteFixtureJournal(path,reducer=apply_offline_event) as j:
                j.append_fixture(OfflineStateEvent('e1','s1','cra',2,'f1',1,'FIGHT_STARTED'))
                j.append_fixture(OfflineStateEvent('e2','s1','cra',2,'f1',2,'ACTOR_SEEN',actor_id=777))
            result=quality_audit(path,'s1',777)
            self.assertEqual(result['journal']['events'],2)
            self.assertFalse(result['quality']['actionable'])
            with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as j:
                self.assertEqual(j.audit()['events'],2)
    def test_same_snapshot_replay_audit(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'states.sqlite3'
            with SQLiteFixtureJournal(path,reducer=apply_offline_event) as writer:
                writer.append_fixture(OfflineStateEvent('e1','s1','cra',2,'f1',1,'FIGHT_STARTED'))
            with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as reader:
                checked=reader.audited_snapshot('s1')
                self.assertEqual(checked['audit']['events'],1)
                self.assertEqual(checked['snapshot']['revision'],1)
    def test_reader_snapshot_does_not_mix_writer_revisions(self):
        # Hold an explicit read transaction; a separate writer may commit on WAL.
        with TemporaryDirectory() as folder:
            path=Path(folder)/'states.sqlite3'
            with SQLiteFixtureJournal(path,reducer=apply_offline_event) as writer:
                writer.append_fixture(OfflineStateEvent('e1','s1','cra',2,'f1',1,'FIGHT_STARTED'))
                with SQLiteFixtureJournal(path,reducer=apply_offline_event,read_only=True) as reader:
                    reader.db.execute('BEGIN')
                    before=reader.audited_snapshot('s1')
                    writer.append_fixture(OfflineStateEvent('e2','s1','cra',2,'f1',2,'ACTOR_SEEN',actor_id=777))
                    after=reader.audited_snapshot('s1')
                    self.assertEqual(before['snapshot']['revision'],1)
                    self.assertEqual(after['snapshot']['revision'],1)
                    reader.db.execute('ROLLBACK')
                    latest=reader.audited_snapshot('s1')
                    self.assertEqual(latest['snapshot']['revision'],2)
    def test_invalid_snapshot_scope_rejected(self):
        with TemporaryDirectory() as folder:
            with SQLiteFixtureJournal(Path(folder)/'states.sqlite3',reducer=apply_offline_event) as journal:
                with self.assertRaises(ValueError):journal.audited_snapshot('')
    def test_audit_missing_session_explicit(self):
        with TemporaryDirectory() as folder:
            path=Path(folder)/'states.sqlite3'
            with SQLiteFixtureJournal(path,reducer=apply_offline_event) as j:
                j.append_fixture(OfflineStateEvent('e1','s1','cra',2,'f1',1,'FIGHT_STARTED'))
            report=quality_audit(path,'missing',777)
            self.assertIn('NO_SNAPSHOT',report['quality']['failures'])
    def test_package_does_not_invert_dependencies(self):
        source=(ROOT/'src/anka_canonical/qualification.py').read_text()
        state=(ROOT/'src/anka_live_state/quality.py').read_text()
        self.assertNotIn('anka_protocol',source)
        self.assertNotIn('anka_capture',source)
        for forbidden in ('anka_protocol','anka_capture','anka_canonical','anka_app','anka_execution'):
            self.assertNotIn(forbidden,state)
    def test_cli_quality_demo(self):
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')
        process=subprocess.run([sys.executable,'-m','anka_app.cli','quality-demo'],cwd=ROOT,env=env,
                               capture_output=True,text=True,timeout=20)
        self.assertEqual(process.returncode,0,process.stdout+process.stderr)
        self.assertIn('ANKA_STATUS=RESEARCH_AND_SYNTHETIC_ONLY',process.stdout)
        self.assertIn('CURRENT_BUILD_EVIDENCE_NOT_CERTIFIED',process.stdout)
    def test_start_remains_refused(self):
        env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src')
        p=subprocess.run([sys.executable,'-m','anka_app.cli','start'],cwd=ROOT,env=env,
                         capture_output=True,text=True,timeout=20)
        self.assertEqual(p.returncode,40,p.stdout)
        self.assertIn('START_WINDOWS_REQUIRED',p.stdout)

if __name__=='__main__':unittest.main()
