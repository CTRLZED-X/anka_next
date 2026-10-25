"""Composition-root bridge between Protocol's admission port and Canonical authority.

This module is deliberately in ``anka_app``: Protocol must not import concrete
Canonical and Canonical must not import concrete Protocol.  The bridge converts
Canonical outcomes into the stable ProtocolAdmissionDecision contract and, when an
observer is supplied, publishes only facts already proved by Canonical receipts.
"""
from __future__ import annotations

from anka_contracts.protocol import CandidateCanonicalBatch, ProtocolAdmissionDecision
from anka_canonical.writer import (
    CanonicalAdmissionRejected,
    CanonicalCommitUncertain,
    CanonicalError,
    CanonicalWriterFenced,
)


class CanonicalAdmissionAdapter:
    def __init__(self, writer, observer=None):
        self._writer = writer
        self._observer = observer

    def _record(self,name:str,*,batch:CandidateCanonicalBatch,severity='INFO',failure_code=None,
                canonical_cursor=None,evidence_class='DERIVED',payload=None)->None:
        if self._observer is None:return
        account=batch.candidates[0].account_id if batch.candidates else None
        try:
            self._observer.record(name,owner_system='anka_canonical',severity=severity,
                boundary='canonical.commit',failure_code=failure_code,account_id=account,
                canonical_cursor=canonical_cursor,protocol_build=batch.observed_client_build,
                span_id=('span-'+batch.batch_id[6:])[:64],evidence_class=evidence_class,
                payload={'batch_span_id':batch.batch_id,'candidate_count':len(batch.candidates),**(payload or {})})
        except Exception:
            pass

    def _publish_snapshot(self,batch:CandidateCanonicalBatch,canonical_cursor:int|None)->None:
        """Best-effort post-commit state evidence; never part of commit authority."""
        if self._observer is None or not batch.candidates:return
        account=batch.candidates[0].account_id
        try:
            snap=self._writer.snapshot(account)
            if snap is None:return
            actors=[]
            for actor in snap.actors:
                def value(proof):return proof.value if proof.status=='KNOWN' else None
                actors.append({'actor_id':actor.actor_id,'cell':value(actor.cell),'cell_status':actor.cell.status,
                    'hp':value(actor.hp),'hp_status':actor.hp.status,'ap':value(actor.ap),'ap_status':actor.ap.status,
                    'mp':value(actor.mp),'mp_status':actor.mp.status,'ready':value(actor.ready),'ready_status':actor.ready.status})
            self._observer.record('live_state.snapshot_published',owner_system='anka_live_state',
                boundary='live_state.post_commit_projection',account_id=account,
                fight_epoch=snap.fight_epoch if snap.fight_epoch>0 else None,turn_epoch=snap.turn_epoch,
                canonical_cursor=snap.canonical_cursor,canonical_revision=snap.snapshot_revision,
                protocol_build=batch.observed_client_build,span_id=('span-'+batch.batch_id[6:])[:64],
                evidence_class='AUTHORITY_COMMITTED',payload={'batch_span_id':batch.batch_id,
                    'snapshot_id':snap.snapshot_id,'semantic_sha256':snap.semantic_sha256,
                    'fight_phase':snap.fight_phase.value if snap.fight_phase.status=='KNOWN' else None,
                    'turn_owner':snap.turn_owner.value if snap.turn_owner.status=='KNOWN' else None,'actors':actors})
        except Exception as exc:
            try:
                self._observer.record('live_state.snapshot_publish_failed',owner_system='anka_live_state',severity='WARNING',
                    boundary='live_state.post_commit_projection',account_id=account,canonical_cursor=canonical_cursor,
                    protocol_build=batch.observed_client_build,span_id=('span-'+batch.batch_id[6:])[:64],
                    failure_code='LIVE_STATE_POST_COMMIT_OBSERVATION_FAILED',payload={'batch_span_id':batch.batch_id,'error_type':type(exc).__name__})
            except Exception:
                pass

    def admit_candidate_batch(self, batch: CandidateCanonicalBatch) -> ProtocolAdmissionDecision:
        try:
            receipt = self._writer.commit_candidate_batch(batch)
        except CanonicalCommitUncertain as exc:
            self._record('canonical.batch_commit_uncertain',batch=batch,severity='SAFETY',
                         failure_code=exc.receipt.reason_code or 'CANONICAL_COMMIT_UNCERTAIN',
                         canonical_cursor=exc.receipt.last_cursor,evidence_class='CONFLICTING',
                         payload={'status':'COMMIT_UNCERTAIN','receipt_reason':exc.receipt.reason_code})
            # Durable truth may already exist. Protocol MUST rollback speculative
            # decoder state and wait for Canonical reopen/reconciliation.
            return ProtocolAdmissionDecision('UNCERTAIN', reason_code=exc.receipt.reason_code or 'CANONICAL_COMMIT_UNCERTAIN')
        except CanonicalWriterFenced:
            self._record('canonical.batch_rejected',batch=batch,severity='SAFETY',failure_code='CANONICAL_WRITER_FENCED',evidence_class='MISSING')
            return ProtocolAdmissionDecision('UNCERTAIN', reason_code='CANONICAL_WRITER_FENCED')
        except CanonicalAdmissionRejected as exc:
            self._record('canonical.batch_rejected',batch=batch,severity='WARNING',failure_code=str(exc),evidence_class='DERIVED')
            return ProtocolAdmissionDecision('REJECTED', reason_code=str(exc))
        except CanonicalError as exc:
            code=str(exc) or type(exc).__name__
            self._record('canonical.batch_rejected',batch=batch,severity='WARNING',failure_code=code,evidence_class='DERIVED')
            return ProtocolAdmissionDecision('REJECTED', reason_code=code)
        except Exception:
            # Projection/validation failures are deterministic admission failures;
            # do not leak concrete Live-State exceptions back into Protocol.
            self._record('canonical.batch_rejected',batch=batch,severity='ERROR',failure_code='CANONICAL_VALIDATION_FAILED',evidence_class='DERIVED')
            return ProtocolAdmissionDecision('REJECTED', reason_code='CANONICAL_VALIDATION_FAILED')
        if receipt.status in ('COMMITTED','IDEMPOTENT_DUPLICATE'):
            self._record('canonical.batch_committed',batch=batch,canonical_cursor=receipt.last_cursor,
                         evidence_class='AUTHORITY_COMMITTED',payload={'status':receipt.status,'event_count':receipt.event_count,
                             'first_cursor':receipt.first_cursor,'last_cursor':receipt.last_cursor,
                             'decoder_checkpoint_sha256':receipt.decoder_checkpoint_sha256})
            self._publish_snapshot(batch,receipt.last_cursor)
            return ProtocolAdmissionDecision('COMMITTED', committed_cursor=receipt.last_cursor)
        if receipt.status == 'COMMIT_UNCERTAIN':
            self._record('canonical.batch_commit_uncertain',batch=batch,severity='SAFETY',canonical_cursor=receipt.last_cursor,
                         failure_code=receipt.reason_code or 'CANONICAL_COMMIT_UNCERTAIN',evidence_class='CONFLICTING')
            return ProtocolAdmissionDecision('UNCERTAIN', reason_code=receipt.reason_code or 'CANONICAL_COMMIT_UNCERTAIN')
        self._record('canonical.batch_rejected',batch=batch,severity='WARNING',
                     failure_code=receipt.reason_code or 'CANONICAL_NOT_COMMITTED')
        return ProtocolAdmissionDecision('REJECTED', reason_code=receipt.reason_code or 'CANONICAL_NOT_COMMITTED')
