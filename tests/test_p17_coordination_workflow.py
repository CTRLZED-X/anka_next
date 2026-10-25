"""P17 adversarial evidence and fail-closed research lifecycle tests."""
from __future__ import annotations
from dataclasses import replace
from unittest import TestCase
from pathlib import Path
from contextlib import redirect_stdout
import io
from anka_contracts.coordination_flow import PartyMember,PartyFixtureEvent,PartyTimelineReport
from anka_contracts.workflow_flow import SyntheticFightOutcome,MissionResearchReport
from anka_coordination.party_lifecycle import replay_party,PartyFixtureRejected
from anka_workflow.mission_research import evaluate_mission
from anka_app.coordination_offline import coordination_demo

M=(PartyMember('cra',1,777,'leader'),PartyMember('enu',1,888,'follower'))

def e(i,kind,who=None,tick=None,fight='fight-1'):
    kw={'account_id':who,'actor_id':777 if who=='cra' else 888,'generation':1} if who else {}
    if kind in ('FIGHT_STARTED','TURN_STARTED','END_TURN_INTENDED','TURN_ENDED','FIGHT_ENDED'):
        kw['fight_id']=fight
    return PartyFixtureEvent(i,i if tick is None else tick,kind,f'event-{i}',**kw)

def base():
    return (e(1,'READY','cra'),e(2,'READY','enu'),e(3,'FIGHT_STARTED'),
            e(4,'TURN_STARTED','cra'),e(5,'END_TURN_INTENDED','cra'),
            e(6,'TURN_ENDED','cra'),e(7,'TURN_STARTED','enu'),e(8,'FIGHT_ENDED'))

class TestLifecycle(TestCase):
    def test_happy_fixture_with_no_authority(self):
        r=replay_party(M,base())
        self.assertEqual((r.status,r.turn_owner,r.fight_id,r.first_failed_sequence),('FINISHED',None,'fight-1',None))
        self.assertFalse(r.to_dict()['actionable']);self.assertIsNone(r.to_dict()['selected_action'])
    def test_ready_is_not_turn_owner(self):
        r=replay_party(M,base()[:2])
        self.assertEqual((r.status,r.turn_owner),('WAIT_FIGHT',None))
    def test_only_one_account_ready(self):
        self.assertEqual(replay_party(M,base()[:1]).status,'WAIT_READY')
    def test_fight_start_requires_both_ready(self):
        r=replay_party(M,(e(1,'READY','cra'),e(2,'FIGHT_STARTED',tick=2)))
        self.assertEqual(r.reasons,('P17_FIGHT_BEFORE_ALL_READY',));self.assertEqual(r.first_failed_sequence,2)
    def test_turn_started_without_fight_quarantined(self):
        r=replay_party(M,(e(1,'TURN_STARTED','cra'),))
        self.assertEqual(r.reasons,('P17_OVERLAPPING_OR_EARLY_TURN',))
    def test_end_turn_intent_does_not_confirm_end(self):
        r=replay_party(M,base()[:5])
        self.assertEqual((r.status,r.turn_owner,r.pending_end_actor),('WAIT_TURN_END',777,777))
    def test_unobserved_handoff_blocked(self):
        es=base()[:5]+(e(6,'TURN_STARTED','enu'),)
        r=replay_party(M,es)
        self.assertEqual((r.first_failed_sequence,r.reasons),(6,('P17_OVERLAPPING_OR_EARLY_TURN',)))
    def test_wrong_actor_end_turn_request(self):
        es=base()[:4]+(e(5,'END_TURN_INTENDED','enu'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_END_INTENT_NOT_OWNER',))
    def test_end_without_pending_intent(self):
        es=base()[:4]+(e(5,'TURN_ENDED','cra'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_UNCONFIRMED_OR_WRONG_TURN_END',))
    def test_end_wrong_owner(self):
        es=base()[:5]+(e(6,'TURN_ENDED','enu'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_UNCONFIRMED_OR_WRONG_TURN_END',))
    def test_end_turn_stall_timeout(self):
        es=base()[:5]+(e(6,'CHECK',tick=10),)
        self.assertEqual(replay_party(M,es).reasons,('P17_TURN_END_UNCONFIRMED',))
    def test_missing_first_turn_timeout(self):
        es=base()[:3]+(e(4,'CHECK',tick=9),)
        self.assertEqual(replay_party(M,es).reasons,('P17_FIRST_TURN_TIMEOUT',))
    def test_missing_next_turn_timeout(self):
        es=base()[:6]+(e(7,'CHECK',tick=12),)
        self.assertEqual(replay_party(M,es).reasons,('P17_NEXT_TURN_TIMEOUT',))
    def test_missing_fight_start_timeout(self):
        es=base()[:2]+(e(3,'CHECK',tick=9),)
        self.assertEqual(replay_party(M,es).reasons,('P17_FIGHT_START_TIMEOUT',))
    def test_timeout_at_event_even_without_check(self):
        es=base()[:5]+(e(6,'TURN_ENDED','cra',tick=15),)
        self.assertEqual(replay_party(M,es).reasons,('P17_TURN_END_UNCONFIRMED',))
    def test_exact_timeout_boundary_accepted(self):
        es=base()[:5]+(e(6,'TURN_ENDED','cra',tick=9),)
        self.assertEqual(replay_party(M,es).status,'WAIT_NEXT_TURN')
    def test_timeout_integer_type_rejected(self):
        for t in (True,0,-1,1001,1.4):
            with self.assertRaises(PartyFixtureRejected):replay_party(M,(),wait_ticks=t)
    def test_duplicate_ready(self):
        es=base()[:1]+(e(2,'READY','cra'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_READY_PHASE_OR_DUPLICATE',))
    def test_stale_generation(self):
        es=base()[:1]+(replace(e(2,'READY','enu'),generation=2),)
        self.assertEqual(replay_party(M,es).reasons,('P17_ACCOUNT_GENERATION_OR_ACTOR_MISMATCH',))
    def test_fight_epoch_mismatch(self):
        es=base()[:3]+(e(4,'TURN_STARTED','cra',fight='fight-other'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_FIGHT_EPOCH_CONFLICT',))
    def test_disconnect_never_auto_resume(self):
        es=base()[:4]+(e(5,'DISCONNECTED','enu'), e(6,'END_TURN_INTENDED','cra'))
        r=replay_party(M,es)
        self.assertEqual((r.first_failed_sequence,r.last_sequence),(5,5))
        self.assertEqual(r.reasons,('P17_PARTY_DISCONNECTED',))
    def test_end_of_fight_without_turn_end_permitted(self):
        # Victory can end a fight mid-turn, but does NOT certify the outcome.
        es=base()[:4]+(e(5,'FIGHT_ENDED'),)
        self.assertEqual(replay_party(M,es).status,'FINISHED')
    def test_finish_then_more_turn_quarantined(self):
        es=base()+(e(9,'TURN_STARTED','enu'),)
        self.assertEqual(replay_party(M,es).reasons,('P17_EVENT_AFTER_TERMINAL_STATE',))
    def test_duplicate_message_identity_rejected(self):
        es=base()[:1]+(replace(e(2,'READY','enu'),event_id='event-1'),)
        with self.assertRaisesRegex(PartyFixtureRejected,'DUPLICATE'):
            replay_party(M,es)
    def test_gap_reorder_clock_rejected(self):
        for es in (base()[:1]+(e(3,'READY','enu'),),
                   (e(1,'READY','cra',tick=3),e(2,'READY','enu',tick=2))):
            with self.assertRaises(PartyFixtureRejected):replay_party(M,es)
    def test_reject_invalid_party(self):
        for party in ((),M[:1],(M[0],M[0]),(M[0],replace(M[1],actor_id=777)),
                      (replace(M[0],role='follower'),M[1])):
            with self.assertRaises(PartyFixtureRejected):replay_party(tuple(party),())
    def test_reject_malformed_events(self):
        for kw in ({'generation':True},{'actor_id':0},{'account_id':'bad name'}):
            with self.assertRaises(ValueError):replace(e(1,'READY','cra'),**kw)
    def test_reject_extraneous_data(self):
        with self.assertRaises(ValueError):replace(e(1,'READY','cra'),fight_id='fight-1')
        with self.assertRaises(ValueError):replace(e(3,'FIGHT_STARTED'),account_id='cra')
    def test_overflow_rejected(self):
        with self.assertRaises(PartyFixtureRejected):replay_party(M,tuple(e(i,'CHECK') for i in range(1,514)))
    def test_authority_forgery_rejected(self):
        r=replay_party(M,())
        for field in ('actionable','authoritative','physical_input_permitted'):
            with self.assertRaisesRegex(ValueError,'AUTHORITY_FORGERY'):replace(r,**{field:True})
        with self.assertRaises(ValueError):replace(r,synthetic_only=False)

class TestAdditionalFailureModes(TestCase):
    def test_late_first_turn_without_check_fails(self):
        seq=base()[:3]+(e(4,'TURN_STARTED','cra',tick=20),)
        self.assertEqual(replay_party(M,seq).reasons,('P17_FIRST_TURN_TIMEOUT',))
    def test_ambiguous_duplicated_turn_start(self):
        seq=base()[:4]+(e(5,'TURN_STARTED','cra'),)
        self.assertEqual(replay_party(M,seq).reasons,('P17_OVERLAPPING_OR_EARLY_TURN',))
    def test_replay_deterministic_and_does_not_mutate_input(self):
        seq=base()
        a=replay_party(M,seq);b=replay_party(M,seq)
        self.assertEqual(a.to_dict(),b.to_dict())
        self.assertEqual(seq,base())
    def test_independent_dependency_boundaries(self):
        import ast,inspect,anka_coordination.party_lifecycle as coordination
        import anka_workflow.mission_research as workflow
        for module in (coordination,workflow):
            tree=ast.parse(inspect.getsource(module))
            modules={node.module or '' for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
            for forbidden in ('anka_capture','anka_protocol','anka_execution','anka_game_kernel','anka_app'):
                self.assertFalse(any(x==forbidden or x.startswith(forbidden+'.') for x in modules))
    def test_diagnostics_bundle_for_stall_is_valid(self):
        from tempfile import TemporaryDirectory
        from anka_observability.api import LocalDiagnostics
        from anka_observability.bundle import verify_incident
        with TemporaryDirectory() as tmp:
            observer=LocalDiagnostics(Path(tmp))
            result=coordination_demo(observer=observer,scenario='missing-end-confirmation')
            self.assertEqual(result['status'],'QUARANTINED')
            self.assertTrue(Path(result['incident_bundle']).is_file())
            self.assertEqual(verify_incident(Path(result['incident_bundle']))['status'],'PASS')

class TestWorkflow(TestCase):
    def test_fight_end_not_proof_of_win(self):
        r=evaluate_mission((replay_party(M,base()),),())
        self.assertEqual(r.status,'BLOCKED_SYNTHETIC')
        self.assertIn('P17_FIGHT_END_NOT_VICTORY_PROOF',r.reasons)
    def test_outcome_separate_from_coordination(self):
        r=evaluate_mission((replay_party(M,base()),),(SyntheticFightOutcome('fight-1','VICTORY','o1'),))
        self.assertEqual(r.status,'SYNTHETIC_TARGET_REACHED');self.assertFalse(r.actionable)
    def test_ongoing_fight_does_not_count(self):
        r=evaluate_mission((replay_party(M,base()[:4]),),())
        self.assertEqual((r.status,r.unresolved_fights),('WAITING_FOR_SYNTHETIC_EVIDENCE',1))
    def test_cannot_claim_outcome_during_fight(self):
        r=evaluate_mission((replay_party(M,base()[:4]),),(SyntheticFightOutcome('fight-1','VICTORY','o1'),))
        self.assertIn('P17_OUTCOME_BEFORE_FIGHT_END',r.reasons)
    def test_invalid_policy_or_orphan_or_duplicate(self):
        p=replay_party(M,base());o=SyntheticFightOutcome('fight-1','VICTORY','o1')
        for n in (True,0,101):
            with self.assertRaises(ValueError):evaluate_mission((p,),(o,),target_wins=n)
        with self.assertRaises(ValueError):evaluate_mission((p,), (o,o))
        with self.assertRaises(ValueError):evaluate_mission((p,), (SyntheticFightOutcome('other','VICTORY','o2'),))
    def test_loss_budget_enforced(self):
        r=evaluate_mission((replay_party(M,base()),),(SyntheticFightOutcome('fight-1','DEFEAT','o1'),),max_losses=0)
        self.assertIn('P17_LOSS_BUDGET_EXCEEDED',r.reasons)
    def test_workflow_does_not_import_implementation(self):
        import anka_workflow.mission_research as mod
        self.assertNotIn('anka_coordination',mod.__dict__)
    def test_workflow_authority_forgery_rejected(self):
        r=evaluate_mission((),())
        for field in ('actionable','authoritative'):
            with self.assertRaisesRegex(ValueError,'FORGERY'):replace(r,**{field:True})

class TestComposition(TestCase):
    def test_synthetic_demo_and_blocked_failures(self):
        for scenario,status in [('handoff','FINISHED'),('missing-end-confirmation','QUARANTINED'),
                                ('overlapping-owner','QUARANTINED'),('missing-next-owner','QUARANTINED')]:
            report=coordination_demo(scenario=scenario)
            self.assertEqual(report['status'],status)
            self.assertFalse(report['physical_input_sent'])
    def test_cli_exit_codes_and_passive_bundle(self):
        from anka_app.cli import main
        for scenario,code in [('handoff',0),('missing-end-confirmation',10)]:
            output=io.StringIO()
            with redirect_stdout(output):rc=main(['coordination-demo',scenario])
            self.assertEqual(rc,code)
            self.assertIn('ANKA_RESULT=',output.getvalue())
        self.assertIn('ANKA_STATUS=QUARANTINED',output.getvalue())
