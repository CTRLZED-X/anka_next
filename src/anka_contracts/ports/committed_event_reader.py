from typing import Protocol
from anka_contracts.canonical import CanonicalEventEnvelope
class CommittedEventReader(Protocol):
    def read_from(self, canonical_cursor: int, *, limit: int = 512) -> tuple[CanonicalEventEnvelope, ...]: ...
