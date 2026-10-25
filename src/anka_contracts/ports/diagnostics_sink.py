"""Dependency-inversion port: business modules do not import the recorder."""
from typing import Protocol, Literal
from anka_contracts.diagnostics import DiagnosticEvent

EmitResult = Literal['RECORDED','DROPPED','UNAVAILABLE']

class DiagnosticsSink(Protocol):
    def emit(self, event: DiagnosticEvent) -> EmitResult:
        ...
