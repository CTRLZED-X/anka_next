"""Research-only admission boundary. Owns no live-state projection or authority.

The future authoritative journal/reducer must be implemented and verified as a
separate milestone, with crash-atomic canonical/state commits.
"""
from __future__ import annotations
from dataclasses import dataclass
from anka_contracts.canonical import CanonicalAdmission,CanonicalDraft
from anka_contracts.semantic import SemanticResult

MAX_STAGED=2048

class CanonicalStagingGate:
    def __init__(self):
        self._research:list[CanonicalDraft]=[]
        self._seen:set[tuple]=set()
        self.rejections=0

    def inspect(self,result:SemanticResult,*,transport_complete:bool=False,account_attested:bool=False)->CanonicalAdmission:
        """Neither transport nor account flags can promote a historical mapping."""
        if result.status!='CANDIDATES_ONLY':
            self.rejections+=1
            return CanonicalAdmission('QUARANTINED',(),(result.failure_code or result.status,))
        if len(result.candidates)>MAX_STAGED-len(self._research):
            self.rejections+=1
            return CanonicalAdmission('QUARANTINED',(),('STAGING_CAPACITY_EXCEEDED',))
        accepted=[]
        keys=[]
        for item in result.candidates:
            proof=item.evidence
            if item.authority!='HISTORICAL_CANDIDATE_ONLY' or proof.protocol_build!=result.protocol_build or proof.adapter_id!=result.adapter_id or proof.wire_name!=result.wire_name:
                self.rejections+=1
                return CanonicalAdmission('QUARANTINED',(),('CANDIDATE_PROVENANCE_MISMATCH',))
            key=(proof.protocol_build,proof.adapter_id,proof.flow_digest,proof.transport_generation,proof.packet_number,proof.message_index,item.kind,item.actor_id,item.resource)
            if key in self._seen or key in keys:
                self.rejections+=1
                return CanonicalAdmission('QUARANTINED',(),('DUPLICATE_EVIDENCE',))
            keys.append(key)
            accepted.append(item)
        # No state update; immutable research evidence remains bounded in memory.
        self._research.extend(accepted)
        self._seen.update(keys)
        return CanonicalAdmission('STAGED_UNCERTIFIED',tuple(accepted),('HISTORICAL_SCHEMA_UNCERTIFIED',
                 'TRANSPORT_VALIDATION_REQUIRED' if not transport_complete else 'NO_CURRENT_BUILD_CERTIFICATION',
                 'ACCOUNT_ATTESTATION_REQUIRED' if not account_attested else 'NO_AUTHORITATIVE_JOURNAL'))

    @property
    def staged_count(self)->int:return len(self._research)
