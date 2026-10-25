from typing import Protocol
from anka_contracts.canonical import CanonicalEventEnvelope
class CanonicalAdmissionPort(Protocol):
    def admit(self, candidates: tuple[CanonicalEventEnvelope, ...]) -> int: ...
