"""Stable P6 wire-observation contracts: no game-state mutations or raw evidence in exports."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass(frozen=True, slots=True)
class WireMessage:
    direction: str
    name: str
    body: bytes = field(repr=False)
    packet_number: int = 0
    flow_key: str = field(default='', repr=False)
    generation: int = 0
    message_index: int = 0

    def __post_init__(self):
        if self.direction not in ('server_to_client', 'client_to_server'):
            raise ValueError('PROTOCOL_DIRECTION_INVALID')
        if not isinstance(self.name,str) or not 1<=len(self.name)<=96 or not self.name.isascii() or not self.name.replace('_','').isalnum():
            raise ValueError('PROTOCOL_MESSAGE_NAME_INVALID')
        if not isinstance(self.body,bytes) or len(self.body)>2_000_000:
            raise ValueError('PROTOCOL_BODY_INVALID')
        if type(self.packet_number) is not int or self.packet_number<0:
            raise ValueError('PROTOCOL_PACKET_INVALID')
        if type(self.generation) is not int or self.generation<0:
            raise ValueError('PROTOCOL_GENERATION_INVALID')
        if type(self.message_index) is not int or self.message_index<0:
            raise ValueError('PROTOCOL_MESSAGE_INDEX_INVALID')


@dataclass(frozen=True, slots=True)
class ProtocolFinding:
    category: str
    name: str
    direction: str
    packet_number: int
    capability: str = 'UNASSIGNED'
    reason: str = ''

    def __post_init__(self):
        if self.category not in ('CATALOG_OBSERVED_ONLY','UNKNOWN_WIRE','DIRECTION_MISMATCH','CONTRACT_VIOLATION'):
            raise ValueError('PROTOCOL_FINDING_INVALID')


@dataclass(frozen=True, slots=True)
class ProtocolReceipt:
    schema_version: int
    adapter_id: str
    requested_build: str
    adapter_build: str
    status: str
    selected_segments: int
    framed_messages: int
    classified_observations: int
    unknown_messages: int
    direction_mismatches: int
    invalid_frames: int
    quarantined_streams: int
    unanchored_streams: int
    packet_loss_reported: bool
    account_identity_certified: bool = False
    canonical_events_emitted: int = 0
    gameplay_capabilities_certified: bool = False
    physical_input_sent: bool = False
    findings: tuple[ProtocolFinding,...] = ()

    def to_dict(self) -> dict:
        obj=asdict(self)
        # No IP, payload, endpoint, raw source path or account name is ever available.
        return obj


# --- Definitive M5 protocol SDK contracts ---
from typing import Literal
from hashlib import sha256 as _sha256
from anka_contracts.canonical import CanonicalCandidate
from anka_contracts.wire import WireEnvelope

AdapterLifecycle = Literal[
    'STAGED','STRUCTURALLY_VALID','REPLAY_CERTIFIED','OBSERVATION_CERTIFIED',
    'ACTION_SCOPED_CERTIFIED','ACTIVE','QUARANTINED','RETIRED'
]
DecodeHealth = Literal[
    'SEMANTIC_CANDIDATES','FRAMING_IN_PROGRESS','NO_SEMANTIC_MAPPING',
    'OPAQUE_CERTIFIED_ZERO_SEMANTIC','UNKNOWN_CRITICAL','INCOMPLETE_TRANSPORT','QUARANTINED'
]
AdmissionStatus = Literal['COMMITTED','REJECTED','UNCERTAIN']

@dataclass(frozen=True, slots=True)
class AdapterReleaseDescriptor:
    adapter_release_id: str
    observed_client_build: str
    code_sha256: str
    evidence_manifest_sha256: str
    canonical_schema_major: int
    canonical_schema_minor: int
    lifecycle: AdapterLifecycle
    capabilities: tuple[str,...] = ()
    certified_scenarios: tuple[str,...] = ()
    action_scopes: tuple[str,...] = ()

    def __post_init__(self):
        if type(self.adapter_release_id) is not str or not self.adapter_release_id.startswith('adapter-') or len(self.adapter_release_id)>128:
            raise ValueError('INVALID_ADAPTER_RELEASE_ID')
        if type(self.observed_client_build) is not str or not 1<=len(self.observed_client_build)<=96:
            raise ValueError('INVALID_ADAPTER_BUILD')
        for value,code in ((self.code_sha256,'INVALID_ADAPTER_CODE_HASH'),(self.evidence_manifest_sha256,'INVALID_ADAPTER_EVIDENCE_HASH')):
            if type(value) is not str or len(value)!=64 or any(c not in '0123456789abcdef' for c in value): raise ValueError(code)
        if type(self.canonical_schema_major) is not int or self.canonical_schema_major<1 or type(self.canonical_schema_minor) is not int or self.canonical_schema_minor<0:
            raise ValueError('INVALID_ADAPTER_CANONICAL_SCHEMA')
        if self.lifecycle not in ('STAGED','STRUCTURALLY_VALID','REPLAY_CERTIFIED','OBSERVATION_CERTIFIED','ACTION_SCOPED_CERTIFIED','ACTIVE','QUARANTINED','RETIRED'):
            raise ValueError('INVALID_ADAPTER_LIFECYCLE')
        for values,code in ((self.capabilities,'INVALID_ADAPTER_CAPABILITY'),(self.certified_scenarios,'INVALID_ADAPTER_SCENARIO'),(self.action_scopes,'INVALID_ADAPTER_ACTION_SCOPE')):
            if len(set(values))!=len(values) or any(type(x) is not str or not 1<=len(x)<=96 for x in values): raise ValueError(code)

@dataclass(frozen=True, slots=True)
class WireEnvelopeRef:
    capture_session_id: str
    connection_id: str
    connection_generation: int
    producer_sequence: int
    direction: str
    continuity: str
    payload_sha256: str

    @classmethod
    def from_envelope(cls, envelope: WireEnvelope) -> 'WireEnvelopeRef':
        return cls(envelope.capture_session_id,envelope.connection_id,envelope.connection_generation,
                   envelope.producer_sequence,envelope.direction,envelope.continuity,
                   _sha256(envelope.payload).hexdigest())

    def __post_init__(self):
        if not self.capture_session_id.startswith('capture-') or not self.connection_id.startswith('conn-'):
            raise ValueError('INVALID_WIRE_REF_ID')
        if type(self.connection_generation) is not int or self.connection_generation<=0 or type(self.producer_sequence) is not int or self.producer_sequence<0:
            raise ValueError('INVALID_WIRE_REF_SEQUENCE')
        if self.direction not in ('client_to_server','server_to_client'):
            raise ValueError('INVALID_WIRE_REF_DIRECTION')
        if self.continuity not in ('COMPLETE','GAP_BEFORE','GAP_INSIDE','RECONNECTED','CONTIGUOUS','RESET','UNKNOWN'):
            raise ValueError('INVALID_WIRE_REF_CONTINUITY')
        if type(self.payload_sha256) is not str or len(self.payload_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.payload_sha256):
            raise ValueError('INVALID_WIRE_REF_HASH')

@dataclass(frozen=True, slots=True)
class DecoderCheckpointRef:
    adapter_release_id: str
    observed_client_build: str
    connection_id: str
    connection_generation: int
    context_revision: int
    context_sha256: str

    def __post_init__(self):
        if not self.adapter_release_id.startswith('adapter-') or not self.connection_id.startswith('conn-'):
            raise ValueError('INVALID_DECODER_CHECKPOINT_ID')
        if type(self.observed_client_build) is not str or not self.observed_client_build:
            raise ValueError('INVALID_DECODER_CHECKPOINT_BUILD')
        if type(self.connection_generation) is not int or self.connection_generation<=0 or type(self.context_revision) is not int or self.context_revision<0:
            raise ValueError('INVALID_DECODER_CHECKPOINT_REVISION')
        if type(self.context_sha256) is not str or len(self.context_sha256)!=64 or any(c not in '0123456789abcdef' for c in self.context_sha256):
            raise ValueError('INVALID_DECODER_CHECKPOINT_HASH')

@dataclass(frozen=True, slots=True)
class CandidateCanonicalBatch:
    batch_id: str
    adapter_release_id: str
    observed_client_build: str
    connection_id: str
    connection_generation: int
    source_envelopes: tuple[WireEnvelopeRef,...]
    candidates: tuple[CanonicalCandidate,...]
    decode_health: DecodeHealth
    candidate_checkpoint: DecoderCheckpointRef
    unknown_fingerprints: tuple[str,...] = ()
    failure_codes: tuple[str,...] = ()

    def __post_init__(self):
        if type(self.batch_id) is not str or not self.batch_id.startswith('batch-') or len(self.batch_id)>128:
            raise ValueError('INVALID_PROTOCOL_BATCH_ID')
        if not self.adapter_release_id.startswith('adapter-') or not self.connection_id.startswith('conn-'):
            raise ValueError('INVALID_PROTOCOL_BATCH_SOURCE')
        if type(self.observed_client_build) is not str or not self.observed_client_build:
            raise ValueError('INVALID_PROTOCOL_BATCH_BUILD')
        if type(self.connection_generation) is not int or self.connection_generation<=0:
            raise ValueError('INVALID_PROTOCOL_BATCH_GENERATION')
        if not self.source_envelopes or any(not isinstance(x,WireEnvelopeRef) for x in self.source_envelopes):
            raise ValueError('PROTOCOL_BATCH_EVIDENCE_REQUIRED')
        if self.decode_health not in ('SEMANTIC_CANDIDATES','FRAMING_IN_PROGRESS','NO_SEMANTIC_MAPPING','OPAQUE_CERTIFIED_ZERO_SEMANTIC','UNKNOWN_CRITICAL','INCOMPLETE_TRANSPORT','QUARANTINED'):
            raise ValueError('INVALID_PROTOCOL_BATCH_HEALTH')
        if self.decode_health=='SEMANTIC_CANDIDATES' and not self.candidates:
            raise ValueError('PROTOCOL_BATCH_CANDIDATES_REQUIRED')
        if self.decode_health!='SEMANTIC_CANDIDATES' and self.candidates:
            raise ValueError('PROTOCOL_BATCH_UNSAFE_PARTIAL_CANDIDATES')
        if (self.candidate_checkpoint.adapter_release_id!=self.adapter_release_id or
                self.candidate_checkpoint.observed_client_build!=self.observed_client_build or
                self.candidate_checkpoint.connection_id!=self.connection_id or
                self.candidate_checkpoint.connection_generation!=self.connection_generation):
            raise ValueError('PROTOCOL_BATCH_CHECKPOINT_SCOPE_MISMATCH')
        for fp in self.unknown_fingerprints:
            if type(fp) is not str or len(fp)!=64 or any(c not in '0123456789abcdef' for c in fp): raise ValueError('INVALID_UNKNOWN_FINGERPRINT')

@dataclass(frozen=True, slots=True)
class ProtocolAdmissionDecision:
    status: AdmissionStatus
    committed_cursor: int | None = None
    reason_code: str | None = None

    def __post_init__(self):
        if self.status not in ('COMMITTED','REJECTED','UNCERTAIN'): raise ValueError('INVALID_PROTOCOL_ADMISSION_STATUS')
        if self.status=='COMMITTED':
            if type(self.committed_cursor) is not int or self.committed_cursor<0: raise ValueError('PROTOCOL_COMMIT_CURSOR_REQUIRED')
        elif self.committed_cursor is not None: raise ValueError('PROTOCOL_NONCOMMIT_CURSOR_FORBIDDEN')
        if self.status!='COMMITTED' and (type(self.reason_code) is not str or not self.reason_code): raise ValueError('PROTOCOL_NONCOMMIT_REASON_REQUIRED')

@dataclass(frozen=True, slots=True)
class SemanticImpact:
    semantic_kind: str
    change: str
    consumers: tuple[str,...]
    action_scopes: tuple[str,...]
    safety_effect: str

    def __post_init__(self):
        if self.change not in ('UNCHANGED','ADDED','REMOVED','CHANGED','UNPROVEN'): raise ValueError('INVALID_SEMANTIC_CHANGE')
        if self.safety_effect not in ('NONE','OBSERVE_ONLY','DISARM_CAPABILITY','BLOCK_BUILD'): raise ValueError('INVALID_SEMANTIC_SAFETY_EFFECT')
