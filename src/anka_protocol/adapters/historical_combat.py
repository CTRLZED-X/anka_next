"""R5.198 Dofus 3.7.10.10 jsq/jwp *research-only* narrow decoder.

Field layouts independently traced to archived ActionProtocolHandlersMixin._jsq
and LifecycleProtocolHandlersMixin._jwp. No historical modules are imported.
Damage/heal and other jsq branches deliberately remain unsupported.
"""
from __future__ import annotations

from hashlib import sha256

from anka_contracts.canonical import EvidenceRef
from anka_contracts.historical_lifecycle import LegacyFightScope
from anka_contracts.historical_combat import HistoricalCombatObservation, HistoricalCombatResult
from anka_contracts.protocol import WireMessage
from anka_protocol.wire import parse_fields, WireRejected

BUILD = 'Dofus 3.7.10.10'
ADAPTER_ID = 'dofus_3_7_10_10_p46_combat_history'
RECOGNIZED = frozenset({'jsq', 'jwp'})


class _ShapeError(ValueError):
    pass


def _int(node: dict, field: int, *, signed: bool = False) -> int:
    values = node.get(field, ())
    if len(values) != 1 or type(values[0]) is not int:
        raise _ShapeError('P46_MISSING_DUPLICATE_OR_WRONG_WIRE_FIELD')
    value = values[0]
    return value - 2**64 if signed and value >= 2**63 else value


def _nested(node: dict, field: int) -> dict:
    values = node.get(field, ())
    if len(values) != 1 or type(values[0]) is not bytes:
        raise _ShapeError('P46_NESTED_BRANCH_MISSING_OR_AMBIGUOUS')
    return parse_fields(values[0])


class HistoricalCombatDecoder:
    """Never certify, stage Canonical, infer causation, or perform input."""
    def __init__(self, *, requested_build: str):
        self.build = requested_build

    def decode(self, message: WireMessage, *, scope: LegacyFightScope | None) -> HistoricalCombatResult:
        base = dict(adapter_id=ADAPTER_ID, protocol_build=self.build, wire_name=message.name)
        if self.build != BUILD:
            return HistoricalCombatResult('BUILD_MISMATCH', **base)
        if message.name not in RECOGNIZED:
            return HistoricalCombatResult('NO_MAPPING', **base)
        if message.direction != 'server_to_client':
            return HistoricalCombatResult('QUARANTINED', failure_code='P46_UNTRUSTED_DIRECTION', **base)
        digest = sha256(message.flow_key.encode('utf8')).hexdigest()
        if (not message.flow_key or not isinstance(scope, LegacyFightScope) or scope.protocol_build != BUILD or
                scope.generation != message.generation or scope.flow_digest != digest):
            return HistoricalCombatResult('SCOPE_UNVERIFIED', **base)
        try:
            node = parse_fields(message.body)
            evidence = EvidenceRef(BUILD, ADAPTER_ID, message.name, message.packet_number,
                                   message.generation, digest, message_index=message.message_index)
            if message.name == 'jwp':
                # Old decoder used this ONLY as an ENDED/RESULT boundary.
                # Payload does not independently establish win, lose or rewards.
                obs = HistoricalCombatObservation('FIGHT_RESULT_BOUNDARY_OBSERVED', evidence, scope.fight_id)
            else:
                aid = _int(node, 22)
                if aid not in (300, 5, 4):
                    return HistoricalCombatResult('UNSUPPORTED_ACTION',
                                                  failure_code='P46_JSQ_ACTION_EFFECT_UNSUPPORTED', **base)
                if aid == 300:
                    source = _int(node, 36, signed=True)
                    branch = _nested(node, 2)
                    spell_box = _nested(branch, 2)
                    obs = HistoricalCombatObservation('CAST_WIRE_OBSERVED', evidence, scope.fight_id,
                        wire_action_type=300, actor_id=source, spell_level_record_id=_int(spell_box, 1),
                        spell_id=_int(spell_box, 2), target_cell_id=_int(branch, 5))
                elif aid == 5:
                    branch = _nested(node, 5)
                    obs = HistoricalCombatObservation('DISPLACEMENT_OBSERVED', evidence, scope.fight_id,
                        wire_action_type=5, actor_id=_int(branch, 1, signed=True),
                        from_cell_id=_int(branch, 2), to_cell_id=_int(branch, 3),
                        displacement_kind='PUSH')
                else:
                    branch = _nested(node, 20)
                    obs = HistoricalCombatObservation('DISPLACEMENT_OBSERVED', evidence, scope.fight_id,
                        wire_action_type=4, actor_id=_int(branch, 2, signed=True),
                        from_cell_id=None, to_cell_id=_int(branch, 1),
                        displacement_kind='TELEPORT')
            return HistoricalCombatResult('OBSERVATIONS_ONLY', observations=(obs,), **base)
        except (_ShapeError, WireRejected, ValueError, TypeError, OverflowError):
            return HistoricalCombatResult('QUARANTINED', failure_code='P46_COMBAT_SCHEMA_OR_VALUE_DRIFT', **base)
