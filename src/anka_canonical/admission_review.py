"""P58: fail-closed *structural* review of untrusted protocol/identity claims.

A positive structural finding MUST NOT be interpreted as current-client
certification. All claims, bytes, and identity values are caller supplied;
there is no trusted evidence provider and no journal write path in this module.
"""
from __future__ import annotations
from dataclasses import dataclass,field
from hashlib import sha256
from json import dumps
from anka_contracts.admission import AdmissionRehearsal

MANDATORY_BLOCKERS=(
    'P58_TRUSTED_CAPTURE_ATTESTOR_NOT_IMPLEMENTED',
    'P58_CAPTURE_ORIGIN_INDEPENDENTLY_UNVERIFIED',
    'P58_CURRENT_BUILD_SEMANTIC_CERTIFICATION_MISSING',
    'P58_INDEPENDENT_PROCESS_WINDOW_CHARACTER_BINDING_MISSING',
    'P58_CHARACTER_BREED_AND_ACCOUNT_ROLE_UNVERIFIED',
    'P58_AUTHORITATIVE_CANONICAL_WRITER_NOT_IMPLEMENTED',
)

@dataclass(frozen=True,slots=True)
class AdmissionReview:
    """Privacy-safe diagnostic; cannot be used as a grant or journal envelope."""
    status: str
    structural_consistency: bool
    reasons: tuple[str,...]
    checked_packets: int
    checked_drafts: int
    scope_fingerprint: str
    certified: bool = field(default=False,init=False)
    authoritative: bool = field(default=False,init=False)
    actionable: bool = field(default=False,init=False)
    canonical_commits: int = field(default=0,init=False)
    physical_input_sent: bool = field(default=False,init=False)

    def __post_init__(self):
        if self.status not in ('STRUCTURALLY_CONSISTENT_UNTRUSTED','QUARANTINED'):
            raise ValueError('P58_REVIEW_STATUS_INVALID')
        if self.structural_consistency != (self.status=='STRUCTURALLY_CONSISTENT_UNTRUSTED'):
            raise ValueError('P58_REVIEW_STATUS_CONFLICT')
        if not set(MANDATORY_BLOCKERS).issubset(self.reasons):
            raise ValueError('P58_MANDATORY_BLOCKERS_MISSING')
        if len(self.scope_fingerprint)!=64:
            raise ValueError('P58_REVIEW_FINGERPRINT_INVALID')

    def to_dict(self)->dict:
        # No account names, PID, HWND, flow selectors, or raw wire/payload data.
        return {'status':self.status,'structural_consistency':self.structural_consistency,
            'reasons':list(self.reasons),'checked_packets':self.checked_packets,
            'checked_drafts':self.checked_drafts,'scope_fingerprint':self.scope_fingerprint,
            'certified':False,'authoritative':False,'actionable':False,
            'canonical_commits':0,'physical_input_sent':False}


def _key(ref):
    return (ref.flow_digest,ref.transport_generation,ref.packet_number,ref.message_index)


def review_admission_rehearsal(rehearsal:AdmissionRehearsal)->AdmissionReview:
    """Check exact source/body associations and conservative ordering.

    This function intentionally offers NO certified/ready/promote mode, even
    if every supplied claim matches and even if a caller labels it current.
    One packet can yield multiple distinct facts, but cannot change its bytes.
    """
    if type(rehearsal) is not AdmissionRehearsal:
        raise TypeError('P58_UNTRUSTED_REHEARSAL_REQUIRED')
    s=rehearsal.scope
    fingerprint=sha256(dumps({'session':s.session_id,'account':s.account_id,
        'account_generation':s.account_generation,'fight':s.fight_id,
        'build':s.protocol_build,'adapter':s.adapter_id,'flow':s.flow_digest,
        'transport_generation':s.transport_generation,'process_generation':s.process_generation,
        'window_generation':s.window_generation,'capture':s.capture_sha256},
        sort_keys=True,separators=(',',':')).encode('ascii')).hexdigest()
    errors=set()
    packet_by_ref={}
    last=None
    for packet in rehearsal.packets:
        ref=packet.evidence
        key=_key(ref)
        if (ref.protocol_build,ref.adapter_id,ref.flow_digest,ref.transport_generation)!=(
                s.protocol_build,s.adapter_id,s.flow_digest,s.transport_generation):
            errors.add('P58_PACKET_SCOPE_MISMATCH')
        if packet.capture_sha256!=s.capture_sha256:
            errors.add('P58_CAPTURE_SNAPSHOT_MISMATCH')
        if packet.direction!='server_to_client':
            errors.add('P58_UNTRUSTED_OR_NONSERVER_DIRECTION')
        if key in packet_by_ref:
            errors.add('P58_DUPLICATE_PACKET_SOURCE')
        else:
            packet_by_ref[key]=packet
        if last is not None and (ref.packet_number,ref.message_index)<=last:
            errors.add('P58_PACKET_SOURCE_NOT_ORDERED')
        last=(ref.packet_number,ref.message_index)
    identity=rehearsal.character
    identity_key=_key(identity.evidence)
    if identity_key not in packet_by_ref:
        errors.add('P58_CHARACTER_PACKET_NOT_PRESENT')
    else:
        if packet_by_ref[identity_key].evidence != identity.evidence:
            errors.add('P58_CHARACTER_PACKET_PROVENANCE_MISMATCH')
    if (identity.evidence.protocol_build,identity.evidence.adapter_id,
        identity.evidence.flow_digest,identity.evidence.transport_generation)!=(
            s.protocol_build,s.adapter_id,s.flow_digest,s.transport_generation):
        errors.add('P58_CHARACTER_SCOPE_MISMATCH')
    seen_fact=set()
    seen_local=False
    seen_semantic=False
    for draft in rehearsal.drafts:
        ref=draft.evidence
        key=_key(ref)
        packet=packet_by_ref.get(key)
        if packet is None:
            errors.add('P58_SEMANTIC_PACKET_NOT_PRESENT')
        elif packet.evidence!=ref:
            errors.add('P58_SEMANTIC_PACKET_PROVENANCE_MISMATCH')
        if (ref.protocol_build,ref.adapter_id,ref.flow_digest,ref.transport_generation)!=(
                s.protocol_build,s.adapter_id,s.flow_digest,s.transport_generation):
            errors.add('P58_SEMANTIC_SCOPE_MISMATCH')
        if (ref.packet_number,ref.message_index) <= (identity.evidence.packet_number,identity.evidence.message_index):
            errors.add('P58_SEMANTIC_NOT_AFTER_CHARACTER_WITNESS')
        fact=(key,draft.kind,draft.actor_id,draft.resource)
        if fact in seen_fact:
            errors.add('P58_DUPLICATE_OR_CONFLICTING_FACT_SOURCE')
        seen_fact.add(fact)
        seen_local |= draft.actor_id==identity.actor_id
        seen_semantic=True
        if draft.authority!='HISTORICAL_CANDIDATE_ONLY':
            errors.add('P58_UNEXPECTED_SEMANTIC_AUTHORITY')
    if not seen_local or not seen_semantic:
        errors.add('P58_LOCAL_CHARACTER_ACTOR_NOT_OBSERVED')
    # This proves internal consistency of supplied metadata/bytes only.
    reasons=tuple(sorted(errors|set(MANDATORY_BLOCKERS)))
    consistent=not errors
    return AdmissionReview('STRUCTURALLY_CONSISTENT_UNTRUSTED' if consistent else 'QUARANTINED',
        consistent,reasons,len(rehearsal.packets),len(rehearsal.drafts),fingerprint)
