"""P23 independent oracles: a valid early message must not survive later corrupted transport."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anka_app.cli import ROOT
from anka_app.semantic_offline import inspect_semantic_pcapng, MAX_PENDING_SEMANTIC_MESSAGES
from anka_contracts.protocol import WireMessage
from anka_contracts.semantic import SemanticResult
from anka_protocol.adapters.historical_semantic import HistoricalSemanticAdapter
from tests.capture_fixtures import pcapng, packet
from tests.test_protocol_wire import framed, any_body
from tests.test_semantic_p7 import jtk


def _wire(name='jtk', body=None):
    return framed(any_body(name, jtk() if body is None else body))


def _packet_chain(*parts):
    """Make an exact in-order SYN-anchored server stream."""
    result = [packet(seq=100, flags=2, data=b'', reverse=True)]
    seq = 101
    for part in parts:
        result.append(packet(seq=seq, flags=0x18, data=part, reverse=True))
        seq += len(part)
    return result


def _audit(*packets, build='Dofus 3.7.10.10'):
    with tempfile.TemporaryDirectory() as td:
        file = Path(td) / 'synthetic.pcapng'
        file.write_bytes(pcapng(*packets))
        return inspect_semantic_pcapng(file, root=ROOT, ports=(40400,), build=build)


class TestP23TransportFinality(unittest.TestCase):
    def test_clean_evidence_is_still_research_only(self):
        r = _audit(*_packet_chain(_wire()))
        self.assertEqual(r['staged_candidates'], 2)
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['withheld_candidates'], 0)
        self.assertEqual(r['status'], 'HISTORICAL_RESEARCH_ONLY')
        self.assertIsNone(r['first_failure_boundary'])
        self.assertTrue(r['transport_continuity_observed'])
        self.assertFalse(r['live_ready'])
        self.assertFalse(r['live_state_mutated'])
        self.assertFalse(r['physical_input_sent'])

    def test_later_gap_invalidates_previously_decoded_fact(self):
        body = _wire()
        parts = _packet_chain(body)
        parts.append(packet(seq=101 + len(body) + 10, flags=0x18, data=b'bad', reverse=True))
        r = _audit(*parts)
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['withheld_candidates'], 2)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')

    def test_incomplete_frame_after_valid_message_never_stages(self):
        r = _audit(*_packet_chain(_wire(), b'\x80'))
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')
        self.assertGreater(r['wire']['quarantined_streams'], 0)

    def test_tcp_reset_after_valid_message_never_stages(self):
        body = _wire()
        parts = _packet_chain(body)
        parts.append(packet(seq=101 + len(body), flags=0x04, data=b'', reverse=True))
        r = _audit(*parts)
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')

    def test_missing_server_syn_invalidates_batch(self):
        # Client SYN does not establish the server's independent TCP sequence.
        r = _audit(packet(seq=100, flags=2, data=b'', reverse=False),
                   packet(seq=101, flags=0x18, data=_wire(), reverse=True))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')

    def test_new_clean_reconnect_cannot_launder_older_gap(self):
        body = _wire()
        parts = _packet_chain(body)
        parts.extend((packet(seq=101 + len(body) + 10, flags=0x18, data=b'bad', reverse=True),
                      packet(seq=500, flags=2, data=b'', reverse=True),
                      packet(seq=501, flags=0x18, data=body, reverse=True)))
        r = _audit(*parts)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['pending_candidates'], 4)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')

    def test_schema_drift_blocks_earlier_valid_candidates(self):
        r = _audit(*_packet_chain(_wire(), _wire(body=b'\x00')))
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SCHEMA_DRIFT')
        self.assertGreater(r['semantic_status_counts']['QUARANTINED'], 0)

    def test_unknown_background_wire_does_not_poison_valid_research(self):
        r = _audit(*_packet_chain(_wire('new_opaque', b'\x08\x01'), _wire()))
        self.assertEqual(r['staged_candidates'], 2)
        self.assertIsNone(r['first_failure_boundary'])
        self.assertEqual(r['semantic_status_counts']['NO_SEMANTIC_MAPPING'], 1)

    def test_mismatched_build_blocks_all_staging(self):
        r = _audit(*_packet_chain(_wire()), build='Dofus 3.7.11.11')
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_HISTORICAL_BUILD_MISMATCH')
        self.assertEqual(r['semantic_status_counts']['BUILD_MISMATCH'], 1)

    def test_duplicate_looking_envelopes_keep_distinct_ordinals(self):
        r = _audit(*_packet_chain(_wire(), _wire()))
        self.assertEqual(r['staged_candidates'], 4)
        self.assertEqual(r['pending_candidates'], 4)
        self.assertIsNone(r['first_failure_boundary'])

    def test_semantic_callback_exception_rejects_provisional_batch(self):
        original = HistoricalSemanticAdapter.decode
        count = 0
        def failing(self, msg, *, context=None):
            nonlocal count
            count += 1
            if count == 2:
                raise RuntimeError('injected decoder crash')
            return original(self, msg, context=context)
        with patch.object(HistoricalSemanticAdapter, 'decode', failing):
            r = _audit(*_packet_chain(_wire(), _wire()))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['pending_candidates'], 2)
        self.assertEqual(r['first_failure_boundary'], 'P23_TRANSPORT_CONTINUITY_UNPROVEN')

    def test_batch_limit_failure_does_not_leak_partial_candidates(self):
        # Inject a small cap to exercise saturation without huge packet fixtures.
        with patch('anka_app.semantic_offline.MAX_PENDING_SEMANTIC_MESSAGES', 1):
            r = _audit(*_packet_chain(_wire(), _wire()))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_BATCH_LIMIT_EXCEEDED')
        self.assertTrue(r['batch_capacity_exceeded'])

    def test_conflicting_reused_message_coordinates_rejected(self):
        # Independent packet ordinals should avoid collisions. Force a simulated
        # broken producer to reuse a message index and verify batch quarantine.
        from dataclasses import replace
        from anka_contracts.protocol import WireMessage
        # Protocol inspector normally guarantees distinct indices.  The scope
        # here is the higher-level staging batch, with a forged adapter result.
        original = HistoricalSemanticAdapter.decode
        def broken(self, msg, *, context=None):
            result = original(self, msg, context=context)
            if result.candidates:
                items = tuple(replace(x, evidence=replace(x.evidence, packet_number=9,
                                     message_index=0)) for x in result.candidates)
                return replace(result, candidates=items)
            return result
        with patch.object(HistoricalSemanticAdapter, 'decode', broken):
            r = _audit(*_packet_chain(_wire(), _wire()))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH')

    def test_no_payload_paths_or_raw_content_in_receipt(self):
        raw = _wire('private_unknown', b'secret-evidence-payload')
        r = _audit(*_packet_chain(raw, _wire()))
        serialized = json.dumps(r)
        self.assertNotIn('secret-evidence-payload', serialized)
        self.assertNotIn('192.0.2.', serialized)
        self.assertNotIn('.pcapng', serialized)
        self.assertEqual(r['staged_candidates'], 2)


if __name__ == '__main__':
    unittest.main()

class TestP23SourceProvenance(unittest.TestCase):
    def test_wrong_packet_ordinal_is_not_staged(self):
        from dataclasses import replace
        original = HistoricalSemanticAdapter.decode
        def tamper(self, msg, *, context=None):
            r = original(self, msg, context=context)
            return replace(r, candidates=tuple(replace(fact,
                evidence=replace(fact.evidence, packet_number=999)) for fact in r.candidates))
        with patch.object(HistoricalSemanticAdapter, 'decode', tamper):
            r = _audit(*_packet_chain(_wire()))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['source_provenance_mismatches'], 1)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH')

    def test_wrong_flow_digest_is_not_staged(self):
        from dataclasses import replace
        original = HistoricalSemanticAdapter.decode
        def tamper(self, msg, *, context=None):
            r = original(self, msg, context=context)
            return replace(r, candidates=tuple(replace(fact,
                evidence=replace(fact.evidence, flow_digest='f'*64)) for fact in r.candidates))
        with patch.object(HistoricalSemanticAdapter, 'decode', tamper):
            r = _audit(*_packet_chain(_wire()))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH')

    def test_wrong_adapter_reported_by_decoder_rejected_even_without_facts(self):
        from dataclasses import replace
        original = HistoricalSemanticAdapter.decode
        def tamper(self, msg, *, context=None):
            r = original(self, msg, context=context)
            return replace(r, adapter_id='forged_adapter')
        with patch.object(HistoricalSemanticAdapter, 'decode', tamper):
            r = _audit(*_packet_chain(_wire('new_opaque', b'\x08\x01')))
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH')

    def test_provenance_failure_blocks_all_earlier_valid_candidates(self):
        from dataclasses import replace
        original = HistoricalSemanticAdapter.decode
        number = 0
        def tamper(self, msg, *, context=None):
            nonlocal number
            number += 1
            r = original(self, msg, context=context)
            if number == 2:
                return replace(r, candidates=tuple(replace(fact,
                    evidence=replace(fact.evidence, message_index=999)) for fact in r.candidates))
            return r
        with patch.object(HistoricalSemanticAdapter, 'decode', tamper):
            r = _audit(*_packet_chain(_wire(), _wire()))
        self.assertEqual(r['pending_candidates'], 4)
        self.assertEqual(r['withheld_candidates'], 4)
        self.assertEqual(r['staged_candidates'], 0)
        self.assertEqual(r['first_failure_boundary'], 'P23_SEMANTIC_SOURCE_PROVENANCE_MISMATCH')
