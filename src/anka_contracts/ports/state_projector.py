from typing import Protocol
from anka_contracts.canonical import CanonicalEventEnvelope
from anka_contracts.state import StateSnapshotIdentity
class StateProjectorPort(Protocol):
    def prepare(self, previous: StateSnapshotIdentity | None, batch: tuple[CanonicalEventEnvelope, ...]) -> StateSnapshotIdentity: ...
