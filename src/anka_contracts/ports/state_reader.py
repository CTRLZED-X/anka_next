from typing import Protocol
from anka_contracts.state import StateSnapshotIdentity
class StateReader(Protocol):
    def current_snapshot(self, account_id: str) -> StateSnapshotIdentity: ...
