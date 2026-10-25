"""Definitive ANKA_NEXT composition entry point.

Only :mod:`anka_app` may construct concrete cross-system implementations.  This
module is the stable entry point for the definitive roadmap; historical P-series
composition modules remain regression fixtures and are not production owners.

The live runtime intentionally remains unavailable until Q10→Q12 have current
Windows/client evidence.  Merely having a Windows input driver in the source tree
cannot enable it.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from anka_app.readiness import assess_live_readiness


class CompositionBlocked(RuntimeError):
    """Raised when a requested composition has not passed its acceptance gate."""


@dataclass(frozen=True, slots=True)
class CompositionStatus:
    mode: str
    physical_input_state: str
    live_ready: bool
    blockers: tuple[str, ...]


class AnkaCompositionRoot:
    """Single definitive construction facade for cross-system runtime graphs."""

    @staticmethod
    def status() -> CompositionStatus:
        readiness=assess_live_readiness()
        return CompositionStatus('OFFLINE_VERIFIED_LIVE_BLOCKED','DISABLED',False,readiness.blockers)

    @staticmethod
    def build_zero_input_verification(runtime_dir: Path, *, driver_scenario: str='sent'):
        # Lazy import keeps ordinary setup/check lightweight and makes the fake
        # nature of Q9 explicit at the call site.
        from anka_app.zero_input_integration import ZeroInputQ9Scenario
        return ZeroInputQ9Scenario(Path(runtime_dir),driver_scenario=driver_scenario)

    @staticmethod
    def build_live_runtime(*_args, **_kwargs):
        readiness=assess_live_readiness()
        detail=';'.join(readiness.blockers)
        raise CompositionBlocked('LIVE_RUNTIME_NOT_IMPLEMENTED:'+detail)
