"""P46 independent hand-authored byte-shape oracles, not current/live packets."""
from __future__ import annotations

import hashlib
import unittest
from dataclasses import replace

from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.historical_combat import HistoricalCombatObservation, HistoricalCombatResult
from anka_contracts.protocol import WireMessage
from anka_protocol.adapters.historical_combat import HistoricalCombatDecoder, BUILD
from anka_protocol.historical_combat_audit import audit_historical_combat


def varint(value: int) -> bytes:
    b = bytearray()
    while value > 127:
        b.append((value & 127) | 128)
        value >>= 7
    b.append(value)
    return bytes(b)


def unsigned(field: int, value: int) -> bytes:
    return varint(field << 3) + varint(value)


def branch(field: int, payload: bytes) -> bytes:
    return varint((field << 3) | 2) + varint(len(payload)) + payload


def sint(value: int) -> int:
    return value if value >= 0 else (1 << 64) + value


def cast(*, actor=-38, spell=32435, level=86146, cell=251):
    return (unsigned(22, 300) + unsigned(36, sint(actor)) +
            branch(2, branch(2, unsigned(1, level) + unsigned(2, spell)) + unsigned(5, cell)))


def push(*, actor=-51, before=123, after=124):
    return (unsigned(22, 5) + branch(5, unsigned(1, sint(actor)) +
            unsigned(2, before) + unsigned(3, after)))


def teleport(*, actor=33, after=201):
    return unsigned(22, 4) + branch(20, unsigned(1, after) + unsigned(2, sint(actor)))


class P46CombatResearchTests(unittest.TestCase):
    def setUp(self):
        self.decode = HistoricalCombatDecoder(requested_build=BUILD)
        self.scope = LegacyFightScope(401, hashlib.sha256(b'CRA_FLOW').hexdigest(), 7, BUILD)

    def msg(self, name='jsq', payload=None, packet=5, index=0, flow='CRA_FLOW',
            direction='server_to_client', generation=7):
        if payload is None:
            payload = cast()
        return WireMessage(direction, name, payload, packet, flow, generation, index)

    def obs(self, message):
        r = self.decode.decode(message, scope=self.scope)
        self.assertEqual(r.status, 'OBSERVATIONS_ONLY', r.failure_code)
        self.assertEqual(r.canonical_commits, 0)
        self.assertFalse(r.physical_input_sent)
        return r.observations[0]

    def test_cast_field_mapping_distinguishes_spell_level_record_id_from_ordinal(self):
        o = self.obs(self.msg(payload=cast()))
        self.assertEqual((o.kind, o.actor_id, o.spell_id, o.spell_level_record_id, o.target_cell_id),
                         ('CAST_WIRE_OBSERVED', -38, 32435, 86146, 251))
        self.assertEqual(o.wire_action_type, 300)
        self.assertEqual(o.authority, 'HISTORICAL_RESEARCH_ONLY')
        self.assertEqual(o.outcome, 'UNKNOWN')
        self.assertFalse(o.server_effect_confirmed)
        self.assertFalse(o.victory_confirmed)

    def test_push_has_target_and_two_explicit_cells_but_no_spell_attribution(self):
        o = self.obs(self.msg(payload=push()))
        self.assertEqual((o.kind, o.displacement_kind, o.actor_id, o.from_cell_id, o.to_cell_id),
                         ('DISPLACEMENT_OBSERVED', 'PUSH', -51, 123, 124))
        self.assertIsNone(o.spell_id)

    def test_teleport_target_has_no_invented_origin(self):
        o = self.obs(self.msg(payload=teleport()))
        self.assertEqual((o.displacement_kind, o.actor_id, o.to_cell_id), ('TELEPORT', 33, 201))
        self.assertIsNone(o.from_cell_id)

    def test_jwp_marks_terminal_boundary_not_victory_or_rewards(self):
        o = self.obs(self.msg('jwp', b'', packet=8))
        self.assertEqual(o.kind, 'FIGHT_RESULT_BOUNDARY_OBSERVED')
        self.assertEqual(o.outcome, 'UNKNOWN')
        self.assertIsNone(o.actor_id)
        self.assertFalse(o.victory_confirmed)

    def test_malformed_result_payload_cannot_be_accepted_as_terminal(self):
        r = self.decode.decode(self.msg('jwp', b'\x08\x80'), scope=self.scope)
        self.assertEqual(r.status, 'QUARANTINED')

    def test_cast_then_push_then_result_coherent_not_causally_settled(self):
        sequence = (self.obs(self.msg(packet=1)),
                    self.obs(self.msg(payload=push(), packet=2)),
                    self.obs(self.msg('jwp', b'\x08\x01', packet=3)))
        r = audit_historical_combat(sequence)
        self.assertEqual(r.status, 'RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED')
        self.assertEqual((r.cast_records, r.displacement_records, r.result_boundaries), (1, 1, 1))
        self.assertIn('CAST_TO_DAMAGE_OR_HEAL_UNPROVEN', r.unsupported_causation)
        self.assertFalse(r.authoritative)
        self.assertFalse(r.live_ready)
        self.assertFalse(r.physical_input_sent)

    def test_target_moves_without_preceding_spell_still_research_coherent(self):
        r = audit_historical_combat((self.obs(self.msg(payload=push(), packet=1)),))
        self.assertEqual(r.status, 'RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED')
        self.assertEqual(r.cast_records, 0)
        self.assertEqual(r.displacement_records, 1)

    def test_result_does_not_certify_world_reentry(self):
        r = audit_historical_combat((self.obs(self.msg('jwp', b'', packet=1)),))
        self.assertEqual(r.result_boundaries, 1)
        self.assertIn('FIGHT_WIN_LOSS_UNVERIFIED', r.unsupported_causation)

    def test_after_terminal_cannot_extend_same_research_fight(self):
        r = audit_historical_combat((self.obs(self.msg('jwp', b'', packet=1)),
                                     self.obs(self.msg(payload=cast(), packet=2))))
        self.assertEqual((r.status, r.first_issue), ('ORDER_CONFLICT', 'P46_OBSERVATION_AFTER_RESULT'))

    def test_duplicate_result_not_accepted(self):
        r = audit_historical_combat((self.obs(self.msg('jwp', b'', packet=1)),
                                     self.obs(self.msg('jwp', b'', packet=2))))
        self.assertEqual(r.first_issue, 'P46_OBSERVATION_AFTER_RESULT')

    def test_duplicate_source_rejected_even_if_different_action_body(self):
        r = audit_historical_combat((self.obs(self.msg(payload=cast())),
                                     self.obs(self.msg(payload=push()))))
        self.assertEqual(r.first_issue, 'P46_DUPLICATE_OR_REORDERED_SOURCE')

    def test_same_packet_distinct_message_indices_can_be_ordered(self):
        r = audit_historical_combat((self.obs(self.msg(packet=5, index=0)),
                                     self.obs(self.msg(payload=push(), packet=5, index=1))))
        self.assertEqual(r.status, 'RESEARCH_SEQUENCE_COHERENT_NOT_CERTIFIED')

    def test_wrong_or_reordered_index_blocked(self):
        r = audit_historical_combat((self.obs(self.msg(packet=5, index=2)),
                                     self.obs(self.msg(payload=push(), packet=5, index=1))))
        self.assertEqual(r.first_issue, 'P46_DUPLICATE_OR_REORDERED_SOURCE')

    def test_cross_flow_fight_and_build_rejected(self):
        a = self.obs(self.msg(packet=1))
        other = self.obs(self.msg(payload=push(), packet=2))
        cases = (replace(other, fight_id=77),
                 replace(other, evidence=replace(other.evidence, flow_digest='1'*64)),
                 replace(other, evidence=replace(other.evidence, transport_generation=11)),
                 replace(other, evidence=replace(other.evidence, protocol_build='Dofus 3.7.11.11')),
                 replace(other, evidence=replace(other.evidence, adapter_id='unknown_adapter')))
        for altered in cases:
            with self.subTest(variant=altered.evidence):
                r = audit_historical_combat((a, altered))
                self.assertEqual(r.first_issue, 'P46_MIXED_FIGHT_FLOW_OR_BUILD')

    def test_wrong_build_scope_and_direction_never_yield_observations(self):
        variants = (
            HistoricalCombatDecoder(requested_build='Dofus 3.7.11.11').decode(self.msg(), scope=self.scope),
            self.decode.decode(self.msg(direction='client_to_server'), scope=self.scope),
            self.decode.decode(self.msg(flow='ENU_FLOW'), scope=self.scope),
            self.decode.decode(self.msg(generation=8), scope=self.scope),
            self.decode.decode(self.msg(), scope=None),
        )
        self.assertEqual([x.status for x in variants],
                         ['BUILD_MISMATCH', 'QUARANTINED', 'SCOPE_UNVERIFIED', 'SCOPE_UNVERIFIED', 'SCOPE_UNVERIFIED'])
        self.assertTrue(all(not x.observations and not x.physical_input_sent for x in variants))

    def test_old_messages_only_recognized_when_names_explicit(self):
        r = self.decode.decode(self.msg('jtk', b''), scope=self.scope)
        self.assertEqual(r.status, 'NO_MAPPING')

    def test_known_other_jsq_action_unsupported_without_false_damagelike_event(self):
        r = self.decode.decode(self.msg(payload=unsigned(22, 80) + unsigned(36, 33)), scope=self.scope)
        self.assertEqual((r.status, r.failure_code),
                         ('UNSUPPORTED_ACTION', 'P46_JSQ_ACTION_EFFECT_UNSUPPORTED'))
        self.assertFalse(r.observations)

    def test_unknown_jsq_action_also_unsupported(self):
        r = self.decode.decode(self.msg(payload=unsigned(22, 987654)), scope=self.scope)
        self.assertEqual(r.status, 'UNSUPPORTED_ACTION')

    def test_missing_or_double_action_id_quarantined(self):
        for body in (b'', unsigned(22, 300) + unsigned(22, 300) + branch(2, b'')):
            with self.subTest(body=body):
                self.assertEqual(self.decode.decode(self.msg(payload=body), scope=self.scope).status, 'QUARANTINED')

    def test_duplicate_required_nested_fields_quarantined(self):
        spell = branch(2, unsigned(1, 86146) + unsigned(1, 86146) + unsigned(2, 32435))
        r = self.decode.decode(self.msg(payload=unsigned(22, 300) + unsigned(36, 1) + branch(2, spell + unsigned(5, 1))), scope=self.scope)
        self.assertEqual(r.status, 'QUARANTINED')

    def test_wrong_nested_type_quarantined(self):
        r = self.decode.decode(self.msg(payload=unsigned(22, 300) + unsigned(36, 1) + unsigned(2, 5)), scope=self.scope)
        self.assertEqual(r.status, 'QUARANTINED')

    def test_truncated_wire_quarantined(self):
        self.assertEqual(self.decode.decode(self.msg(payload=b'\xb0\x01\x80'), scope=self.scope).status, 'QUARANTINED')

    def test_out_of_range_cells_and_actor_zero_quarantined(self):
        for body in (cast(cell=560), cast(actor=0), cast(spell=0), cast(level=0),
                     push(after=560), teleport(actor=0), teleport(after=900),
                     push(before=560)):
            with self.subTest(body=body):
                self.assertEqual(self.decode.decode(self.msg(payload=body), scope=self.scope).status, 'QUARANTINED')

    def test_valid_cell_zero_not_falsely_blocked(self):
        o = self.obs(self.msg(payload=cast(cell=0)))
        self.assertEqual(o.target_cell_id, 0)

    def test_missing_teleport_origin_stays_none_not_zero(self):
        o = self.obs(self.msg(payload=teleport(after=0)))
        self.assertIsNone(o.from_cell_id)

    def test_empty_sequence_explicitly_insufficient(self):
        self.assertEqual(audit_historical_combat(()).first_issue, 'P46_EMPTY_SEQUENCE')

    def test_non_observation_object_not_silently_accepted(self):
        self.assertEqual(audit_historical_combat(('invalid',)).first_issue, 'P46_NOT_AN_OBSERVATION')

    def test_contract_blocks_invented_success(self):
        o = self.obs(self.msg())
        with self.assertRaises((AttributeError, TypeError)):
            o.victory_confirmed = True
        with self.assertRaises((AttributeError, TypeError)):
            o.server_effect_confirmed = True
        with self.assertRaises(ValueError):
            HistoricalCombatObservation('FIGHT_RESULT_BOUNDARY_OBSERVED', o.evidence, 401, actor_id=33)

    def test_combat_result_rejects_unbacked_observations(self):
        with self.assertRaises(ValueError):
            HistoricalCombatResult('OBSERVATIONS_ONLY', 'a', BUILD, 'jsq')
        with self.assertRaises(ValueError):
            HistoricalCombatResult('UNSUPPORTED_ACTION', 'a', BUILD, 'jsq')

if __name__ == '__main__':
    unittest.main()
