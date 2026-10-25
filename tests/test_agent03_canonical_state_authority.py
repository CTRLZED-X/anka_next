"""Chat 03 regressions for Canonical/Live-State authority invariants.

These tests are intentionally adversarial: stale epochs, invalid boundaries and
damaged provenance receipts must fail closed without mutating durable truth.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from anka_canonical.writer import CanonicalWriter, ExactReleaseAdmissionPolicy, CanonicalIntegrityError
from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import CandidateCanonicalBatch, DecoderCheckpointRef, WireEnvelopeRef
from anka_live_state.projector import StateProjector, LiveStateProjectionError


ADAPTER='adapter-agent03-r1'
BUILD='Dofus TEST-AGENT03'
CONN='conn-agent03'
ACCOUNT='acct-cra'
CLIENT='client-cra'


def evidence(tag:str)->EvidencePointer:
    digest=sha256(tag.encode()).hexdigest()
    return EvidencePointer(
        'evidence-'+digest[:32],
        'OBSERVED_EXTERNAL',
        'anka_protocol',
        'agent03:'+digest,
        digest,
        'AGENT03_TEST',
    )


def candidate(tag:str,kind:str,payload:dict[str,object],*,account=ACCOUNT,client=CLIENT,
              world_epoch=None,fight_epoch=None,turn_epoch=None)->CanonicalCandidate:
    digest=sha256(tag.encode()).hexdigest()[:32]
    encoded=tuple(
        (key,str(value).lower() if isinstance(value,bool) else str(value))
        for key,value in payload.items()
    )
    return CanonicalCandidate(
        'candidate-'+digest,
        kind,
        account,
        client,
        (evidence(tag),),
        encoded,
        world_epoch,
        fight_epoch,
        turn_epoch,
    )


def batch(n:int,*candidates,health='SEMANTIC_CANDIDATES')->CandidateCanonicalBatch:
    source=WireEnvelopeRef(
        'capture-agent03',
        CONN,
        1,
        n,
        'server_to_client',
        'COMPLETE',
        sha256(f'payload-{n}'.encode()).hexdigest(),
    )
    checkpoint=DecoderCheckpointRef(
        ADAPTER,
        BUILD,
        CONN,
        1,
        n,
        sha256(f'checkpoint-{n}'.encode()).hexdigest(),
    )
    return CandidateCanonicalBatch(
        f'batch-agent03-{n}',
        ADAPTER,
        BUILD,
        CONN,
        1,
        (source,),
        tuple(candidates),
        health,
        checkpoint,
    )


def fight_bootstrap(n=1):
    return batch(
        n,
        candidate(f'{n}-fight','FIGHT_STARTED',{'fight_id':'fight-1','map_id':200},fight_epoch=1),
        candidate(f'{n}-actor','ACTOR_SEEN',{'actor_id':41},fight_epoch=1),
        candidate(f'{n}-ap','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'AP','value':11},fight_epoch=1),
        candidate(f'{n}-mp','ACTOR_RESOURCE_ABSOLUTE',{'actor_id':41,'resource':'MP','value':6},fight_epoch=1),
    )


class Agent03AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/'canonical.sqlite3'
        self.projector=StateProjector()
        self.policy=ExactReleaseAdmissionPolicy(((ADAPTER,BUILD),))

    def tearDown(self):
        self.tmp.cleanup()

    def writer(self):
        return CanonicalWriter(self.path,projector=self.projector,admission_policy=self.policy)

    def test_wrong_fight_epoch_rolls_back_without_mutating_current_state(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            before=writer.snapshot(ACCOUNT).to_dict()
            with self.assertRaisesRegex(LiveStateProjectionError,'STATE_FIGHT_EPOCH_MISMATCH'):
                writer.commit_candidate_batch(batch(
                    2,
                    candidate('wrong-fight-hp','ACTOR_HP_ABSOLUTE',
                              {'actor_id':41,'value':90,'maximum':100},fight_epoch=2),
                ))
            self.assertEqual(writer.current_cursor(),4)
            self.assertEqual(writer.snapshot(ACCOUNT).to_dict(),before)

    def test_second_fight_start_cannot_overwrite_an_active_fight(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            with self.assertRaisesRegex(LiveStateProjectionError,'STATE_FIGHT_ALREADY_ACTIVE'):
                writer.commit_candidate_batch(batch(
                    2,
                    candidate('overlap-fight','FIGHT_STARTED',
                              {'fight_id':'fight-2','map_id':201},fight_epoch=2),
                ))
            snapshot=writer.snapshot(ACCOUNT)
            self.assertEqual(snapshot.fight_id.value,'fight-1')
            self.assertEqual(snapshot.fight_phase.value,'ACTIVE')
            self.assertEqual(writer.current_cursor(),4)

    def test_turn_epoch_jump_is_rejected(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            with self.assertRaisesRegex(LiveStateProjectionError,'STATE_TURN_EPOCH_MISMATCH'):
                writer.commit_candidate_batch(batch(
                    2,
                    candidate('jump-turn','TURN_STARTED',{'actor_id':41},
                              fight_epoch=1,turn_epoch=3),
                ))
            self.assertEqual(writer.snapshot(ACCOUNT).turn_epoch,0)

    def test_turn_scoped_absolute_values_are_bound_to_upcoming_turn(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            before=writer.snapshot(ACCOUNT).actors[0]
            self.assertEqual((before.ap.status,before.ap.turn_epoch),('KNOWN',1))
            self.assertEqual((before.mp.status,before.mp.turn_epoch),('KNOWN',1))
            writer.commit_candidate_batch(batch(
                2,
                candidate('turn-1','TURN_STARTED',{'actor_id':41},
                          fight_epoch=1,turn_epoch=1),
            ))
            after=writer.snapshot(ACCOUNT).actors[0]
            self.assertEqual((after.ap.status,after.ap.turn_epoch),('KNOWN',1))
            self.assertEqual((after.mp.status,after.mp.turn_epoch),('KNOWN',1))

    def test_old_turn_absolute_value_cannot_remain_known_in_new_turn(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            writer.commit_candidate_batch(batch(
                2,
                candidate('turn-1','TURN_STARTED',{'actor_id':41},
                          fight_epoch=1,turn_epoch=1),
            ))
            writer.commit_candidate_batch(batch(
                3,
                candidate('turn-end-1','TURN_ENDED',{'actor_id':41},
                          fight_epoch=1,turn_epoch=1),
            ))
            writer.commit_candidate_batch(batch(
                4,
                candidate('ap-next','ACTOR_RESOURCE_ABSOLUTE',
                          {'actor_id':41,'resource':'AP','value':12},
                          fight_epoch=1,turn_epoch=2),
            ))
            writer.commit_candidate_batch(batch(
                5,
                candidate('turn-2','TURN_STARTED',{'actor_id':41},
                          fight_epoch=1,turn_epoch=2),
            ))
            actor=writer.snapshot(ACCOUNT).actors[0]
            self.assertEqual((actor.ap.status,actor.ap.value,actor.ap.turn_epoch),('KNOWN',12,2))
            self.assertEqual(actor.mp.status,'STALE')

    def test_new_fight_resets_complete_looking_actor_state(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            writer.commit_candidate_batch(batch(
                2,
                candidate('hp','ACTOR_HP_ABSOLUTE',{'actor_id':41,'value':100,'maximum':100},fight_epoch=1),
                candidate('cell','ACTOR_CELL_OBSERVED',{'actor_id':41,'cell_id':315},fight_epoch=1),
                candidate('cooldowns','ACTOR_COOLDOWN_SNAPSHOT',{'actor_id':41,'cooldowns':'[[1001,2]]'},fight_epoch=1),
                candidate('ready','READY_OBSERVED',{'actor_id':41,'ready':True},fight_epoch=1),
            ))
            writer.commit_candidate_batch(batch(
                3,
                candidate('fight-end','FIGHT_ENDED',{},fight_epoch=1),
            ))
            writer.commit_candidate_batch(batch(
                4,
                candidate('fight-2','FIGHT_STARTED',{'fight_id':'fight-2','map_id':201},fight_epoch=2),
                candidate('fight-2-actor','ACTOR_SEEN',{'actor_id':41},fight_epoch=2),
            ))
            actor=writer.snapshot(ACCOUNT).actors[0]
            self.assertTrue(all(
                getattr(actor,name).status=='UNKNOWN'
                for name in ('cell','hp','max_hp','ap','mp','range','cooldowns','ready')
            ))

    def test_cross_client_state_cannot_contaminate_existing_account_snapshot(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
            with self.assertRaisesRegex(LiveStateProjectionError,'STATE_ACCOUNT_CLIENT_SCOPE_MISMATCH'):
                writer.commit_candidate_batch(batch(
                    2,
                    candidate('other-client','ACTOR_SEEN',{'actor_id':99},
                              client='client-cra-restarted',fight_epoch=1),
                ))
            self.assertEqual(writer.current_cursor(),4)
            self.assertEqual(writer.snapshot(ACCOUNT).client_instance_id,CLIENT)

    def test_deleted_batch_receipt_is_detected_on_reopen(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
        db=sqlite3.connect(self.path)
        db.execute('DELETE FROM canonical_batches')
        db.commit()
        db.close()
        with self.assertRaisesRegex(CanonicalIntegrityError,'CANONICAL_BATCH_COVERAGE_INVALID'):
            self.writer()

    def test_batch_release_metadata_tamper_is_detected_on_reopen(self):
        with self.writer() as writer:
            writer.commit_candidate_batch(fight_bootstrap())
        db=sqlite3.connect(self.path)
        db.execute("UPDATE canonical_batches SET adapter_release_id='adapter-tampered'")
        db.commit()
        db.close()
        with self.assertRaisesRegex(CanonicalIntegrityError,'CANONICAL_BATCH_EVENT_PROVENANCE_MISMATCH'):
            self.writer()


if __name__=='__main__':
    unittest.main()
