"""P48 preflight runs the actual read-only transport -> research chain."""
import unittest
from pathlib import Path
from anka_app.historical_transport_offline import historical_transport_smoke
from anka_app.cli import _preflight, ROOT

class TestP48Preflight(unittest.TestCase):
    def test_transport_smoke_detects_success_and_hard_blockers(self):
        result=historical_transport_smoke(ROOT)
        self.assertEqual(result['status'],'PASS_HISTORICAL_RESEARCH_ONLY')
        self.assertEqual(result['research_observations'],3)
        self.assertEqual(result['loss_rejected'],'P48_CAPTURE_LOSS_OR_DRIVER_VISIBILITY_UNKNOWN')
        self.assertEqual(result['truncated_frame_rejected'],'P48_PROTOCOL_FRAMING_UNTRUSTED')
        self.assertFalse(result['live_ready'])
        self.assertFalse(result['physical_input_sent'])
        self.assertEqual(result['canonical_commits'],0)

if __name__=='__main__':unittest.main()
