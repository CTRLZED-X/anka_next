from __future__ import annotations
import unittest
from anka_app.cli import ROOT
from anka_app.adapters.kernel_queries import GameKernelQueriesAdapter
from anka_contracts.decision import ActionPlan, DecisionFrame
from anka_game_kernel import GameKernel, ExternalGameDataConfig, load_bundled_spell_mechanics_pack

class TestM2KernelAdapter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=ROOT/'assets'/'game_data'
        kernel=GameKernel.start(ExternalGameDataConfig(base/'Static',base/'Mapuse','3.6.10.10','3.6.10.10','m2-adapter','3.6.10.10'),spell_mechanics=load_bundled_spell_mechanics_pack())
        cls.adapter=GameKernelQueriesAdapter(kernel)

    def test_known_spell_structural_readiness_never_becomes_live_plan_permission(self):
        ready=self.adapter.spell_grade_readiness(32435,3)
        self.assertIn(ready.status,('LEGAL','INDETERMINATE'))
        frame=DecisionFrame('frame-m2','run-m2','acct-cra',1,1,'snap-m2',4,'FIGHT_PROGRESS')
        plan=ActionPlan('plan-m2','a'*64,'CAST',(('spell_id','32435'),('grade','3')),('CAST_CONSEQUENCE',),'snap-m2',4)
        self.assertEqual(self.adapter.validate_plan(frame,plan).status,'INDETERMINATE')
        self.assertEqual(self.adapter.validate_plan(frame,plan).reason,'LIVE_CAST_CONTEXT_REQUIRED')

    def test_missing_spell_fails_indeterminate_not_guessed(self):
        result=self.adapter.spell_grade_readiness(999999999,1)
        self.assertEqual(result.status,'INDETERMINATE')

    def test_static_nonwalkable_cell_can_prove_illegal_but_walkable_is_not_live_move_permission(self):
        # Inspect the scoped map to choose one deterministic example of each type.
        definition=next(iter(self.adapter.kernel.maps))
        blocked=next(c for c in definition.cells if (not c.walkable or c.non_walkable_during_fight))
        walkable=next(c for c in definition.cells if c.walkable and not c.non_walkable_during_fight)
        self.assertEqual(self.adapter.map_cell_walkability(int(definition.map_id),int(blocked.cell_id)).status,'ILLEGAL')
        self.assertEqual(self.adapter.map_cell_walkability(int(definition.map_id),int(walkable.cell_id)).status,'LEGAL')
        frame=DecisionFrame('frame-move','run-m2','acct-cra',1,1,'snap-move',5,'FIGHT_PROGRESS')
        plan=ActionPlan('plan-move','b'*64,'MOVE',(('map_id',str(int(definition.map_id))),('target_cell',str(int(walkable.cell_id)))),('CELL_CHANGED',),'snap-move',5)
        result=self.adapter.validate_plan(frame,plan)
        self.assertEqual(result.status,'INDETERMINATE')
        self.assertEqual(result.reason,'LIVE_OCCUPANCY_AND_PATH_CONTEXT_REQUIRED')

    def test_stale_plan_basis_is_illegal_before_any_mechanics_claim(self):
        frame=DecisionFrame('frame-stale','run-m2','acct-cra',1,1,'snap-a',8,'FIGHT_PROGRESS')
        plan=ActionPlan('plan-stale','c'*64,'END_TURN',(),('NEXT_TURN_OWNER',),'snap-b',7)
        self.assertEqual(self.adapter.validate_plan(frame,plan).status,'ILLEGAL')
        self.assertEqual(self.adapter.validate_plan(frame,plan).reason,'PLAN_BASIS_MISMATCH')

    def test_scoped_cra_enu_classes_and_all_verified_spell_mechanics_are_loadable(self):
        classes={int(c.class_id):c.name for c in self.adapter.kernel.classes}
        self.assertEqual(classes[9],'Crâ')
        self.assertEqual(classes[3],'Enutrof')
        pack=self.adapter.kernel.spell_mechanics
        self.assertIsNotNone(pack)
        self.assertEqual(len(pack.spells),47)
        for definition in pack.spells:
            static=self.adapter.kernel.spells.get(definition.spell_id)
            self.assertIsNotNone(static, int(definition.spell_id))
            # Every mechanics grade must produce an explicit readiness result; unsupported
            # or incomplete knowledge is allowed but may never crash or be guessed.
            for grade in definition.grades:
                result=self.adapter.spell_grade_readiness(int(definition.spell_id),grade.grade)
                self.assertIn(result.status,('LEGAL','INDETERMINATE'))

if __name__=='__main__': unittest.main()
