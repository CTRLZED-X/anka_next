"""Historical Dofus 3.7.10.10 adapter behind the definitive M5 SDK.

This wrapper deliberately reuses already-ported historical semantic code while
keeping this release replay-only.  It is not current-client certification.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import json

from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.evidence import EvidencePointer
from anka_contracts.protocol import CandidateCanonicalBatch,DecoderCheckpointRef,WireEnvelopeRef
from anka_contracts.protocol import AdapterReleaseDescriptor,WireMessage
from anka_contracts.wire import WireEnvelope
from anka_protocol.adapters.historical_semantic import HistoricalSemanticAdapter,HistoricalContext
from anka_protocol.sdk.opaque import OpaquePolicy
from anka_protocol.sdk.runtime import AdapterContextCheckpoint
from anka_protocol.wire import FrameBuffer,extract_any,WireRejected

BUILD='Dofus 3.7.10.10'
RELEASE_ID='adapter-dofus-3.7.10.10-historical-m5-r2'

@dataclass(frozen=True,slots=True)
class _State:
    revision:int
    s2c_buffer:bytes
    c2s_buffer:bytes
    s2c_failed:bool
    c2s_failed:bool
    messages_seen:int
    s2c_pending_refs:tuple[WireEnvelopeRef,...]
    c2s_pending_refs:tuple[WireEnvelopeRef,...]

class Historical371010Adapter:
    def __init__(self,*,descriptor:AdapterReleaseDescriptor,account_id:str,client_instance_id:str,connection_id:str,connection_generation:int,opaque_policy:OpaquePolicy|None=None,semantic_context:HistoricalContext|None=None):
        if descriptor.adapter_release_id!=RELEASE_ID or descriptor.observed_client_build!=BUILD: raise ValueError('M5_HISTORICAL_DESCRIPTOR_MISMATCH')
        if not account_id.startswith('acct-') or not client_instance_id.startswith('client-'): raise ValueError('M5_HISTORICAL_IDENTITY_INVALID')
        if not connection_id.startswith('conn-') or type(connection_generation) is not int or connection_generation<=0: raise ValueError('M5_HISTORICAL_CONNECTION_INVALID')
        self.descriptor=descriptor;self.account_id=account_id;self.client_instance_id=client_instance_id
        self.connection_id=connection_id;self.connection_generation=connection_generation
        self._buffers={'server_to_client':FrameBuffer(),'client_to_server':FrameBuffer()}
        self._pending_refs={'server_to_client':(), 'client_to_server':()}
        self._revision=0;self._messages_seen=0;self._opaque=opaque_policy or OpaquePolicy();self._semantic_context=semantic_context
        self._semantic=HistoricalSemanticAdapter(requested_build=BUILD)

    def _state(self)->_State:
        return _State(self._revision,bytes(self._buffers['server_to_client'].buffer),bytes(self._buffers['client_to_server'].buffer),
                      self._buffers['server_to_client'].failed,self._buffers['client_to_server'].failed,self._messages_seen,
                      tuple(self._pending_refs['server_to_client']),tuple(self._pending_refs['client_to_server']))
    @staticmethod
    def _digest(state:_State)->str:
        h=sha256();h.update(str(state.revision).encode());h.update(state.s2c_buffer);h.update(b'|');h.update(state.c2s_buffer)
        h.update(bytes((state.s2c_failed,state.c2s_failed)));h.update(str(state.messages_seen).encode())
        for direction,refs in (('s2c',state.s2c_pending_refs),('c2s',state.c2s_pending_refs)):
            h.update(direction.encode())
            for ref in refs:
                h.update(f'{ref.capture_session_id}|{ref.connection_id}|{ref.connection_generation}|{ref.producer_sequence}|{ref.direction}|{ref.continuity}|{ref.payload_sha256}'.encode())
        return h.hexdigest()
    def checkpoint_runtime_context(self)->AdapterContextCheckpoint:
        state=self._state();return AdapterContextCheckpoint(RELEASE_ID,BUILD,self.connection_id,self.connection_generation,state.revision,state,self._digest(state))
    def restore_runtime_context(self,checkpoint:AdapterContextCheckpoint)->None:
        if checkpoint.adapter_release_id!=RELEASE_ID or checkpoint.observed_client_build!=BUILD or checkpoint.connection_id!=self.connection_id or checkpoint.connection_generation!=self.connection_generation:
            raise ValueError('M5_CHECKPOINT_SCOPE_MISMATCH')
        state=checkpoint.opaque_state
        if not isinstance(state,_State) or self._digest(state)!=checkpoint.digest: raise ValueError('M5_CHECKPOINT_CORRUPT')
        self._revision=state.revision;self._messages_seen=state.messages_seen
        self._buffers={'server_to_client':FrameBuffer(),'client_to_server':FrameBuffer()}
        self._pending_refs={'server_to_client':tuple(state.s2c_pending_refs),'client_to_server':tuple(state.c2s_pending_refs)}
        for direction,data,failed in (('server_to_client',state.s2c_buffer,state.s2c_failed),('client_to_server',state.c2s_buffer,state.c2s_failed)):
            self._buffers[direction].buffer.extend(data);self._buffers[direction].failed=failed

    def _checkpoint_ref(self)->DecoderCheckpointRef:
        cp=self.checkpoint_runtime_context()
        return DecoderCheckpointRef(RELEASE_ID,BUILD,self.connection_id,self.connection_generation,cp.revision,cp.digest)

    def _candidate(self,draft,msg:WireMessage,envelope:WireEnvelope,index:int)->CanonicalCandidate:
        selector=sha256(f'{self.connection_id}:{envelope.producer_sequence}:{msg.message_index}:{msg.name}'.encode()).hexdigest()
        ev=EvidencePointer('evidence-'+selector[:32],'OBSERVED_EXTERNAL','anka_protocol','wire-selector:'+selector,
                           sha256(msg.body).hexdigest(),f'{BUILD}/{RELEASE_ID}/{self.connection_id}/{self.connection_generation}')
        payload=[]
        if draft.resource is not None:payload.append(('resource',draft.resource))
        if draft.value is not None:payload.append(('value',str(draft.value)))
        if draft.maximum is not None:payload.append(('maximum',str(draft.maximum)))
        if draft.cooldowns:payload.append(('cooldowns',json.dumps(list(draft.cooldowns),separators=(',',':'))))
        ident=sha256(f'{selector}:{draft.kind}:{draft.actor_id}:{index}'.encode()).hexdigest()[:32]
        payload.append(('actor_id',str(draft.actor_id)))
        return CanonicalCandidate('candidate-'+ident,draft.kind,self.account_id,self.client_instance_id,(ev,),tuple(payload))

    def decode_envelope(self,envelope:WireEnvelope)->CandidateCanonicalBatch:
        if envelope.connection_id!=self.connection_id or envelope.connection_generation!=self.connection_generation or envelope.client_instance_id!=self.client_instance_id:
            raise ValueError('M5_ENVELOPE_SCOPE_MISMATCH')
        ref=WireEnvelopeRef.from_envelope(envelope)
        prior_refs=tuple(self._pending_refs[envelope.direction])
        sources=prior_refs+(ref,)
        if envelope.continuity in ('GAP_BEFORE','GAP_INSIDE','RESET','UNKNOWN'):
            self._revision+=1
            cp=self._checkpoint_ref();bid=sha256(f'{RELEASE_ID}:{self.connection_id}:{envelope.producer_sequence}:gap'.encode()).hexdigest()[:32]
            return CandidateCanonicalBatch('batch-'+bid,RELEASE_ID,BUILD,self.connection_id,self.connection_generation,(ref,),(), 'INCOMPLETE_TRANSPORT',cp,(),('TRANSPORT_CONTINUITY_UNTRUSTED',))
        try:
            frames=self._buffers[envelope.direction].feed(envelope.payload)
        except WireRejected:
            self._pending_refs[envelope.direction]=()
            self._revision+=1;cp=self._checkpoint_ref();bid=sha256(f'{RELEASE_ID}:{self.connection_id}:{envelope.producer_sequence}:wire'.encode()).hexdigest()[:32]
            return CandidateCanonicalBatch('batch-'+bid,RELEASE_ID,BUILD,self.connection_id,self.connection_generation,sources,(), 'QUARANTINED',cp,(),('WIRE_FRAME_MALFORMED',))
        if self._buffers[envelope.direction].buffer:
            # If at least one frame completed, any remaining incomplete frame
            # starts in the current envelope. If none completed, the prior partial
            # frame still depends on every envelope accumulated so far.
            self._pending_refs[envelope.direction]=(ref,) if frames else sources
        else:
            self._pending_refs[envelope.direction]=()
        candidates=[];unknown=[];opaque_count=0;mapped_count=0;unmapped_count=0;message_index=0
        for frame in frames:
            try:pairs=extract_any(frame)
            except WireRejected:
                self._revision+=1;cp=self._checkpoint_ref();bid=sha256(f'{RELEASE_ID}:{self.connection_id}:{envelope.producer_sequence}:any'.encode()).hexdigest()[:32]
                return CandidateCanonicalBatch('batch-'+bid,RELEASE_ID,BUILD,self.connection_id,self.connection_generation,sources,(), 'QUARANTINED',cp,(),('WIRE_ANY_MALFORMED',))
            for name,body in pairs:
                self._messages_seen+=1
                msg=WireMessage(envelope.direction,name,body,envelope.source_packet_number or envelope.producer_sequence,
                                self.connection_id,self.connection_generation,message_index);message_index+=1
                result=self._semantic.decode(msg,context=self._semantic_context)
                if result.status=='CANDIDATES_ONLY':
                    mapped_count+=1
                    for i,draft in enumerate(result.candidates): candidates.append(self._candidate(draft,msg,envelope,i))
                elif result.status in ('QUARANTINED','BUILD_MISMATCH'):
                    unknown.append(sha256(envelope.direction.encode()+b'|'+name.encode()+b'|'+body).hexdigest())
                elif self._opaque.accepts(envelope.direction,name,body): opaque_count+=1
                elif result.status=='CONTEXT_MISSING':
                    # Missing identity/fight context is safety-significant; never turn it into a negative fact.
                    unknown.append(sha256(envelope.direction.encode()+b'|'+name.encode()+b'|'+body).hexdigest())
                else:
                    unmapped_count+=1;unknown.append(sha256(envelope.direction.encode()+b'|'+name.encode()+b'|'+body).hexdigest())
        self._revision+=1
        cp=self._checkpoint_ref();bid=sha256(f'{RELEASE_ID}:{self.connection_id}:{envelope.producer_sequence}:{cp.context_sha256}'.encode()).hexdigest()[:32]
        # One unknown in a batch fences all semantic candidates from that envelope;
        # never partially commit around traffic whose impact is unproven.
        if unknown:
            return CandidateCanonicalBatch('batch-'+bid,RELEASE_ID,BUILD,self.connection_id,self.connection_generation,sources,(), 'UNKNOWN_CRITICAL',cp,tuple(sorted(set(unknown))),('UNKNOWN_OR_UNPROVEN_WIRE',))
        if candidates: health='SEMANTIC_CANDIDATES'
        elif opaque_count: health='OPAQUE_CERTIFIED_ZERO_SEMANTIC'
        elif self._buffers[envelope.direction].buffer:
            # No complete wire message exists yet. This is transport-framing
            # progress, not an opaque semantic negative and not unmapped traffic.
            # Canonical may durably bind the decoder checkpoint while committing
            # zero semantic events, allowing the next TCP envelope to continue.
            health='FRAMING_IN_PROGRESS'
        else: health='NO_SEMANTIC_MAPPING'
        return CandidateCanonicalBatch('batch-'+bid,RELEASE_ID,BUILD,self.connection_id,self.connection_generation,sources,tuple(candidates),health,cp)
