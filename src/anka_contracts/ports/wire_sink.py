from typing import Protocol
from anka_contracts.wire import WireEnvelope
class WireSink(Protocol):
    def accept(self, envelope: WireEnvelope) -> None: ...
