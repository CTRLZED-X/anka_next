"""Chat 10 Issue #32 Phase A: shared Workflow authority/migration contracts."""
from __future__ import annotations

from dataclasses import asdict, replace
import unittest

from anka_app.workflow_persistence import (
    WORKFLOW_PERSISTENCE_SCHEMA_VERSION,
    admit_workflow_resume,
    admit_workflow_signal_tick,
    dump_workflow_signal,
    dump_workflow_snapshot,
    load_workflow_signal,
    load_workflow_snapshot,
    persist_workflow_signal_tick,
    prepare_recovery_outcome_signal,
)
from anka_contracts.workflow import (
    WorkflowSignal,
    WorkflowSnapshot,
    correlate_recovery_outcome,
    next_workflow_recovery_generation,
)


def snap(
    *,
    phase='WORLD',
    phase_started_tick=1,
    watchdog_deadline_tick=6,
    recovery_generation=2,
    active_recovery_generation=None,
    last_processed_tick=100,
    resume_phase=None,
    terminal_reason=None,
):
    return WorkflowSnapshot(
        run_id='run-issue32',
        phase=phase,
        fight_epoch=1,
        attempts=0,
        wins=0,
        losses=0,
        unknowns=0,
        aborted=0,
        route_index=0,
        pending_action_id=None,
        counted_fight_epochs=(),
        started_fight_epochs=(1,),
        processed_signal_ids=('wfsig-existing',),
        progress_generation=4,
        progress_token='a'*64,
        phase_started_tick=phase_started_tick,
        watchdog_deadline_tick=watchdog_deadline_tick,
        recovery_budget_remaining=1,
        resume_phase=resume_phase,
        expected_next_evidence=('ENCOUNTER_SELECTED',),
        terminal_reason=terminal_reason,
        goal_reached_pending_reentry=False,
        plan_id='missionplan-issue32',
        selected_encounter_id=None,
        selected_encounter_map_id=None,
        recovery_generation=recovery_generation,
        active_recovery_generation=active_recovery_generation,
        last_processed_tick=last_processed_tick,
    )


def recovering():
    return snap(
        phase='RECOVERING',
        phase_started_tick=90,
        watchdog_deadline_tick=105,
        recovery_generation=2,
        active_recovery_generation=2,
        last_processed_tick=100,
        resume_phase='READY',
    )


class TestRecoveryIdentityPhaseA(unittest.TestCase):
    def test_stale_success_a_after_b_starts_is_rejected_noncurrent(self):
        result=prepare_recovery_outcome_signal(
            recovering(),signal_id='wfsig-success-a',kind='RECOVERY_SUCCEEDED',
            monotonic_tick=101,recovery_generation=1,
        )
        self.assertEqual((result.admission.status,result.admission.reason,result.signal),
                         ('REJECTED','RECOVERY_OUTCOME_STALE_GENERATION',None))

    def test_stale_failure_a_after_b_starts_is_rejected_noncurrent(self):
        result=prepare_recovery_outcome_signal(
            recovering(),signal_id='wfsig-failure-a',kind='RECOVERY_FAILED',
            monotonic_tick=101,recovery_generation=1,
        )
        self.assertEqual((result.admission.status,result.admission.reason,result.signal),
                         ('REJECTED','RECOVERY_OUTCOME_STALE_GENERATION',None))

    def test_matching_success_and_failure_b_are_current(self):
        for kind in ('RECOVERY_SUCCEEDED','RECOVERY_FAILED'):
            result=prepare_recovery_outcome_signal(
                recovering(),signal_id=f'wfsig-{kind.lower()}',kind=kind,
                monotonic_tick=101,recovery_generation=2,
            )
            self.assertEqual(result.admission.status,'ALLOWED')
            self.assertEqual(result.signal.recovery_generation,2)
            self.assertEqual(correlate_recovery_outcome(recovering(),result.signal).disposition,'CURRENT')

    def test_duplicate_b_outcome_after_settlement_is_idempotent(self):
        settled=snap(phase='READY',phase_started_tick=101,watchdog_deadline_tick=106,
                     recovery_generation=2,active_recovery_generation=None,last_processed_tick=101)
        result=prepare_recovery_outcome_signal(
            settled,signal_id='wfsig-duplicate-b',kind='RECOVERY_SUCCEEDED',
            monotonic_tick=100,recovery_generation=2,
        )
        self.assertEqual((result.admission.status,result.admission.reason,result.signal),
                         ('IDEMPOTENT','RECOVERY_OUTCOME_ALREADY_NONCURRENT',None))

    def test_future_recovery_generation_is_rejected(self):
        result=prepare_recovery_outcome_signal(
            recovering(),signal_id='wfsig-future',kind='RECOVERY_SUCCEEDED',
            monotonic_tick=101,recovery_generation=3,
        )
        self.assertEqual((result.admission.status,result.admission.reason),
                         ('REJECTED','RECOVERY_OUTCOME_FUTURE_GENERATION'))

    def test_wrong_recovery_producer_kind_fails_closed(self):
        result=prepare_recovery_outcome_signal(
            recovering(),signal_id='wfsig-wrong-kind',kind='HEARTBEAT',
            monotonic_tick=101,recovery_generation=None,
        )
        self.assertEqual(result.admission.status,'REJECTED')
        self.assertIn('WORKFLOW_RECOVERY_OUTCOME_REQUIRED',result.admission.reason)

    def test_missing_recovery_identity_fails_closed(self):
        result=prepare_recovery_outcome_signal(
            recovering(),signal_id='wfsig-missing-id',kind='RECOVERY_SUCCEEDED',
            monotonic_tick=101,recovery_generation=None,
        )
        self.assertEqual((result.admission.status,result.admission.reason,result.signal),
                         ('REJECTED','RECOVERY_IDENTITY_MISSING',None))

    def test_next_recovery_generation_is_monotonic_and_unproven_fails_closed(self):
        self.assertEqual(next_workflow_recovery_generation(recovering()),3)
        with self.assertRaisesRegex(ValueError,'RECOVERY_GENERATION_UNPROVEN'):
            next_workflow_recovery_generation(replace(snap(),recovery_generation=None))

    def test_recovery_signal_contract_rejects_invalid_or_extraneous_generation(self):
        with self.assertRaisesRegex(ValueError,'INVALID_WORKFLOW_RECOVERY_GENERATION'):
            WorkflowSignal('wfsig-bad-zero','RECOVERY_SUCCEEDED',1,recovery_generation=0)
        with self.assertRaisesRegex(ValueError,'INVALID_WORKFLOW_RECOVERY_GENERATION'):
            WorkflowSignal('wfsig-bad-bool','RECOVERY_SUCCEEDED',1,recovery_generation=True)
        with self.assertRaisesRegex(ValueError,'EXTRANEOUS'):
            WorkflowSignal('wfsig-bad-kind','HEARTBEAT',1,recovery_generation=1)

    def test_persistence_roundtrip_preserves_active_identity(self):
        original=recovering()
        payload=dump_workflow_snapshot(original)
        self.assertEqual(payload['schema_version'],WORKFLOW_PERSISTENCE_SCHEMA_VERSION)
        loaded=load_workflow_snapshot(payload)
        self.assertEqual(loaded.classification,'SAFE')
        self.assertTrue(loaded.resume_authorized)
        self.assertEqual(loaded.snapshot,original)
        self.assertEqual(loaded.snapshot.active_recovery_generation,2)

    def test_old_recovering_snapshot_cannot_invent_active_identity(self):
        legacy=asdict(recovering())
        for name in ('recovery_generation','active_recovery_generation','last_processed_tick'):
            legacy.pop(name)
        loaded=load_workflow_snapshot(legacy)
        self.assertEqual(loaded.classification,'INCOMPATIBLE')
        self.assertFalse(loaded.resume_authorized)
        self.assertIn('LEGACY_ACTIVE_RECOVERY_IDENTITY_UNPROVEN',loaded.reasons)

    def test_legacy_nonrecovery_snapshot_is_ambiguous_not_authoritative(self):
        legacy=asdict(snap())
        for name in ('recovery_generation','active_recovery_generation','last_processed_tick'):
            legacy.pop(name)
        loaded=load_workflow_snapshot(legacy)
        self.assertEqual(loaded.classification,'AMBIGUOUS')
        self.assertFalse(loaded.resume_authorized)
        self.assertIsNone(loaded.snapshot.last_processed_tick)

    def test_pristine_legacy_created_snapshot_has_only_safe_zero_upgrade(self):
        created=snap(
            phase='CREATED',phase_started_tick=0,watchdog_deadline_tick=None,
            recovery_generation=None,active_recovery_generation=None,last_processed_tick=None,
        )
        legacy=asdict(replace(
            created,fight_epoch=0,started_fight_epochs=(),processed_signal_ids=(),
            progress_generation=0,resume_phase=None,expected_next_evidence=('START',),
        ))
        for name in ('recovery_generation','active_recovery_generation','last_processed_tick'):
            legacy.pop(name)
        loaded=load_workflow_snapshot(legacy)
        self.assertEqual(loaded.classification,'SAFE')
        self.assertTrue(loaded.resume_authorized)
        self.assertEqual((loaded.snapshot.recovery_generation,loaded.snapshot.last_processed_tick),(0,0))


class TestTemporalWatermarkPhaseA(unittest.TestCase):
    def test_tick1_accepted100_snapshot_resume50_rejected(self):
        world=snap(phase_started_tick=1,last_processed_tick=100)
        admission=admit_workflow_resume(world,50)
        self.assertEqual((admission.status,admission.reason),('REJECTED','RESUME_TICK_BELOW_WATERMARK'))

    def test_resume_at_or_above_watermark_is_allowed(self):
        world=snap(last_processed_tick=100)
        for tick in (100,101,1000):
            self.assertEqual(admit_workflow_resume(world,tick).status,'ALLOWED')

    def test_post_resume_signal_below_watermark_rejects(self):
        world=snap(last_processed_tick=100)
        self.assertEqual(admit_workflow_signal_tick(world,99).reason,'SIGNAL_TICK_BELOW_WATERMARK')
        self.assertEqual(admit_workflow_signal_tick(world,100).status,'ALLOWED')

    def test_accepted_signal_advances_watermark_rejected_signal_does_not(self):
        world=snap(last_processed_tick=100)
        rejected=persist_workflow_signal_tick(world,120,accepted=False)
        self.assertIs(rejected,world)
        accepted=persist_workflow_signal_tick(world,120,accepted=True)
        self.assertEqual(accepted.last_processed_tick,120)
        self.assertEqual(world.last_processed_tick,100)

    def test_watermark_is_independent_from_new_resume_watchdog_origin(self):
        resumed=snap(phase_started_tick=150,watchdog_deadline_tick=155,last_processed_tick=100)
        self.assertEqual(resumed.last_processed_tick,100)
        self.assertEqual(admit_workflow_resume(resumed,150).status,'ALLOWED')
        advanced=persist_workflow_signal_tick(resumed,151,accepted=True)
        self.assertEqual(advanced.last_processed_tick,151)
        self.assertEqual(advanced.phase_started_tick,150)
        self.assertEqual(advanced.watchdog_deadline_tick,155)

    def test_nonprogress_persistence_does_not_refresh_watchdog(self):
        world=snap(last_processed_tick=100,watchdog_deadline_tick=6)
        updated=persist_workflow_signal_tick(world,120,accepted=True)
        self.assertEqual(updated.watchdog_deadline_tick,world.watchdog_deadline_tick)
        self.assertEqual(updated.phase_started_tick,world.phase_started_tick)
        self.assertEqual(updated.progress_generation,world.progress_generation)

    def test_watermark_never_regresses(self):
        with self.assertRaisesRegex(ValueError,'WORKFLOW_TICK_BELOW_WATERMARK'):
            persist_workflow_signal_tick(snap(last_processed_tick=100),99,accepted=True)

    def test_resume_fails_closed_when_watermark_or_generation_unproven(self):
        self.assertEqual(
            admit_workflow_resume(replace(snap(),last_processed_tick=None),100).reason,
            'WORKFLOW_WATERMARK_UNPROVEN',
        )
        self.assertEqual(
            admit_workflow_resume(replace(snap(),recovery_generation=None),100).reason,
            'RECOVERY_GENERATION_UNPROVEN',
        )


class TestPersistenceMigrationPhaseA(unittest.TestCase):
    def test_current_snapshot_and_recovery_signal_roundtrip(self):
        snapshot_result=load_workflow_snapshot(dump_workflow_snapshot(recovering()))
        self.assertEqual(snapshot_result.snapshot,recovering())
        signal=WorkflowSignal(
            'wfsig-roundtrip','RECOVERY_FAILED',101,('evidence-r',),recovery_generation=2
        )
        signal_result=load_workflow_signal(dump_workflow_signal(signal))
        self.assertEqual((signal_result.classification,signal_result.authoritative),('SAFE',True))
        self.assertEqual(signal_result.signal,signal)

    def test_current_schema_missing_authority_fields_is_incompatible(self):
        payload=dump_workflow_snapshot(snap())
        del payload['snapshot']['last_processed_tick']
        loaded=load_workflow_snapshot(payload)
        self.assertEqual(loaded.classification,'INCOMPATIBLE')
        self.assertFalse(loaded.resume_authorized)

    def test_invalid_schema_versions_fail_closed(self):
        payload=dump_workflow_snapshot(snap())
        payload['schema_version']=True
        loaded=load_workflow_snapshot(payload)
        self.assertEqual(loaded.classification,'INCOMPATIBLE')
        signal_payload=dump_workflow_signal(WorkflowSignal('wfsig-current','HEARTBEAT',10))
        signal_payload['schema_version']=0
        signal_loaded=load_workflow_signal(signal_payload)
        self.assertEqual(signal_loaded.classification,'INCOMPATIBLE')

    def test_invalid_types_are_incompatible_not_coerced(self):
        payload=dump_workflow_snapshot(snap())
        payload['snapshot']['last_processed_tick']=True
        loaded=load_workflow_snapshot(payload)
        self.assertEqual(loaded.classification,'INCOMPATIBLE')
        self.assertIsNone(loaded.snapshot)

    def test_legacy_nonrecovery_signal_is_parseable_but_not_current_authority(self):
        legacy={
            'signal_id':'wfsig-legacy-heartbeat',
            'kind':'HEARTBEAT',
            'monotonic_tick':10,
            'evidence_ids':[],
        }
        loaded=load_workflow_signal(legacy)
        self.assertEqual(loaded.classification,'AMBIGUOUS')
        self.assertFalse(loaded.authoritative)
        self.assertEqual(loaded.signal.kind,'HEARTBEAT')
        self.assertIn('LEGACY_SIGNAL_AUTHORITY_UNPROVEN',loaded.reasons)

    def test_legacy_recovery_signal_never_gets_manufactured_identity(self):
        legacy={
            'signal_id':'wfsig-legacy-recovery',
            'kind':'RECOVERY_SUCCEEDED',
            'monotonic_tick':10,
            'evidence_ids':[],
        }
        loaded=load_workflow_signal(legacy)
        self.assertEqual(loaded.classification,'INCOMPATIBLE')
        self.assertFalse(loaded.authoritative)
        self.assertIsNone(loaded.signal.recovery_generation)

    def test_dump_refuses_to_stamp_current_schema_over_incomplete_authority(self):
        with self.assertRaisesRegex(ValueError,'AUTHORITY_INCOMPLETE'):
            dump_workflow_snapshot(replace(snap(),last_processed_tick=None))
        with self.assertRaisesRegex(ValueError,'RECOVERY_IDENTITY_REQUIRED'):
            dump_workflow_signal(WorkflowSignal('wfsig-no-id','RECOVERY_FAILED',10))

    def test_snapshot_contract_rejects_mismatched_active_generation(self):
        with self.assertRaisesRegex(ValueError,'ACTIVE_RECOVERY_GENERATION_MISMATCH'):
            replace(recovering(),active_recovery_generation=1)
        with self.assertRaisesRegex(ValueError,'ACTIVE_RECOVERY_GENERATION_MISMATCH'):
            replace(recovering(),phase='READY')


if __name__=='__main__':
    unittest.main()
