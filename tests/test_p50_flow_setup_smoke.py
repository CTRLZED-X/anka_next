"""P50 bootstrap must exercise the new source-bound flow inventory."""
from pathlib import Path
from unittest import TestCase
from anka_app.historical_pcapng_inventory_offline import historical_flow_inventory_smoke

ROOT=Path(__file__).resolve().parents[1]

class P50FlowInventorySmoke(TestCase):
    def test_setup_candidate_flow_remains_research_only(self):
        report=historical_flow_inventory_smoke(ROOT)
        self.assertEqual(report['status'],'PASS_CANDIDATE_FLOW_ONLY')
        self.assertEqual(report['candidate_flows'],1)
        self.assertEqual(report['historical_messages'],3)
        self.assertFalse(report['capture_complete'])
        self.assertFalse(report['account_binding_verified'])
        self.assertEqual(report['canonical_commits'],0)
        self.assertFalse(report['physical_input_sent'])
