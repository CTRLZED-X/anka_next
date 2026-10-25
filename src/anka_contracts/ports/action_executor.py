from typing import Protocol
from anka_contracts.action import ActionCommand, ActionOutcome
class ActionExecutor(Protocol):
    def submit(self, command: ActionCommand) -> ActionOutcome: ...
