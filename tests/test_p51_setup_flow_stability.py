"""P51 permanent source-bound preflight smoke, no live-control promotion."""
import unittest
from pathlib import Path
from anka_app.ingress_readiness import host_flow_stability_smoke
from anka_app.cli import ROOT

class TestP51FlowPreflight(unittest.TestCase):
    def test_three_causal_scenarios(self):
        result=host_flow_stability_smoke()
        self.assertEqual(result['status'],'PASS_RESEARCH_ONLY')
        self.assertEqual(result['scenarios_checked'],3)
        self.assertTrue(result['ambiguous_owner_guarded'])
        self.assertTrue(result['pid_reuse_guarded'])
        self.assertFalse(result['account_binding_verified'])
        self.assertFalse(result['live_certified'])
        self.assertEqual(result['canonical_commits'],0)
        self.assertFalse(result['physical_input_sent'])
    def test_setup_is_wired_to_internal_smoke(self):
        cli=(ROOT/'src/anka_app/cli.py').read_text(encoding='utf8')
        self.assertIn("state['windows_flow_stability'] = host_flow_stability_smoke()",cli)
        self.assertIn("capture.windows_flow_stability_checked",cli)
        self.assertEqual({p.name for p in ROOT.glob('*.bat')},{'setup.bat','start.bat'})
