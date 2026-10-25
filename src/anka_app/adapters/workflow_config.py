"""Composition-root adapter from app configuration to Workflow contracts."""
from __future__ import annotations
from pathlib import Path
from anka_app.configuration import RunConfiguration
from anka_contracts.workflow import MissionConfigSpec, EffectiveMissionPlan
from anka_workflow.compiler import compile_mission


def compile_run_mission(config: RunConfiguration, root: Path, *, watchdog_budget_ticks: int = 5, recovery_budget: int = 2) -> EffectiveMissionPlan:
    m=config.mission
    contract=MissionConfigSpec(m.route_id,m.min_monsters,m.max_monsters,m.target_wins,m.max_attempts,m.stop_on_loss,m.stop_on_unknown,config.sha256)
    return compile_mission(contract,Path(root)/'assets/workflow/routes.json',watchdog_budget_ticks=watchdog_budget_ticks,recovery_budget=recovery_budget)
