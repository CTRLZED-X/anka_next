"""Current-build evidence intake.  It can block or stage; it cannot certify itself."""
from __future__ import annotations
from dataclasses import dataclass

_REQUIRED=('BUILD_FINGERPRINT','CAPTURE_IDENTITY','WORLD','FIGHT_ENTRY','PLACEMENT_READY','FIRST_TURN','TURN_HANDOFF','FIGHT_END_WORLD_REENTRY')
@dataclass(frozen=True,slots=True)
class CurrentBuildAssessment:
    observed_client_build:str
    status:str
    missing_evidence:tuple[str,...]
    may_stage_adapter:bool
    may_activate:bool=False

class CurrentBuildIntake:
    def assess(self,observed_client_build:str|None,evidence_classes)->CurrentBuildAssessment:
        if not observed_client_build:
            return CurrentBuildAssessment('UNKNOWN','BLOCKED_MISSING_BUILD',_REQUIRED,False,False)
        present={str(x) for x in evidence_classes}
        missing=tuple(x for x in _REQUIRED if x not in present)
        if missing:return CurrentBuildAssessment(observed_client_build,'BLOCKED_MISSING_EVIDENCE',missing,True,False)
        # Complete intake permits implementation/replay work, not live activation.
        return CurrentBuildAssessment(observed_client_build,'READY_FOR_ADAPTER_REPLAY_QUALIFICATION',(),True,False)
