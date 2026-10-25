"""P47 end-to-end offline preflight contract for the historical replay facade."""
from __future__ import annotations

import unittest
from anka_app.historical_stream_offline import historical_stream_smoke
from anka_protocol.historical_stream_replay import HistoricalStreamReplay


class P47HistoricalReplaySetupSmoke(unittest.TestCase):
    def test_fast_offline_replay_smoke_detects_clean_partial_and_blocked(self):
        outcome=historical_stream_smoke()
        self.assertEqual(outcome['status'],'PASS_HISTORICAL_RESEARCH_ONLY')
        self.assertEqual(outcome['research_events'],3)
        self.assertEqual(outcome['partial_unknown_wire_detected'],'P47_UNMAPPED_WIRE_SEMANTICS')
        self.assertEqual(outcome['duplicate_wire_block_detected'],'P47_REPEATED_OR_REORDERED_WIRE_SOURCE')
        self.assertIs(outcome['live_ready'],False)
        self.assertIs(outcome['physical_input_sent'],False)
        self.assertEqual(outcome['canonical_commits'],0)

    def test_report_cannot_claim_success_with_a_blocker(self):
        with self.assertRaisesRegex(ValueError,'P47_REPORT_STATUS_REASON_MISMATCH'):
            HistoricalStreamReplay('RESEARCH_REPLAY_ONLY','P47_GAP',None,0,0,0,0,(),(),None,None,None,None)

    def test_clean_report_cannot_claim_live_authority(self):
        report=HistoricalStreamReplay('RESEARCH_REPLAY_ONLY',None,None,0,0,0,0,(),(),None,None,None,None)
        self.assertEqual(report.authority,'HISTORICAL_RESEARCH_ONLY')
        self.assertEqual(report.canonical_commits,0)
        self.assertIs(report.physical_input_sent,False)
        self.assertIs(report.current_client_certified,False)
        self.assertIs(report.actionable,False)
        self.assertIs(report.source_completeness_verified,False)

if __name__=='__main__':unittest.main()
