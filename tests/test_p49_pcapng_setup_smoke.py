from pathlib import Path
import unittest
from anka_app.historical_pcapng_offline import historical_pcapng_smoke

ROOT = Path(__file__).resolve().parents[1]

class P49SetupSmoke(unittest.TestCase):
    def test_pcapng_smoke_blocks_full_capture_claim(self):
        r=historical_pcapng_smoke(ROOT)
        self.assertEqual(r['status'],'PASS_UNCERTIFIED_HISTORICAL_PCAPNG')
        self.assertEqual(r['observed_research_messages'],3)
        self.assertFalse(r['capture_driver_proof'])
        self.assertFalse(r['account_binding_verified'])
        self.assertFalse(r['live_ready'])
        self.assertEqual(r['canonical_commits'],0)
        self.assertFalse(r['physical_input_sent'])
