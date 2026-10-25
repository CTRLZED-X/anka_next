from pathlib import Path
import unittest
from anka_app.cli import ROOT
from anka_game_kernel import GameKernel, ExternalGameDataConfig,load_bundled_spell_mechanics_pack
from anka_game_kernel.domain.ids import SpellId

class TestRealKernel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base=ROOT/'assets/game_data'
        cls.kernel=GameKernel.start(ExternalGameDataConfig(
            static_directory=base/'Static',mapuse_directory=base/'Mapuse',
            static_source_version='3.6.10.10',mapuse_source_version='3.6.10.10',
            pack_version='offline-historical-smoke',game_version='3.6.10.10'),
            spell_mechanics=load_bundled_spell_mechanics_pack())
    def test_old_kernel_loaded_from_supplied_static(self):
        self.assertGreater(len(self.kernel.spells),100)
        self.assertGreater(len(self.kernel.monsters),100)
    def test_cra_mechanic_static_and_bundled_grade_match(self):
        spell=self.kernel.spells.require(SpellId(32435))
        self.assertEqual(spell.name,'Flèche Glacée')
        self.assertEqual(len(spell.grades),3)
        self.assertEqual(spell.grades[-1].ap_cost,3)
    def test_historical_data_not_claimed_current_build(self):
        import json
        compatible=json.loads((ROOT/'assets/game_data/COMPATIBILITY.json').read_text())
        self.assertEqual(compatible['source_game_version'],'3.6.10.10')
        self.assertNotIn('LIVE_CERTIFIED', compatible['client_builds']['3.7.10.10']['status'])
