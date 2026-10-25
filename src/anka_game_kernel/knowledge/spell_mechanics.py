from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.resources import as_file, files
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from anka_game_kernel.domain.combat_stats import CombatStatKey, Element
from anka_game_kernel.domain.characteristics import CharacteristicKey
from anka_game_kernel.domain.actor_taxonomy import ActorKind, SummonKind
from anka_game_kernel.domain.effect_conditions import (
    ActorKindCondition,
    AdjacentActorCondition,
    ConditionOperator,
    ConditionSubject,
    EffectConditionSpec,
    EffectTriggerKind,
    PreviousTurnEnemyAttackCountCondition,
    SelectedTargetDistanceCondition,
    SpellTargetSequenceCondition,
    SpellTargetSequenceRelation,
    SelectedTargetTeamRelation,
    SelectedTargetTeamRelationCondition,
    ShieldPresenceCondition,
    StateCondition,
    SummonCondition,
)
from anka_game_kernel.domain.ids import ClassId, CreatureId, EffectId, SpellId, StateId
from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.domain.provenance import Provenance, SourceKind, VerificationStatus
from anka_game_kernel.domain.spell_modifiers import SpellRangeBound, SpellSemanticTag
from anka_game_kernel.domain.spell_effects import (
    APChangeEffectSpec,
    AreaDamageFalloff,
    ApplyStateEffectSpec,
    CharacteristicChangeEffectSpec,
    CharacteristicGainPerAffectedActorEffectSpec,
    CombatStatChangeEffectSpec,
    DamageEffectSpec,
    DamageSourceHealEffectSpec,
    DamageInterceptEffectSpec,
    DamageSourceRelation,
    EffectDurationChangeEffectSpec,
    DisplacementOrigin,
    EffectTargetScope,
    LifeStealEffectSpec,
    HealEffectSpec,
    MPChangeEffectSpec,
    MPStealEffectSpec,
    PerMPUsedModifierEffectSpec,
    PullEffectSpec,
    RecoilEffectSpec,
    PushEffectSpec,
    RemoveStateEffectSpec,
    RangeChangeEffectSpec,
    RevealInvisibleEffectSpec,
    SpellRangeChangeEffectSpec,
    AdditionalAreaOriginsSpec,
    ShieldEffectSpec,
    SummonEffectSpec,
    EffectAreaAnchor,
    SpellBaseDamageChangeEffectSpec,
    SpellCastRuleOverride,
    SpellEffectBranch,
    SpellEffectOccurrence,
    PerTurnCastAreaProgressionSpec,
    SpellGradeMechanics,
    SpellProjectionCapability,
    SpellMechanicsDefinition,
    SwapEffectSpec,
    TeleportEffectSpec,
    TargetSequenceChargeEffectSpec,
)
from anka_game_kernel.domain.values import AmountSpec, ProbabilitySpec, ValueReference, ValueUnit
from anka_game_kernel.mechanics.aoe.model import AreaShape, AreaSpec
from anka_game_kernel.mechanics.targeting.model import EffectTargetClass, EffectTargetSpec
from anka_game_kernel.registries.base import DefinitionRegistry

SPELL_MECHANICS_SCHEMA_VERSION = "1"
SPELL_MECHANICS_IMPORTER_VERSION = "spell-mechanics-v1"
SPELL_MECHANICS_NORMALIZER_VERSION = "spell-mechanics-v1"


class _StrictSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MechanicsSourceProvenance(_StrictSourceModel):
    source_kind: SourceKind
    source_name: str
    source_version: str | None = None
    verification_status: VerificationStatus
    notes: str | None = None


class AmountSource(_StrictSourceModel):
    minimum: int
    maximum: int | None = None
    unit: ValueUnit = ValueUnit.ABSOLUTE
    reference: ValueReference | None = None


class ProbabilitySource(_StrictSourceModel):
    basis_points: int


class AreaSource(_StrictSourceModel):
    shape: AreaShape
    min_radius: int = 0
    radius: int = 0


class TargetSource(_StrictSourceModel):
    allowed_classes: tuple[EffectTargetClass, ...]
    allowed_actor_kinds: tuple[ActorKind, ...] | None = None
    allowed_summon_kinds: tuple[SummonKind, ...] | None = None
    excluded_class_ids: tuple[int, ...] = ()


class AdditionalAreaOriginsSource(_StrictSourceModel):
    owned_creature_ids: tuple[int, ...] = ()


class AreaProgressionSource(_StrictSourceModel):
    stages: tuple[AreaSource, ...]


class ConditionPredicateSource(_StrictSourceModel):
    kind: str
    subject: ConditionSubject
    state_id: int | None = None
    present: bool | None = None
    allowed_kinds: tuple[ActorKind, ...] | None = None
    summoned: bool | None = None
    minimum: int | None = None
    maximum: int | None = None
    relation: SelectedTargetTeamRelation | SpellTargetSequenceRelation | None = None
    minimum_stacks: int | None = None
    maximum_stacks: int | None = None
    summoner_class_id: int | None = None


class EffectConditionSource(_StrictSourceModel):
    operator: ConditionOperator = ConditionOperator.ALL
    predicates: tuple[ConditionPredicateSource, ...]


class DamageParametersSource(_StrictSourceModel):
    element: Element
    amount: AmountSource
    area_falloff: AreaDamageFalloff | None = None


class AmountParametersSource(_StrictSourceModel):
    amount: AmountSource


class DamageSourceHealParametersSource(_StrictSourceModel):
    amount: AmountSource
    source_relation: DamageSourceRelation


class ResourceChangeParametersSource(_StrictSourceModel):
    amount: AmountSource
    dodgeable: bool | None = None


class CharacteristicChangeParametersSource(_StrictSourceModel):
    characteristic: CharacteristicKey
    amount: AmountSource


class CharacteristicGainPerAffectedActorParametersSource(_StrictSourceModel):
    characteristic: CharacteristicKey
    amount_per_actor: AmountSource
    max_affected_actors: int


class CombatStatChangeParametersSource(_StrictSourceModel):
    stat: CombatStatKey
    amount: AmountSource


class PerMPUsedModifierParametersSource(_StrictSourceModel):
    characteristic: CharacteristicKey
    characteristic_delta_per_mp: int
    range_delta_per_mp: int
    max_triggers: int


class SpellBaseDamageChangeParametersSource(_StrictSourceModel):
    affected_spell_id: int
    amount: AmountSource


class SpellRangeChangeParametersSource(_StrictSourceModel):
    bound: SpellRangeBound
    amount: AmountSource
    affected_class_id: int | None = None
    required_tags: tuple[SpellSemanticTag, ...] = ()


class TargetSequenceChargeParametersSource(_StrictSourceModel):
    max_stacks: int
    timeout_turns: int
    timeout_element: Element
    timeout_amounts: tuple[AmountSource, ...]


class DistanceParametersSource(_StrictSourceModel):
    distance: int


class StateParametersSource(_StrictSourceModel):
    state_id: int




class SummonParametersSource(_StrictSourceModel):
    creature_id: int
    summon_kind: SummonKind = SummonKind.NORMAL
    controllable: bool = False
    linked_spell_ids: tuple[int, ...] = ()

class EmptyParametersSource(_StrictSourceModel):
    pass


class EffectOccurrenceSource(_StrictSourceModel):
    order: int
    mechanic: MechanicKey
    parameters: dict[str, Any]
    effect_id: int | None = None
    area: AreaSource | None = None
    area_progression: AreaProgressionSource | None = None
    target: TargetSource | None = None
    target_scope: EffectTargetScope = EffectTargetScope.AREA
    area_anchor: EffectAreaAnchor = EffectAreaAnchor.TARGET_CELL
    displacement_origin: DisplacementOrigin = DisplacementOrigin.CASTER_CELL
    duration_turns: int | None = None
    delay_turns: int | None = None
    max_stacks: int | None = None
    dispellable: bool | None = None
    additional_area_origins: AdditionalAreaOriginsSource | None = None
    probability: ProbabilitySource | None = None
    unresolved_semantics: tuple[str, ...] = ()
    condition: EffectConditionSource | None = None
    trigger: EffectTriggerKind = EffectTriggerKind.IMMEDIATE


class CastRuleOverrideSource(_StrictSourceModel):
    cast_in_diagonal: bool | None = None
    max_global_cast_per_turn: int | None = None
    shared_cooldown: bool | None = None


class SpellGradeMechanicsSource(_StrictSourceModel):
    grade: int
    cast_rule_override: CastRuleOverrideSource | None = None
    certified_projection_capabilities: tuple[SpellProjectionCapability, ...] = ()
    normal_effects: tuple[EffectOccurrenceSource, ...] | None
    critical_effects: tuple[EffectOccurrenceSource, ...] | None


class SpellMechanicsDefinitionSource(_StrictSourceModel):
    spell_id: int
    class_id: int | None = None
    tags: tuple[SpellSemanticTag, ...] = ()
    grades: tuple[SpellGradeMechanicsSource, ...]


class SpellMechanicsPackSource(_StrictSourceModel):
    schema_version: str
    pack_version: str
    game_version: str | None = None
    source: MechanicsSourceProvenance
    spells: tuple[SpellMechanicsDefinitionSource, ...]


@dataclass(frozen=True, slots=True)
class SpellMechanicsPackManifest:
    schema_version: str
    pack_version: str
    game_version: str | None
    source_hash: str
    source_name: str
    source_version: str | None


@dataclass(frozen=True, slots=True)
class SpellMechanicsPack:
    manifest: SpellMechanicsPackManifest
    spells: DefinitionRegistry[SpellId, SpellMechanicsDefinition]


def _amount(source: AmountSource) -> AmountSpec:
    maximum = source.minimum if source.maximum is None else source.maximum
    return AmountSpec(
        minimum=source.minimum,
        maximum=maximum,
        unit=source.unit,
        reference=source.reference,
    )


def _parameters(mechanic: MechanicKey, raw: dict[str, Any]):
    if mechanic is MechanicKey.DAMAGE:
        source = DamageParametersSource.model_validate(raw)
        return DamageEffectSpec(
            element=source.element,
            amount=_amount(source.amount),
            area_falloff=source.area_falloff,
        )
    if mechanic is MechanicKey.LIFESTEAL:
        source = DamageParametersSource.model_validate(raw)
        return LifeStealEffectSpec(
            element=source.element,
            amount=_amount(source.amount),
            area_falloff=source.area_falloff,
        )
    if mechanic is MechanicKey.HEAL:
        source = AmountParametersSource.model_validate(raw)
        return HealEffectSpec(amount=_amount(source.amount))
    if mechanic is MechanicKey.DAMAGE_SOURCE_HEAL:
        source = DamageSourceHealParametersSource.model_validate(raw)
        return DamageSourceHealEffectSpec(
            amount=_amount(source.amount), source_relation=source.source_relation
        )
    if mechanic is MechanicKey.DAMAGE_INTERCEPT:
        EmptyParametersSource.model_validate(raw)
        return DamageInterceptEffectSpec()
    if mechanic is MechanicKey.SHIELD:
        source = AmountParametersSource.model_validate(raw)
        return ShieldEffectSpec(amount=_amount(source.amount))
    if mechanic is MechanicKey.PUSH:
        source = DistanceParametersSource.model_validate(raw)
        return PushEffectSpec(distance=source.distance)
    if mechanic is MechanicKey.PULL:
        source = DistanceParametersSource.model_validate(raw)
        return PullEffectSpec(distance=source.distance)
    if mechanic is MechanicKey.RECOIL:
        source = DistanceParametersSource.model_validate(raw)
        return RecoilEffectSpec(distance=source.distance)
    if mechanic is MechanicKey.TELEPORT:
        EmptyParametersSource.model_validate(raw)
        return TeleportEffectSpec()
    if mechanic is MechanicKey.SWAP:
        EmptyParametersSource.model_validate(raw)
        return SwapEffectSpec()
    if mechanic is MechanicKey.APPLY_STATE:
        source = StateParametersSource.model_validate(raw)
        return ApplyStateEffectSpec(state_id=StateId(source.state_id))
    if mechanic is MechanicKey.REMOVE_STATE:
        source = StateParametersSource.model_validate(raw)
        return RemoveStateEffectSpec(state_id=StateId(source.state_id))
    if mechanic is MechanicKey.AP_CHANGE:
        source = ResourceChangeParametersSource.model_validate(raw)
        return APChangeEffectSpec(amount=_amount(source.amount), dodgeable=source.dodgeable)
    if mechanic is MechanicKey.MP_CHANGE:
        source = ResourceChangeParametersSource.model_validate(raw)
        return MPChangeEffectSpec(amount=_amount(source.amount), dodgeable=source.dodgeable)
    if mechanic is MechanicKey.MP_STEAL:
        source = ResourceChangeParametersSource.model_validate(raw)
        return MPStealEffectSpec(amount=_amount(source.amount), dodgeable=source.dodgeable)
    if mechanic is MechanicKey.RANGE_CHANGE:
        source = AmountParametersSource.model_validate(raw)
        return RangeChangeEffectSpec(amount=_amount(source.amount))
    if mechanic is MechanicKey.EFFECT_DURATION_CHANGE:
        source = AmountParametersSource.model_validate(raw)
        return EffectDurationChangeEffectSpec(amount=_amount(source.amount))
    if mechanic is MechanicKey.SPELL_RANGE_CHANGE:
        source = SpellRangeChangeParametersSource.model_validate(raw)
        return SpellRangeChangeEffectSpec(
            bound=source.bound,
            amount=_amount(source.amount),
            affected_class_id=(
                None if source.affected_class_id is None else ClassId(source.affected_class_id)
            ),
            required_tags=frozenset(source.required_tags),
        )
    if mechanic is MechanicKey.CHARACTERISTIC_CHANGE:
        source = CharacteristicChangeParametersSource.model_validate(raw)
        return CharacteristicChangeEffectSpec(
            characteristic=source.characteristic, amount=_amount(source.amount)
        )
    if mechanic is MechanicKey.CHARACTERISTIC_GAIN_PER_AFFECTED_ACTOR:
        source = CharacteristicGainPerAffectedActorParametersSource.model_validate(raw)
        return CharacteristicGainPerAffectedActorEffectSpec(
            characteristic=source.characteristic,
            amount_per_actor=_amount(source.amount_per_actor),
            max_affected_actors=source.max_affected_actors,
        )
    if mechanic is MechanicKey.COMBAT_STAT_CHANGE:
        source = CombatStatChangeParametersSource.model_validate(raw)
        return CombatStatChangeEffectSpec(stat=source.stat, amount=_amount(source.amount))
    if mechanic is MechanicKey.PER_MP_USED_MODIFIER:
        source = PerMPUsedModifierParametersSource.model_validate(raw)
        return PerMPUsedModifierEffectSpec(
            characteristic=source.characteristic,
            characteristic_delta_per_mp=source.characteristic_delta_per_mp,
            range_delta_per_mp=source.range_delta_per_mp,
            max_triggers=source.max_triggers,
        )
    if mechanic is MechanicKey.SPELL_BASE_DAMAGE_CHANGE:
        source = SpellBaseDamageChangeParametersSource.model_validate(raw)
        return SpellBaseDamageChangeEffectSpec(
            affected_spell_id=SpellId(source.affected_spell_id),
            amount=_amount(source.amount),
        )
    if mechanic is MechanicKey.REVEAL_INVISIBLE:
        EmptyParametersSource.model_validate(raw)
        return RevealInvisibleEffectSpec()
    if mechanic is MechanicKey.SUMMON:
        source = SummonParametersSource.model_validate(raw)
        return SummonEffectSpec(
            creature_id=CreatureId(source.creature_id),
            summon_kind=source.summon_kind,
            controllable=source.controllable,
            linked_spell_ids=tuple(SpellId(item) for item in source.linked_spell_ids),
        )
    if mechanic is MechanicKey.TARGET_SEQUENCE_CHARGE:
        source = TargetSequenceChargeParametersSource.model_validate(raw)
        return TargetSequenceChargeEffectSpec(
            max_stacks=source.max_stacks,
            timeout_turns=source.timeout_turns,
            timeout_element=source.timeout_element,
            timeout_amounts=tuple(_amount(item) for item in source.timeout_amounts),
        )
    raise ValueError(
        f"mechanic {mechanic.value} has no R7A canonical parameter schema"
    )


def _condition(source: EffectConditionSource | None) -> EffectConditionSpec | None:
    if source is None:
        return None
    predicates = []
    for item in source.predicates:
        if item.kind == "state":
            if item.state_id is None:
                raise ValueError("state condition requires state_id")
            if item.allowed_kinds is not None or item.summoned is not None:
                raise ValueError("state condition contains incompatible fields")
            predicates.append(
                StateCondition(
                    subject=item.subject,
                    state_id=StateId(item.state_id),
                    present=True if item.present is None else item.present,
                )
            )
            continue
        if item.kind == "actor_kind":
            if not item.allowed_kinds:
                raise ValueError("actor_kind condition requires allowed_kinds")
            if item.state_id is not None or item.present is not None or item.summoned is not None:
                raise ValueError("actor_kind condition contains incompatible fields")
            predicates.append(
                ActorKindCondition(
                    subject=item.subject,
                    allowed_kinds=frozenset(item.allowed_kinds),
                )
            )
            continue
        if item.kind == "summoned":
            if item.summoned is None:
                raise ValueError("summoned condition requires summoned")
            if item.state_id is not None or item.present is not None or item.allowed_kinds is not None:
                raise ValueError("summoned condition contains incompatible fields")
            predicates.append(SummonCondition(subject=item.subject, summoned=item.summoned))
            continue
        if item.kind == "shield_present":
            if item.state_id is not None or item.allowed_kinds is not None or item.summoned is not None:
                raise ValueError("shield_present condition contains incompatible fields")
            predicates.append(
                ShieldPresenceCondition(
                    subject=item.subject,
                    present=True if item.present is None else item.present,
                )
            )
            continue
        if item.kind == "selected_target_distance":
            if item.state_id is not None or item.allowed_kinds is not None or item.summoned is not None or item.present is not None:
                raise ValueError("selected_target_distance condition contains incompatible fields")
            predicates.append(
                SelectedTargetDistanceCondition(
                    subject=item.subject,
                    minimum=item.minimum,
                    maximum=item.maximum,
                )
            )
            continue
        if item.kind == "selected_target_team_relation":
            if item.relation is None:
                raise ValueError("selected_target_team_relation condition requires relation")
            if (
                item.state_id is not None
                or item.allowed_kinds is not None
                or item.summoned is not None
                or item.present is not None
                or item.minimum is not None
                or item.maximum is not None
            ):
                raise ValueError("selected_target_team_relation condition contains incompatible fields")
            predicates.append(
                SelectedTargetTeamRelationCondition(
                    subject=item.subject,
                    relation=item.relation,
                )
            )
            continue
        if item.kind == "adjacent_actor":
            if item.state_id is not None or item.present is not None or item.allowed_kinds is not None:
                raise ValueError("adjacent_actor condition contains incompatible fields")
            if item.minimum is not None or item.maximum is not None or item.minimum_stacks is not None or item.maximum_stacks is not None:
                raise ValueError("adjacent_actor condition contains incompatible numeric fields")
            if item.relation is not None and not isinstance(item.relation, SelectedTargetTeamRelation):
                raise ValueError("adjacent_actor relation must be ally/enemy when supplied")
            predicates.append(
                AdjacentActorCondition(
                    subject=item.subject,
                    relation=item.relation,
                    summoned=item.summoned,
                    summoner_class_id=(
                        None if item.summoner_class_id is None else ClassId(item.summoner_class_id)
                    ),
                )
            )
            continue
        if item.kind == "previous_turn_enemy_attacks_received":
            if item.state_id is not None or item.allowed_kinds is not None or item.summoned is not None or item.present is not None:
                raise ValueError("previous_turn_enemy_attacks_received condition contains incompatible fields")
            predicates.append(
                PreviousTurnEnemyAttackCountCondition(
                    subject=item.subject,
                    minimum=item.minimum,
                    maximum=item.maximum,
                )
            )
            continue
        if item.kind == "spell_target_sequence":
            if not isinstance(item.relation, SpellTargetSequenceRelation):
                raise ValueError("spell_target_sequence condition requires a sequence relation")
            if (
                item.state_id is not None
                or item.allowed_kinds is not None
                or item.summoned is not None
                or item.present is not None
                or item.minimum is not None
                or item.maximum is not None
            ):
                raise ValueError("spell_target_sequence condition contains incompatible fields")
            predicates.append(
                SpellTargetSequenceCondition(
                    subject=item.subject,
                    relation=item.relation,
                    minimum_stacks=item.minimum_stacks,
                    maximum_stacks=item.maximum_stacks,
                )
            )
            continue
        raise ValueError(f"unsupported effect condition kind {item.kind!r}")
    return EffectConditionSpec(operator=source.operator, predicates=tuple(predicates))


def _provenance(
    *,
    source: MechanicsSourceProvenance,
    path: Path,
    source_hash: str,
    game_version: str | None,
    record_id: str,
) -> Provenance:
    return Provenance(
        source_kind=source.source_kind,
        source_name=source.source_name,
        source_version=source.source_version,
        source_file=path.name,
        source_record_id=record_id,
        game_version=game_version,
        verification_status=source.verification_status,
        source_hash=source_hash,
        importer_version=SPELL_MECHANICS_IMPORTER_VERSION,
        normalizer_version=SPELL_MECHANICS_NORMALIZER_VERSION,
        notes=source.notes,
    )


def _occurrences(
    *,
    raw_effects: tuple[EffectOccurrenceSource, ...] | None,
    spell_id: SpellId,
    grade: int,
    branch: SpellEffectBranch,
    source: MechanicsSourceProvenance,
    path: Path,
    source_hash: str,
    game_version: str | None,
) -> tuple[SpellEffectOccurrence, ...] | None:
    if raw_effects is None:
        return None
    result: list[SpellEffectOccurrence] = []
    for item in raw_effects:
        result.append(
            SpellEffectOccurrence(
                spell_id=spell_id,
                grade=grade,
                branch=branch,
                order=item.order,
                mechanic_key=item.mechanic,
                parameters=_parameters(item.mechanic, item.parameters),
                effect_id=None if item.effect_id is None else EffectId(item.effect_id),
                area=None
                if item.area is None
                else AreaSpec(
                    shape=item.area.shape,
                    min_radius=item.area.min_radius,
                    radius=item.area.radius,
                ),
                area_progression=(
                    None
                    if item.area_progression is None
                    else PerTurnCastAreaProgressionSpec(
                        stages=tuple(
                            AreaSpec(
                                shape=stage.shape,
                                min_radius=stage.min_radius,
                                radius=stage.radius,
                            )
                            for stage in item.area_progression.stages
                        )
                    )
                ),
                target=None
                if item.target is None
                else EffectTargetSpec(
                    allowed_classes=frozenset(item.target.allowed_classes),
                    allowed_actor_kinds=(
                        None
                        if item.target.allowed_actor_kinds is None
                        else frozenset(item.target.allowed_actor_kinds)
                    ),
                    allowed_summon_kinds=(
                        None
                        if item.target.allowed_summon_kinds is None
                        else frozenset(item.target.allowed_summon_kinds)
                    ),
                    excluded_class_ids=frozenset(
                        ClassId(value) for value in item.target.excluded_class_ids
                    ),
                ),
                target_scope=item.target_scope,
                area_anchor=item.area_anchor,
                displacement_origin=item.displacement_origin,
                duration_turns=item.duration_turns,
                delay_turns=item.delay_turns,
                max_stacks=item.max_stacks,
                dispellable=item.dispellable,
                additional_area_origins=(
                    None
                    if item.additional_area_origins is None
                    else AdditionalAreaOriginsSpec(
                        owned_creature_ids=frozenset(
                            CreatureId(value)
                            for value in item.additional_area_origins.owned_creature_ids
                        )
                    )
                ),
                probability=None
                if item.probability is None
                else ProbabilitySpec(basis_points=item.probability.basis_points),
                unresolved_semantics=item.unresolved_semantics,
                condition=_condition(item.condition),
                trigger=item.trigger,
                provenance=_provenance(
                    source=source,
                    path=path,
                    source_hash=source_hash,
                    game_version=game_version,
                    record_id=(
                        f"spell:{int(spell_id)}/grade:{grade}/"
                        f"{branch.value}:{item.order}"
                    ),
                ),
            )
        )
    return tuple(result)


def load_spell_mechanics_pack(path: str | Path) -> SpellMechanicsPack:
    source_path = Path(path)
    if not source_path.is_file():
        raise ValueError(f"missing spell mechanics source file: {source_path}")
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    raw = json.loads(source_bytes)
    source_pack = SpellMechanicsPackSource.model_validate(raw)
    if source_pack.schema_version != SPELL_MECHANICS_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported spell mechanics schema version {source_pack.schema_version!r}; "
            f"expected {SPELL_MECHANICS_SCHEMA_VERSION!r}"
        )

    definitions: list[SpellMechanicsDefinition] = []
    for spell in source_pack.spells:
        spell_id = SpellId(spell.spell_id)
        grades: list[SpellGradeMechanics] = []
        for grade in spell.grades:
            grade_provenance = _provenance(
                source=source_pack.source,
                path=source_path,
                source_hash=source_hash,
                game_version=source_pack.game_version,
                record_id=f"spell:{spell.spell_id}/grade:{grade.grade}",
            )
            grades.append(
                SpellGradeMechanics(
                    spell_id=spell_id,
                    grade=grade.grade,
                    normal_effects=_occurrences(
                        raw_effects=grade.normal_effects,
                        spell_id=spell_id,
                        grade=grade.grade,
                        branch=SpellEffectBranch.NORMAL,
                        source=source_pack.source,
                        path=source_path,
                        source_hash=source_hash,
                        game_version=source_pack.game_version,
                    ),
                    critical_effects=_occurrences(
                        raw_effects=grade.critical_effects,
                        spell_id=spell_id,
                        grade=grade.grade,
                        branch=SpellEffectBranch.CRITICAL,
                        source=source_pack.source,
                        path=source_path,
                        source_hash=source_hash,
                        game_version=source_pack.game_version,
                    ),
                    provenance=grade_provenance,
                    certified_projection_capabilities=frozenset(
                        grade.certified_projection_capabilities
                    ),
                    cast_rule_override=(
                        None
                        if grade.cast_rule_override is None
                        else SpellCastRuleOverride(
                            cast_in_diagonal=grade.cast_rule_override.cast_in_diagonal,
                            max_global_cast_per_turn=grade.cast_rule_override.max_global_cast_per_turn,
                            shared_cooldown=grade.cast_rule_override.shared_cooldown,
                        )
                    ),
                )
            )
        definitions.append(
            SpellMechanicsDefinition(
                spell_id=spell_id,
                grades=tuple(grades),
                class_id=None if spell.class_id is None else ClassId(spell.class_id),
                tags=frozenset(spell.tags),
                provenance=_provenance(
                    source=source_pack.source,
                    path=source_path,
                    source_hash=source_hash,
                    game_version=source_pack.game_version,
                    record_id=f"spell:{spell.spell_id}",
                ),
            )
        )

    registry = DefinitionRegistry.from_items(definitions, key=lambda item: item.spell_id)
    return SpellMechanicsPack(
        manifest=SpellMechanicsPackManifest(
            schema_version=source_pack.schema_version,
            pack_version=source_pack.pack_version,
            game_version=source_pack.game_version,
            source_hash=source_hash,
            source_name=source_pack.source.source_name,
            source_version=source_pack.source.source_version,
        ),
        spells=registry,
    )


def load_bundled_spell_mechanics_pack() -> SpellMechanicsPack:
    resource = files("anka_game_kernel").joinpath(
        "data", "spell_mechanics", "verified_spells.json"
    )
    with as_file(resource) as path:
        return load_spell_mechanics_pack(path)
