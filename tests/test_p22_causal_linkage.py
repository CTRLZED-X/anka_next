"""P22 attack the *provenance boundary*, not only resulting actor values."""
from __future__ import annotations
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from anka_app.cli import ROOT
from anka_app.integrated_offline import _fixture_stream, _party_events, _fixture_source_links, run_integrated_fixture
from anka_app.source_link_audit import audit_party_source_links
from anka_contracts.causal_evidence import PartySourceLink, PartySourceAudit
from anka_contracts.coordination_flow import PartyMember
from anka_canonical.journal import SQLiteFixtureJournal
from anka_live_state.reducer import apply_offline_event


class TestP22CausalLinkage(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        with SQLiteFixtureJournal(Path(self.work.name)/'state.sqlite3', reducer=apply_offline_event) as j:
            for evt in (*_fixture_stream('cra', 777, turn=True, ended=True),
                        *_fixture_stream('enu', 888, turn=True)):
                j.append_fixture(evt)
            self.evidence = j.audited_evidence(('cra-session', 'enu-session'))
        self.members = (PartyMember('cra', 1, 777, 'leader'), PartyMember('enu', 1, 888, 'follower'))
        self.party_events = _party_events('handoff')
        self.links = _fixture_source_links(self.party_events)

    def audit(self, **kwargs):
        return audit_party_source_links(members=kwargs.get('members', self.members),
            party_events=kwargs.get('party_events', self.party_events),
            journal_evidence=kwargs.get('journal_evidence', self.evidence),
            links=kwargs.get('links', self.links))

    def assert_blocked(self, expected, **kwargs):
        result = self.audit(**kwargs)
        self.assertEqual(result.status, 'BLOCKED_SYNTHETIC')
        self.assertEqual(result.reasons[0], expected)
        self.assertFalse(result.authoritative)
        self.assertFalse(result.actionable)
        self.assertFalse(result.cross_account_order_verified)

    def test_happy_has_exact_links_but_no_global_clock(self):
        x = self.audit()
        self.assertEqual(x.status, 'PASS_SYNTHETIC_LINKAGE')
        self.assertEqual(x.checked_links, 5)
        self.assertEqual(x.linked_party_events, 4)
        self.assertFalse(x.to_dict()['cross_account_order_verified'])
        self.assertFalse(x.to_dict()['physical_input_permitted'])

    def test_missing_enu_turn_source_fails(self):
        self.assert_blocked('P22_TURN_SOURCE_MISSING_OR_DUPLICATED', links=self.links[:-1])

    def test_missing_one_fight_start_source_fails(self):
        self.assert_blocked('P22_FIGHT_START_SOURCES_MISSING', links=self.links[1:])

    def test_source_event_cannot_be_reused(self):
        self.assert_blocked('P22_SOURCE_REUSED', links=(*self.links, self.links[-1]))

    def test_nonexistent_event_does_not_count_as_observation(self):
        bad = replace(self.links[-1], source_event_id='p20-enu-12345')
        self.assert_blocked('P22_SOURCE_NOT_IN_AUDITED_JOURNAL', links=(*self.links[:-1], bad))

    def test_wrong_journal_kind_rejected(self):
        bad = replace(self.links[-1], source_event_id='p20-enu-7')
        self.assert_blocked('P22_SOURCE_KIND_MISMATCH', links=(*self.links[:-1], bad))

    def test_wrong_actor_rejected_even_if_event_id_exists(self):
        e = list(self.party_events)
        e[-1] = replace(e[-1], actor_id=777)
        self.assert_blocked('P22_SOURCE_ACTOR_MISMATCH', party_events=tuple(e))

    def test_wrong_fight_rejected(self):
        e = list(self.party_events)
        e[-1] = replace(e[-1], fight_id='another-fight')
        self.assert_blocked('P22_SOURCE_FIGHT_MISMATCH', party_events=tuple(e))

    def test_wrong_party_generation_rejected(self):
        e = list(self.party_events)
        e[-1] = replace(e[-1], generation=7)
        self.assert_blocked('P22_SOURCE_ACTOR_MISMATCH', party_events=tuple(e))

    def test_wrong_source_account_generation_rejected(self):
        changed = dict(self.evidence)
        views = dict(changed['views'])
        enu = dict(views['enu-session'])
        enu['events'] = tuple(replace(event, account_generation=77) if event.event_id=='p20-enu-8' else event
                              for event in enu['events'])
        views['enu-session'] = enu
        changed['views'] = views
        self.assert_blocked('P22_SOURCE_ACCOUNT_GENERATION_MISMATCH', journal_evidence=changed)

    def test_unsupported_ready_reference_rejected(self):
        unexpected = PartySourceLink(self.party_events[0].event_id, 'cra-session', 'p20-cra-1')
        self.assert_blocked('P22_UNSUPPORTED_LINK_KIND', links=(*self.links, unexpected))

    def test_unknown_party_reference_rejected(self):
        unexpected = PartySourceLink('invented-event', 'cra-session', 'p20-cra-1')
        self.assert_blocked('P22_UNKNOWN_PARTY_REFERENCE', links=(*self.links, unexpected))

    def test_no_unverified_journal_promotion(self):
        changed = dict(self.evidence, authority='CURRENT_CLIENT_CERTIFIED')
        self.assert_blocked('P22_UNVERIFIED_JOURNAL_EVIDENCE', journal_evidence=changed)

    def test_no_journal_failure_hidden(self):
        changed = dict(self.evidence, audit={'status': 'FAIL'})
        self.assert_blocked('P22_JOURNAL_AUDIT_FAILED', journal_evidence=changed)

    def test_token_validation(self):
        with self.assertRaisesRegex(ValueError, 'P22_SOURCE_LINK_INVALID'):
            PartySourceLink('valid', 'enu-session', '../../file')

    def test_report_authority_cannot_be_forged(self):
        with self.assertRaisesRegex(ValueError, 'P22_AUTHORITY_FORGERY'):
            PartySourceAudit((), 5, 4, actionable=True)
        with self.assertRaises(FrozenInstanceError):
            self.audit().authoritative = True

    def test_historical_scenarios_end_to_end_block_before_decision(self):
        cases = {'source-missing': 'P22_TURN_SOURCE_MISSING_OR_DUPLICATED',
                 'source-reused': 'P22_SOURCE_REUSED',
                 'source-orphan': 'P22_SOURCE_NOT_IN_AUDITED_JOURNAL'}
        for scenario, failure in cases.items():
            with self.subTest(scenario=scenario):
                report = run_integrated_fixture(ROOT, scenario=scenario)
                self.assertEqual(report['first_failure'], failure)
                self.assertEqual(report['fake_attempts'], 0)
                self.assertIsNone(report['decision'])
                self.assertIsNone(report['execution'])
                self.assertIn('integration.source_link_audit', report['boundaries'])

    def test_positive_end_to_end_report_keeps_uncertainty(self):
        report = run_integrated_fixture(ROOT)
        self.assertEqual(report['status'], 'SYNTHETIC_REPLAY_PASS')
        self.assertEqual(report['source_link_audit']['checked_links'], 5)
        self.assertFalse(report['source_link_audit']['cross_account_order_verified'])
        self.assertFalse(report['authoritative'])


if __name__ == '__main__':
    unittest.main()
