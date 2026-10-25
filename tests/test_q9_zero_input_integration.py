from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import ast, unittest

from anka_app.zero_input_integration import ZeroInputQ9Scenario, CRA, ENU, PARTY, Q9_BUILD


class Q9Base(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s=ZeroInputQ9Scenario(Path(self.tmp.name))
        self.addCleanup(self.s.close)


class TestQ9ZeroInputIntegration(Q9Base):
    def test_full_cra_enu_world_fight_world_lifecycle_completes(self):
        result=self.s.happy_path()
        self.assertEqual((result.status,result.final_phase,result.attempts,result.wins),('PASS','COMPLETED',1,1))
        # 2 world moves + leader START_FIGHT + follower JOIN + 2 placement +
        # 2 Ready + CRA CAST + CRA END_TURN + ENU CAST. Every external phase
        # now crosses Decision→authority→Execution and settles from newer evidence.
        self.assertEqual(result.driver_calls,11)
        self.assertEqual(result.physical_input_count,0)
        self.assertEqual(result.execution_actions,11)
        self.assertGreaterEqual(result.canonical_events,30)

    def test_end_turn_stays_pending_until_both_views_prove_new_owner(self):
        s=self.s;s.prepare_first_turn();s._run_action(CRA)
        base=s._frame(CRA);first=s.planner.plan(base)
        from dataclasses import replace
        frame=replace(base,frame_id=base.frame_id+'-manual-end',quarantined_action_keys=(first.plan.action_key,))
        dispatch=s.controller.request(PARTY,frame)
        self.assertEqual((dispatch.status,dispatch.outcome_status),('SUBMITTED','PENDING'))
        self.assertEqual(s.ledger.get_command(dispatch.action_id).kind,'END_TURN')
        self.assertFalse(s.coord.turn_permit(PARTY,ENU[0]).allowed)
        # CRA alone sees ENU owner: still no party permit and action is unsettled.
        s.feed.push(CRA[0],(('TURN_ENDED',{'actor_id':CRA[2]},None,1,1),('TURN_STARTED',{'actor_id':ENU[2]},None,1,2)))
        s._coord_obs(CRA,'TURN')
        self.assertFalse(s.coord.turn_permit(PARTY,ENU[0]).allowed)
        self.assertEqual(s.ledger.get(dispatch.action_id).status,'PENDING')

    def test_canonical_state_replay_matches_durable_projection_after_full_run(self):
        self.s.happy_path()
        for account in (CRA[0],ENU[0]):
            with self.subTest(account=account):
                current=self.s.feed.snapshot(account)
                replayed=self.s.feed.writer.replay(account)
                self.assertEqual(replayed.to_dict(),current.to_dict())
        self.assertEqual(self.s.feed.writer.audit()['status'],'PASS')

    def test_q9_is_explicit_synthetic_build_and_fake_driver_only(self):
        self.assertIn('SYNTHETIC',Q9_BUILD)
        self.assertEqual(self.s.driver.mode,'FAKE_ONLY')
        self.s.prepare_first_turn()
        self.assertEqual(self.s.execution.physical_input_count,0)

    def test_one_account_missing_ready_blocks_party_and_driver(self):
        s=self.s
        s._signal('START');s._signal('PREFLIGHT_OK')
        for acct in (CRA,ENU):s._bootstrap_account(acct)
        s._signal('ENCOUNTER_SELECTED');s._signal('FIGHT_ENTRY_PROVEN',fight_epoch=1)
        for acct in (CRA,ENU):s._coord_obs(acct,'JOIN')
        s._signal('PARTY_JOIN_PROVEN',fight_epoch=1)
        for acct in (CRA,ENU):s._refresh_cell(acct);s._coord_obs(acct,'PLACEMENT')
        s._signal('PLACEMENT_PROVEN',fight_epoch=1)
        s._ready(CRA);s._coord_obs(CRA,'READY')
        snap=s.coord.snapshot()
        self.assertFalse(snap.ready_barrier.satisfied)
        self.assertIn(ENU[0],snap.ready_barrier.missing_accounts)
        permit=s.coord.turn_permit(PARTY,CRA[0])
        self.assertFalse(permit.allowed);self.assertEqual(permit.reason,'READY_BARRIER_UNSATISFIED')
        self.assertEqual(s.driver.call_count,0);self.assertEqual(s.execution.physical_input_count,0)

    def test_enu_cannot_act_during_cross_account_handoff_skew(self):
        s=self.s;s.prepare_first_turn();s._run_action(CRA)
        # Only CRA has observed the new owner. ENU still reports the old turn.
        s.feed.push(CRA[0],(
            ('TURN_ENDED',{'actor_id':CRA[2]},None,1,1),
            ('TURN_STARTED',{'actor_id':ENU[2]},None,1,2),
        ));s._coord_obs(CRA,'TURN')
        permit=s.coord.turn_permit(PARTY,ENU[0])
        self.assertFalse(permit.allowed)
        before=s.driver.call_count
        dispatch=s.controller.request(PARTY,s._frame(ENU))
        self.assertEqual(dispatch.status,'WAIT');self.assertEqual(s.driver.call_count,before)
        # Once ENU observes the same authoritative owner, the barrier converges.
        s.feed.push(ENU[0],(
            ('TURN_ENDED',{'actor_id':CRA[2]},None,1,1),
            ('TURN_STARTED',{'actor_id':ENU[2]},None,1,2),
        ));s._coord_obs(ENU,'TURN')
        self.assertTrue(s.coord.turn_permit(PARTY,ENU[0]).allowed)

    def test_ambiguous_external_boundary_blocks_workflow_without_retry(self):
        # Keep the base scenario intact and exercise ambiguity in an independent run directory.
        # This avoids cleanup-order coupling and makes this failure case reproducible in isolation.
        s=ZeroInputQ9Scenario(Path(self.tmp.name)/'ambiguous',driver_scenario='sent')
        try:
            s.prepare_first_turn();before=s.driver.call_count;s.driver.scenario='may-have-sent';frame=s._frame(CRA);dispatch=s.controller.request(PARTY,frame)
            self.assertEqual((dispatch.status,dispatch.outcome_status),('SUBMITTED','UNCERTAIN'))
            s._signal('ACTION_SUBMITTED',fight_epoch=1,action_id=dispatch.action_id)
            out=s._signal('ACTION_OUTCOME',fight_epoch=1,action_id=dispatch.action_id,action_status='UNCERTAIN')
            self.assertEqual(out.snapshot.phase,'BLOCKED')
            self.assertEqual(out.snapshot.terminal_reason,'UNRESOLVED_ACTION_SIDE_EFFECT')
            self.assertEqual(s.driver.call_count,before+1);self.assertEqual(s.execution.physical_input_count,0)
        finally:
            s.close()

    def test_action_settlement_requires_canonical_consequence_and_is_not_click_success(self):
        s=self.s;s.prepare_first_turn();frame=s._frame(CRA);dispatch=s.controller.request(PARTY,frame)
        self.assertEqual(dispatch.outcome_status,'PENDING')
        action=s.ledger.get(dispatch.action_id)
        self.assertEqual(action.status,'PENDING')
        self.assertEqual(s.execution.physical_input_count,0)

    def test_no_windows_input_primitive_is_reachable_from_q9_harness(self):
        path=Path(__file__).resolve().parents[1]/'src/anka_app/zero_input_integration.py'
        tree=ast.parse(path.read_text())
        imports=[]
        for n in ast.walk(tree):
            if isinstance(n,ast.Import):imports += [a.name for a in n.names]
            elif isinstance(n,ast.ImportFrom):imports.append(n.module or '')
        self.assertFalse([x for x in imports if 'windows_input' in x or x in ('ctypes','pyautogui','pynput')])
        source=path.read_text()
        for primitive in ('SetCursorPos','mouse_event','SendInput','pyautogui','pynput'):
            self.assertNotIn(primitive,source)


if __name__=='__main__': unittest.main()
