"""Transactional Protocol runtime boundary.

Protocol can mutate decoder context while *proposing* semantics, but trusted
runtime context advances only when Canonical durably accepts the matching batch.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Any
from threading import RLock

from anka_contracts.protocol import (CandidateCanonicalBatch, ProtocolAdmissionDecision,
    AdapterReleaseDescriptor, WireEnvelopeRef)
from anka_contracts.wire import WireEnvelope

@dataclass(frozen=True, slots=True)
class AdapterContextCheckpoint:
    adapter_release_id: str
    observed_client_build: str
    connection_id: str
    connection_generation: int
    revision: int
    opaque_state: Any
    digest: str

class ProtocolAdapterRuntime(Protocol):
    descriptor: AdapterReleaseDescriptor
    connection_id: str
    connection_generation: int
    def checkpoint_runtime_context(self) -> AdapterContextCheckpoint: ...
    def restore_runtime_context(self, checkpoint: AdapterContextCheckpoint) -> None: ...
    def decode_envelope(self, envelope: WireEnvelope) -> CandidateCanonicalBatch: ...

@dataclass(frozen=True, slots=True)
class TransactionResult:
    status: str
    batch: CandidateCanonicalBatch | None
    admission: ProtocolAdmissionDecision | None
    rollback_performed: bool
    failure_code: str | None = None

class ProtocolTransaction:
    """One connection-generation transactional coordinator.

    It intentionally does not import Canonical.  The admission object is injected
    through the stable contracts port and may be a fake during Q4.
    """
    def __init__(self, adapter:ProtocolAdapterRuntime, admission, observer=None):
        self.adapter=adapter; self.admission=admission; self._lock=RLock();self._poisoned=False;self._observer=observer
        # One ProtocolTransaction owns one connection generation and therefore
        # exactly one client identity. The first trusted in-scope envelope binds
        # this value; later client drift fails closed without decoder mutation.
        self._client_instance_id:str|None=None

    def _record(self,name:str,envelope:WireEnvelope,result:TransactionResult,**kwargs)->None:
        """Publish Protocol transaction facts after releasing decoder authority lock.

        Diagnostics are observational only.  A faulty sink must not alter decoder
        state, Canonical admission, rollback, poisoning, or the returned result.
        """
        if self._observer is None:return
        batch=result.batch
        descriptor=self._descriptor()
        payload={
            'status':result.status,
            'connection_id':envelope.connection_id,
            'connection_generation':envelope.connection_generation,
            'capture_session_id':envelope.capture_session_id,
            'wire_producer_sequence':envelope.producer_sequence,
            'continuity':envelope.continuity,
            'rollback_performed':result.rollback_performed,
            'transaction_poisoned':self.poisoned,
        }
        if descriptor is not None:
            payload['adapter_release_id']=descriptor.adapter_release_id
        if batch is not None:
            payload.update({
                'batch_span_id':batch.batch_id,
                'decode_health':batch.decode_health,
                'candidate_count':len(batch.candidates),
                'semantic_kinds':[c.semantic_kind for c in batch.candidates],
                'unknown_fingerprint_count':len(batch.unknown_fingerprints),
                'decoder_checkpoint_revision':batch.candidate_checkpoint.context_revision,
                'decoder_checkpoint_sha256':batch.candidate_checkpoint.context_sha256,
            })
        if result.admission is not None:
            payload['admission_status']=result.admission.status
            payload['admission_reason']=result.admission.reason_code
            payload['committed_cursor']=result.admission.committed_cursor
        payload.update(kwargs.pop('payload',{}))
        try:
            self._observer.record(name,owner_system='anka_protocol',account_id=None,
                client_generation=envelope.client_instance_id,protocol_build=(descriptor.observed_client_build if descriptor else None),
                span_id=(('span-'+batch.batch_id[6:])[:64] if batch is not None else None),
                failure_code=result.failure_code,boundary=kwargs.pop('boundary','protocol.transaction'),
                evidence_class=kwargs.pop('evidence_class','DERIVED'),payload=payload,**kwargs)
        except Exception:
            pass

    def process(self,envelope:WireEnvelope)->TransactionResult:
        # Decoder context is mutable per connection generation. Checkpoint,
        # decode, Canonical admission and possible rollback are one transaction.
        # Diagnostic publication happens only after releasing this authority lock.
        with self._lock:
            result=self._process_unlocked(envelope)
        if result.batch is not None:
            self._record('protocol.batch_decoded',envelope,result,boundary='protocol.decode',
                         evidence_class='OBSERVED_EXTERNAL')
        if result.status=='COMMITTED':
            self._record('protocol.canonical_admission_result',envelope,result,boundary='protocol.canonical_admission')
        elif result.status in ('ROLLED_BACK','ROLLBACK_FAILED','ADMISSION_FAILED','DECODE_FAILED','CHECKPOINT_FAILED','RUNTIME_INVALID','REJECTED_POISONED','REJECTED_SCOPE','REJECTED_TRANSPORT','REJECTED_CLIENT_BINDING'):
            sev='SAFETY' if result.status in ('ROLLBACK_FAILED','CHECKPOINT_FAILED','RUNTIME_INVALID','REJECTED_POISONED','REJECTED_CLIENT_BINDING') else 'WARNING'
            self._record('protocol.transaction_rejected',envelope,result,boundary='protocol.transaction',severity=sev)
        return result

    @property
    def poisoned(self)->bool:
        """True once decoder context can no longer be proved recoverable.

        A poisoned transaction is scoped to one connection generation. Callers
        must discard it and establish a fresh generation instead of guessing
        whether partially-mutated decoder state is still usable.
        """
        with self._lock:return self._poisoned

    @property
    def client_instance_id(self)->str|None:
        """Client identity permanently bound to this connection-generation transaction."""
        with self._lock:return self._client_instance_id

    def _descriptor(self)->AdapterReleaseDescriptor|None:
        descriptor=getattr(self.adapter,'descriptor',None)
        return descriptor if isinstance(descriptor,AdapterReleaseDescriptor) else None

    def _checkpoint_valid(self, checkpoint:object)->bool:
        descriptor=self._descriptor()
        return bool(
            descriptor is not None and isinstance(checkpoint,AdapterContextCheckpoint) and
            checkpoint.adapter_release_id==descriptor.adapter_release_id and
            checkpoint.observed_client_build==descriptor.observed_client_build and
            checkpoint.connection_id==getattr(self.adapter,'connection_id',None) and
            checkpoint.connection_generation==getattr(self.adapter,'connection_generation',None) and
            type(checkpoint.revision) is int and checkpoint.revision>=0 and
            isinstance(checkpoint.digest,str) and len(checkpoint.digest)==64 and
            all(c in '0123456789abcdef' for c in checkpoint.digest)
        )

    @staticmethod
    def _same_checkpoint(a:AdapterContextCheckpoint,b:AdapterContextCheckpoint)->bool:
        # opaque_state can be an arbitrary adapter-private type.  Its stable
        # integrity identity is the digest plus exact runtime scope/revision.
        return (a.adapter_release_id,a.observed_client_build,a.connection_id,
                a.connection_generation,a.revision,a.digest)==(
                b.adapter_release_id,b.observed_client_build,b.connection_id,
                b.connection_generation,b.revision,b.digest)

    def _batch_scope_valid(self,batch:object)->bool:
        descriptor=self._descriptor()
        return bool(
            descriptor is not None and isinstance(batch,CandidateCanonicalBatch) and
            batch.adapter_release_id==descriptor.adapter_release_id and
            batch.observed_client_build==descriptor.observed_client_build and
            batch.connection_id==self.adapter.connection_id and
            batch.connection_generation==self.adapter.connection_generation
        )

    def _rollback(self,before:AdapterContextCheckpoint,*,batch,decision,status:str,failure_code:str,poison_after:bool=True)->TransactionResult:
        try:
            self.adapter.restore_runtime_context(before)
            restored=self.adapter.checkpoint_runtime_context()
            if not self._checkpoint_valid(restored) or not self._same_checkpoint(before,restored):
                raise RuntimeError('ROLLBACK_VERIFICATION_MISMATCH')
        except Exception:
            self._poisoned=True
            suffix=failure_code.removeprefix('PROTOCOL_')
            return TransactionResult('ROLLBACK_FAILED',batch,decision,False,
                                     'PROTOCOL_RUNTIME_CONTEXT_ROLLBACK_FAILED_AFTER_'+suffix)
        if poison_after:
            # Once an envelope has been decoded and then rolled back, advancing to
            # the next envelope would create a stream hole: the decoder has not
            # consumed the rejected bytes.  Require a fresh connection generation
            # (or an explicit future replay/reconciliation mechanism) instead.
            self._poisoned=True
        return TransactionResult(status,batch,decision,True,failure_code)

    def _process_unlocked(self,envelope:WireEnvelope)->TransactionResult:
        if self._poisoned:
            return TransactionResult('REJECTED_POISONED',None,None,False,'PROTOCOL_TRANSACTION_POISONED')
        descriptor=self._descriptor()
        if descriptor is None:
            self._poisoned=True
            return TransactionResult('RUNTIME_INVALID',None,None,False,'PROTOCOL_ADAPTER_RUNTIME_DESCRIPTOR_INVALID')
        if envelope.connection_id!=self.adapter.connection_id or envelope.connection_generation!=self.adapter.connection_generation:
            return TransactionResult('REJECTED_SCOPE',None,None,False,'PROTOCOL_CONNECTION_SCOPE_MISMATCH')
        if envelope.client_instance_id=='':
            return TransactionResult('REJECTED_TRANSPORT',None,None,False,'PROTOCOL_TRANSPORT_CONTINUITY_UNTRUSTED')
        if envelope.continuity in ('GAP_BEFORE','GAP_INSIDE','RESET','UNKNOWN'):
            # Never ask a version decoder to infer across untrusted transport
            # continuity. More importantly, decoder state accumulated before
            # this discontinuity can no longer be trusted for this connection
            # generation, even if a later envelope is labelled COMPLETE.
            self._poisoned=True
            return TransactionResult('REJECTED_TRANSPORT',None,None,False,'PROTOCOL_TRANSPORT_CONTINUITY_UNTRUSTED')
        if self._client_instance_id is None:
            self._client_instance_id=envelope.client_instance_id
        elif envelope.client_instance_id!=self._client_instance_id:
            # Same connection generation may never silently migrate from one
            # client instance to another. This check is intentionally before
            # checkpoint/decode so no decoder state is mutated under mixed scope.
            self._poisoned=True
            return TransactionResult('REJECTED_CLIENT_BINDING',None,None,False,
                                     'PROTOCOL_TRANSACTION_CLIENT_DRIFT')
        try:
            before=self.adapter.checkpoint_runtime_context()
        except Exception:
            # The rollback precondition itself is unavailable. Continuing this
            # generation would make later decoder mutations impossible to undo.
            self._poisoned=True
            return TransactionResult('CHECKPOINT_FAILED',None,None,False,'PROTOCOL_RUNTIME_CONTEXT_CHECKPOINT_FAILED')
        if not self._checkpoint_valid(before):
            self._poisoned=True
            return TransactionResult('CHECKPOINT_FAILED',None,None,False,'PROTOCOL_RUNTIME_CONTEXT_CHECKPOINT_INVALID')
        try:
            batch=self.adapter.decode_envelope(envelope)
        except Exception:
            return self._rollback(before,batch=None,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_DECODER_EXCEPTION')
        if not self._batch_scope_valid(batch):
            return self._rollback(before,batch=batch if isinstance(batch,CandidateCanonicalBatch) else None,
                                  decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_DECODER_BATCH_SCOPE_MISMATCH')
        # Phase A derives client authority solely from immutable source refs and
        # candidates. Protocol consumes that proof before Canonical admission.
        # This is deliberately first-batch capable and uses no Canonical history.
        try:
            binding=batch.client_binding
        except Exception:
            return self._rollback(before,batch=batch,decision=None,status='REJECTED_CLIENT_BINDING',
                                  failure_code='PROTOCOL_BATCH_CLIENT_BINDING_INVALID')
        if binding.status!='PROVEN' or not binding.authoritative:
            failure_code={
                'LEGACY_UNBOUND':'PROTOCOL_BATCH_CLIENT_UNBOUND',
                'SOURCE_CONFLICT':'PROTOCOL_BATCH_CLIENT_SOURCE_CONFLICT',
                'CANDIDATE_MISMATCH':'PROTOCOL_BATCH_CLIENT_CANDIDATE_MISMATCH',
            }.get(binding.status,'PROTOCOL_BATCH_CLIENT_BINDING_INVALID')
            return self._rollback(before,batch=batch,decision=None,status='REJECTED_CLIENT_BINDING',
                                  failure_code=failure_code)
        if binding.source_client_instance_id!=envelope.client_instance_id:
            return self._rollback(before,batch=batch,decision=None,status='REJECTED_CLIENT_BINDING',
                                  failure_code='PROTOCOL_BATCH_CLIENT_SOURCE_MISMATCH')
        current_ref=WireEnvelopeRef.from_envelope(envelope)
        if current_ref not in batch.source_envelopes:
            return self._rollback(before,batch=batch,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_BATCH_CURRENT_ENVELOPE_EVIDENCE_MISSING')
        # A transaction processes exactly one direction of one capture session.
        # Prior refs may contribute buffered bytes, but the current envelope must
        # be the final causal source; future/cross-session/cross-direction evidence
        # cannot be claimed by a decoder before it has been observed.
        if (batch.source_envelopes[-1]!=current_ref or
                any(r.capture_session_id!=envelope.capture_session_id or r.direction!=envelope.direction
                    for r in batch.source_envelopes)):
            return self._rollback(before,batch=batch,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_BATCH_SOURCE_CAUSALITY_INVALID')
        # The batch checkpoint is Canonical's durable link to the decoder context.
        # Verify it against the adapter's actual post-decode state before allowing
        # Canonical admission; otherwise a buggy adapter can commit truthful events
        # under a false/stale decoder checkpoint.
        try:
            after=self.adapter.checkpoint_runtime_context()
        except Exception:
            return self._rollback(before,batch=batch,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_POST_DECODE_CHECKPOINT_FAILED')
        if not self._checkpoint_valid(after):
            return self._rollback(before,batch=batch,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_POST_DECODE_CHECKPOINT_INVALID')
        ref=batch.candidate_checkpoint
        if (ref.adapter_release_id,ref.observed_client_build,ref.connection_id,
                ref.connection_generation,ref.context_revision,ref.context_sha256)!=(
                after.adapter_release_id,after.observed_client_build,after.connection_id,
                after.connection_generation,after.revision,after.digest):
            return self._rollback(before,batch=batch,decision=None,status='DECODE_FAILED',
                                  failure_code='PROTOCOL_CANDIDATE_CHECKPOINT_MISMATCH')
        try:
            decision=self.admission.admit_candidate_batch(batch)
        except Exception:
            return self._rollback(before,batch=batch,decision=None,status='ADMISSION_FAILED',
                                  failure_code='PROTOCOL_CANONICAL_ADMISSION_EXCEPTION')
        if not isinstance(decision,ProtocolAdmissionDecision):
            return self._rollback(before,batch=batch,decision=None,status='ADMISSION_FAILED',
                                  failure_code='PROTOCOL_CANONICAL_ADMISSION_INVALID_RESULT')
        if decision.status=='COMMITTED':
            return TransactionResult('COMMITTED',batch,decision,False)
        return self._rollback(before,batch=batch,decision=decision,status='ROLLED_BACK',
                              failure_code='PROTOCOL_CANONICAL_'+decision.status)
