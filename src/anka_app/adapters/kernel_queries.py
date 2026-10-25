"""M2 host-side adapter for the independently reusable Game Kernel.

This module deliberately lives in ``anka_app``: it may import both the shared
contracts and the standalone Kernel while the Kernel itself remains unaware of
``anka_contracts``.  Static knowledge can prove an action impossible, but it is
never promoted to live execution permission without complete runtime context.
"""
from __future__ import annotations
from dataclasses import dataclass

from anka_contracts.decision import ActionPlan, DecisionFrame
from anka_contracts.mechanics import MechanicsResult
from anka_game_kernel import GameKernel
from anka_game_kernel.domain.ids import CellId, MapId, SpellId
from anka_game_kernel.errors import DefinitionNotFoundError


def _target(plan: ActionPlan) -> dict[str,str]:
    return dict(plan.semantic_target)

@dataclass(frozen=True, slots=True)
class GameKernelQueriesAdapter:
    kernel: GameKernel

    def spell_grade_readiness(self, spell_id: int, grade: int) -> MechanicsResult:
        if type(spell_id) is not int or spell_id < 0 or type(grade) is not int or grade < 1:
            return MechanicsResult('INDETERMINATE','INVALID_OR_UNSCOPED_SPELL_GRADE')
        try:
            report=self.kernel.spell_readiness.grade(SpellId(spell_id),grade)
        except (DefinitionNotFoundError,ValueError,TypeError):
            return MechanicsResult('INDETERMINATE','SPELL_OR_GRADE_NOT_IN_SCOPED_DATA')
        if report.unknown_blockers:
            return MechanicsResult('INDETERMINATE','UNKNOWN_SPELL_MECHANICS',tuple(str(x) for x in report.unknown_blockers))
        if report.unsupported_blockers:
            return MechanicsResult('INDETERMINATE','UNSUPPORTED_SPELL_MECHANICS',tuple(str(x) for x in report.unsupported_blockers))
        # This says the deterministic projection machinery knows the grade.  It
        # does NOT say a live cast is currently legal.
        return MechanicsResult('LEGAL','',{
            'scope':'STATIC_PROJECTION_READINESS_ONLY',
            'live_requirements':tuple(str(x) for x in report.live_requirements),
            'effect_count':report.effect_count,
        })

    def map_cell_walkability(self, map_id: int, cell_id: int) -> MechanicsResult:
        if type(map_id) is not int or map_id <= 0 or type(cell_id) is not int or cell_id < 0:
            return MechanicsResult('INDETERMINATE','INVALID_MAP_OR_CELL_ID')
        try: definition=self.kernel.maps.get(MapId(map_id))
        except (ValueError,TypeError): definition=None
        if definition is None:
            return MechanicsResult('INDETERMINATE','MAP_NOT_IN_SCOPED_DATA')
        try: cid=CellId(cell_id)
        except (ValueError,TypeError): return MechanicsResult('INDETERMINATE','INVALID_CELL_ID')
        cell=next((x for x in definition.cells if x.cell_id==cid),None)
        if cell is None:
            return MechanicsResult('INDETERMINATE','CELL_NOT_IN_SCOPED_DATA')
        if not cell.walkable or cell.non_walkable_during_fight:
            return MechanicsResult('ILLEGAL','STATIC_FIGHT_CELL_NOT_WALKABLE')
        return MechanicsResult('LEGAL','',{'scope':'STATIC_WALKABILITY_ONLY'})

    def validate_plan(self, frame: DecisionFrame, plan: ActionPlan) -> MechanicsResult:
        """Fail-closed transitional bridge for the M1 port.

        A DecisionFrame intentionally does not contain the full immutable
        FightContext needed for complete cast/path legality. Therefore this
        adapter proves only static contradictions and otherwise returns
        INDETERMINATE rather than inventing a live permit.
        """
        if frame.snapshot_id != plan.basis_snapshot_id or frame.canonical_cursor != plan.basis_canonical_cursor:
            return MechanicsResult('ILLEGAL','PLAN_BASIS_MISMATCH')
        target=_target(plan)
        if plan.kind=='CAST':
            try: sid=int(target['spell_id']); grade=int(target['grade'])
            except (KeyError,ValueError,TypeError):
                return MechanicsResult('INDETERMINATE','CAST_CONTEXT_INCOMPLETE')
            ready=self.spell_grade_readiness(sid,grade)
            if ready.status!='LEGAL': return ready
            return MechanicsResult('INDETERMINATE','LIVE_CAST_CONTEXT_REQUIRED',ready.value)
        if plan.kind=='MOVE':
            try: mid=int(target['map_id']); cell=int(target['target_cell'])
            except (KeyError,ValueError,TypeError):
                return MechanicsResult('INDETERMINATE','MOVE_CONTEXT_INCOMPLETE')
            static=self.map_cell_walkability(mid,cell)
            if static.status=='ILLEGAL': return static
            if static.status=='INDETERMINATE': return static
            return MechanicsResult('INDETERMINATE','LIVE_OCCUPANCY_AND_PATH_CONTEXT_REQUIRED',static.value)
        return MechanicsResult('INDETERMINATE','ACTION_KIND_NOT_OWNED_BY_GAME_KERNEL')
