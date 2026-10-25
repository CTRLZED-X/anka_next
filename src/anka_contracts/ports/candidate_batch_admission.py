from typing import Protocol
from anka_contracts.protocol import CandidateCanonicalBatch, ProtocolAdmissionDecision
class CandidateBatchAdmission(Protocol):
    def admit_candidate_batch(self, batch: CandidateCanonicalBatch) -> ProtocolAdmissionDecision: ...
