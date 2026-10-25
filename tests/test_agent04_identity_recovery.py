"""Chat 04 identity recovery/restart evidence regressions."""
from __future__ import annotations

import unittest

from anka_client.discovery import bind_accounts
from anka_contracts.client import CharacterEvidence, WindowObservation, WindowScan


NOW = 55_000_000_000


def window(*, created: int = 1000) -> WindowObservation:
    return WindowObservation(
        100, 300, created, 'Dofus.exe', 'Curseni - Dofus',
        1280, 649, 96, False,
    )


def evidence(*, created: int = 1000, source: str = 'LIVE_PROTOCOL',
             at: int = NOW - 10, breed: str = 'CRA') -> CharacterEvidence:
    return CharacterEvidence(source, 'Curseni', breed, 100, 300, created, at)


class Agent04IdentityRecoveryTests(unittest.TestCase):
    def test_old_process_generation_does_not_poison_fresh_current_evidence(self):
        scan = WindowScan(NOW, (window(created=2000),))
        result = bind_accounts(
            ('Curseni',), scan,
            (evidence(created=1000), evidence(created=2000)),
        )[0]
        self.assertEqual((result.state, result.breed), ('IDENTITY_MATCHED', 'CRA'))

    def test_stale_same_generation_record_does_not_poison_fresh_record(self):
        scan = WindowScan(NOW, (window(),))
        result = bind_accounts(
            ('Curseni',), scan,
            (evidence(at=NOW - 4_000_000_000), evidence(at=NOW - 10)),
        )[0]
        self.assertEqual(result.state, 'IDENTITY_MATCHED')

    def test_untrusted_record_does_not_poison_fresh_trusted_record(self):
        scan = WindowScan(NOW, (window(),))
        result = bind_accounts(
            ('Curseni',), scan,
            (evidence(source='TITLE'), evidence(source='LIVE_PROTOCOL')),
        )[0]
        self.assertEqual(result.state, 'IDENTITY_MATCHED')

    def test_two_fresh_trusted_records_remain_ambiguous(self):
        scan = WindowScan(NOW, (window(),))
        result = bind_accounts(
            ('Curseni',), scan,
            (evidence(source='LIVE_PROTOCOL'), evidence(source='UNITY_BRIDGE')),
        )[0]
        self.assertEqual((result.state, result.reason),
                         ('BLOCKED', 'AMBIGUOUS_CHARACTER_EVIDENCE'))

    def test_only_old_generation_still_blocks(self):
        scan = WindowScan(NOW, (window(created=2000),))
        result = bind_accounts(('Curseni',), scan, (evidence(created=1000),))[0]
        self.assertEqual((result.state, result.reason),
                         ('BLOCKED', 'PROCESS_GENERATION_CHANGED'))


if __name__ == '__main__':
    unittest.main()
