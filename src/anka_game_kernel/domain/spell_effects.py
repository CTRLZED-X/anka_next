from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from anka_game_kernel.domain.combat_stats import CombatStatKey, Element
from anka_game_kernel.domain.actor_taxonomy import SummonKind
from anka_game_kernel.domain.characteristics import CharacteristicKey
from anka_game_kernel.domain.effect_conditions import EffectConditionSpec, EffectTriggerKind
from anka_game_kernel.domain.ids import ClassId, CreatureId, EffectId, SpellId, StateId
from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.domain.provenance import Provenance
from anka_game_kernel.domain.spell_modifiers import SpellRangeBound, SpellSemanticTag
from anka_game_kernel.domain.values import AmountSpec, ProbabilitySpec
from anka_game_kernel.mechanics.aoe.model import AreaSpec
from anka_game_kernel.mechanics.targeting.model import EffectTargetSpec


class AreaDamageFalloff(StrEnum):
    DEGRESSIVE = "degressive"
    NON_DEGRESSIVE = "non_degressive"


class DamageSourceRelation(StrEnum):
    """Relation of the damage-source actor to the effect holder at trigger time."""

    ALLY = "ally"
    ENEMY = "enemy"
    ANY = "any"


@dataclass(frozen=True, slots=True)
class DamageInterceptEffectSpec:
    """Live-event damage interception aura.

    The actor occupying the effect anchor is the interceptor; eligible actors in the
    declared area are protected recipients. Damage routing and resulting HP remain
    authoritative runtime outcomes.
    """


@dataclass(frozen=True, slots=True)
class AdditionalAreaOriginsSpec:
    """Extra area centers supplied by caster-owned creature templates."""

    owned_creature_ids: frozenset[CreatureId] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.owned_creature_ids, frozenset):
            raise TypeError("owned_creature_ids must be a frozenset of CreatureId values")
        if any(not isinstance(value, CreatureId) for value in self.owned_creature_ids):
            raise TypeError("owned_creature_ids must contain CreatureId values")


@dataclass(frozen=True, slots=True)
class SpellRangeChangeEffectSpec:
    """Temporary selector-based change to a spell's intrinsic min/max cast range."""

    bound: SpellRangeBound
    amount: AmountSpec
    affected_class_id: ClassId | None = None
    required_tags: frozenset[SpellSemanticTag] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.bound, SpellRangeBound):
            raise TypeError("bound must be a SpellRangeBound")
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")
        if self.affected_class_id is not None and not isinstance(self.affected_class_id, ClassId):
            raise TypeError("affected_class_id must be a ClassId or None")
        if not isinstance(self.required_tags, frozenset):
            raise TypeError("required_tags must be a frozenset of SpellSemanticTag values")
        if any(not isinstance(value, SpellSemanticTag) for value in self.required_tags):
            raise TypeError("required_tags must contain SpellSemanticTag values")


class SpellEffectBranch(StrEnum):
    NORMAL = "normal"
    CRITICAL = "critical"


class SpellProjectionCapability(StrEnum):
    """Projection capabilities certified for one spell grade by focused evidence/tests."""

    ARBITRARY_ANGLE_LOS = "arbitrary_angle_los"
    EIGHT_DIRECTION_DISPLACEMENT = "eight_direction_displacement"
    RADIAL_CROSS_DISPLACEMENT = "radial_cross_displacement"
    DIRECTIONAL_LINE_MULTI_TARGET_DISPLACEMENT = "directional_line_multi_target_displacement"
    DIRECTION_GROUPED_MULTI_TARGET_DISPLACEMENT = "direction_grouped_multi_target_displacement"


class EffectAreaAnchor(StrEnum):
    TARGET_CELL = "target_cell"
    CASTER_CELL = "caster_cell"
    PRIOR_SEQUENCE_TARGET_CELL = "prior_sequence_target_cell"


class EffectTargetScope(StrEnum):
    AREA = "area"
    CASTER_LINE_OF_SIGHT = "caster_line_of_sight"
    FIGHT = "fight"


class DisplacementOrigin(StrEnum):
    """Reference cell used to determine push/pull direction."""

    CASTER_CELL = "caster_cell"
    SELECTED_TARGET_CELL = "selected_target_cell"


def _require_non_negative_int(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < 0:
        raise ValueError(f"{name} cannot be negative")


def _require_non_negative_amount(name: str, amount: AmountSpec) -> None:
    if not isinstance(amount, AmountSpec):
        raise TypeError(f"{name} must be an AmountSpec")
    if amount.minimum < 0:
        raise ValueError(f"{name} cannot be negative")




@dataclass(frozen=True, slots=True)
class SummonEffectSpec:
    """Create a controllable/non-controllable summon template on the selected free CellId.

    Runtime actor identity and numeric stats remain live-authoritative; the Kernel owns
    deterministic placement, team/ownership and creature-template semantics.
    """

    creature_id: CreatureId
    summon_kind: SummonKind = SummonKind.NORMAL
    controllable: bool = False
    linked_spell_ids: tuple[SpellId, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.creature_id, CreatureId):
            raise TypeError("creature_id must be a CreatureId")
        if not isinstance(self.summon_kind, SummonKind):
            raise TypeError("summon_kind must be a SummonKind")
        if not isinstance(self.controllable, bool):
            raise TypeError("controllable must be a bool")
        if not isinstance(self.linked_spell_ids, tuple):
            raise TypeError("linked_spell_ids must be a tuple")
        if any(not isinstance(item, SpellId) for item in self.linked_spell_ids):
            raise TypeError("linked_spell_ids must contain SpellId values")

@dataclass(frozen=True, slots=True)
class DamageEffectSpec:
    element: Element
    amount: AmountSpec
    area_falloff: AreaDamageFalloff | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.element, Element):
            raise TypeError("element must be an Element")
        _require_non_negative_amount("damage amount", self.amount)
        if self.area_falloff is not None and not isinstance(self.area_falloff, AreaDamageFalloff):
            raise TypeError("area_falloff must be an AreaDamageFalloff or None")


@dataclass(frozen=True, slots=True)
class LifeStealEffectSpec:
    """Server-authoritative elemental damage whose resulting heal returns to the caster."""

    element: Element
    amount: AmountSpec
    area_falloff: AreaDamageFalloff | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.element, Element):
            raise TypeError("element must be an Element")
        _require_non_negative_amount("lifesteal amount", self.amount)
        if self.area_falloff is not None and not isinstance(self.area_falloff, AreaDamageFalloff):
            raise TypeError("area_falloff must be an AreaDamageFalloff or None")


@dataclass(frozen=True, slots=True)
class HealEffectSpec:
    amount: AmountSpec

    def __post_init__(self) -> None:
        _require_non_negative_amount("heal amount", self.amount)


@dataclass(frozen=True, slots=True)
class DamageSourceHealEffectSpec:
    """Heal the actor that damaged the effect holder when a damage trigger fires.

    The damage-source identity and the triggering damage amount are runtime-event facts,
    so this spec is intentionally declarative/live-authoritative rather than projected.
    """

    amount: AmountSpec
    source_relation: DamageSourceRelation

    def __post_init__(self) -> None:
        _require_non_negative_amount("damage-source heal amount", self.amount)
        if not isinstance(self.source_relation, DamageSourceRelation):
            raise TypeError("source_relation must be a DamageSourceRelation")


@dataclass(frozen=True, slots=True)
class ShieldEffectSpec:
    amount: AmountSpec

    def __post_init__(self) -> None:
        _require_non_negative_amount("shield amount", self.amount)


@dataclass(frozen=True, slots=True)
class PushEffectSpec:
    distance: int

    def __post_init__(self) -> None:
        _require_non_negative_int("distance", self.distance)


@dataclass(frozen=True, slots=True)
class PullEffectSpec:
    distance: int

    def __post_init__(self) -> None:
        _require_non_negative_int("distance", self.distance)


@dataclass(frozen=True, slots=True)
class RecoilEffectSpec:
    """Move the caster away from the selected cast target/reference cell."""

    distance: int

    def __post_init__(self) -> None:
        _require_non_negative_int("distance", self.distance)


@dataclass(frozen=True, slots=True)
class TeleportEffectSpec:
    pass


@dataclass(frozen=True, slots=True)
class SwapEffectSpec:
    pass


@dataclass(frozen=True, slots=True)
class ApplyStateEffectSpec:
    state_id: StateId

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, StateId):
            raise TypeError("state_id must be a StateId")


@dataclass(frozen=True, slots=True)
class RemoveStateEffectSpec:
    state_id: StateId

    def __post_init__(self) -> None:
        if not isinstance(self.state_id, StateId):
            raise TypeError("state_id must be a StateId")


@dataclass(frozen=True, slots=True)
class APChangeEffectSpec:
    amount: AmountSpec
    dodgeable: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")
        if self.dodgeable is not None and not isinstance(self.dodgeable, bool):
            raise TypeError("dodgeable must be a bool or None")


@dataclass(frozen=True, slots=True)
class MPChangeEffectSpec:
    amount: AmountSpec
    dodgeable: bool | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")
        if self.dodgeable is not None and not isinstance(self.dodgeable, bool):
            raise TypeError("dodgeable must be a bool or None")


@dataclass(frozen=True, slots=True)
class MPStealEffectSpec:
    """Dodgeable/non-dodgeable MP transfer from affected target to caster.

    Positive ``amount`` represents how much MP is stolen. For dodgeable steals the
    final target loss and caster gain are authoritative live outcomes and are not
    projected optimistically by the Kernel.
    """

    amount: AmountSpec
    dodgeable: bool | None = None

    def __post_init__(self) -> None:
        _require_non_negative_amount("MP steal amount", self.amount)
        if self.dodgeable is not None and not isinstance(self.dodgeable, bool):
            raise TypeError("dodgeable must be a bool or None")


@dataclass(frozen=True, slots=True)
class RangeChangeEffectSpec:
    amount: AmountSpec

    def __post_init__(self) -> None:
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")


@dataclass(frozen=True, slots=True)
class EffectDurationChangeEffectSpec:
    """Change the remaining duration of dispellable active effects on affected actors.

    The exact runtime set of reducible effects remains live-authoritative unless a future
    canonical snapshot carries complete dispelability/lifecycle semantics.
    """

    amount: AmountSpec

    def __post_init__(self) -> None:
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")


@dataclass(frozen=True, slots=True)
class CharacteristicChangeEffectSpec:
    characteristic: CharacteristicKey
    amount: AmountSpec

    def __post_init__(self) -> None:
        if not isinstance(self.characteristic, CharacteristicKey):
            raise TypeError("characteristic must be a CharacteristicKey")
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")


@dataclass(frozen=True, slots=True)
class CharacteristicGainPerAffectedActorEffectSpec:
    """Caster gain scaled by the number of actors selected by this effect occurrence."""

    characteristic: CharacteristicKey
    amount_per_actor: AmountSpec
    max_affected_actors: int

    def __post_init__(self) -> None:
        if not isinstance(self.characteristic, CharacteristicKey):
            raise TypeError("characteristic must be a CharacteristicKey")
        if not isinstance(self.amount_per_actor, AmountSpec):
            raise TypeError("amount_per_actor must be an AmountSpec")
        if isinstance(self.max_affected_actors, bool) or not isinstance(self.max_affected_actors, int):
            raise TypeError("max_affected_actors must be an int")
        if self.max_affected_actors < 1:
            raise ValueError("max_affected_actors must be >= 1")


@dataclass(frozen=True, slots=True)
class CombatStatChangeEffectSpec:
    """Fixed modifier to a canonical ActorCombatStats field."""

    stat: CombatStatKey
    amount: AmountSpec

    def __post_init__(self) -> None:
        if not isinstance(self.stat, CombatStatKey):
            raise TypeError("stat must be a CombatStatKey")
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")


@dataclass(frozen=True, slots=True)
class RevealInvisibleEffectSpec:
    """Reveal invisible entities in the effect area; visibility settlement remains live-authoritative."""

    pass


@dataclass(frozen=True, slots=True)
class PerMPUsedModifierEffectSpec:
    """Reactive modifier reduced once for every MP spent on movement."""

    characteristic: CharacteristicKey
    characteristic_delta_per_mp: int
    range_delta_per_mp: int
    max_triggers: int

    def __post_init__(self) -> None:
        if not isinstance(self.characteristic, CharacteristicKey):
            raise TypeError("characteristic must be a CharacteristicKey")
        for name, value in (
            ("characteristic_delta_per_mp", self.characteristic_delta_per_mp),
            ("range_delta_per_mp", self.range_delta_per_mp),
            ("max_triggers", self.max_triggers),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an int")
        if self.max_triggers < 1:
            raise ValueError("max_triggers must be >= 1")




@dataclass(frozen=True, slots=True)
class TargetSequenceChargeEffectSpec:
    """Track one target for a stacking spell sequence with a live-authoritative timeout.

    ``timeout_amounts`` records the verified discharge damage ladder for future planners.
    The Kernel can project stack/target changes caused by a hypothetical cast, while expiry
    and no-action timeout triggering remain caller/live-authoritative.
    """

    max_stacks: int
    timeout_turns: int
    timeout_element: Element
    timeout_amounts: tuple[AmountSpec, ...]

    def __post_init__(self) -> None:
        _require_non_negative_int("max_stacks", self.max_stacks)
        _require_non_negative_int("timeout_turns", self.timeout_turns)
        if self.max_stacks < 1:
            raise ValueError("max_stacks must be >= 1")
        if self.timeout_turns < 1:
            raise ValueError("timeout_turns must be >= 1")
        if not isinstance(self.timeout_element, Element):
            raise TypeError("timeout_element must be an Element")
        if not isinstance(self.timeout_amounts, tuple):
            raise TypeError("timeout_amounts must be a tuple of AmountSpec values")
        if len(self.timeout_amounts) != self.max_stacks:
            raise ValueError("timeout_amounts length must equal max_stacks")
        if any(not isinstance(item, AmountSpec) for item in self.timeout_amounts):
            raise TypeError("timeout_amounts must contain AmountSpec values")
        for item in self.timeout_amounts:
            _require_non_negative_amount("timeout discharge amount", item)


@dataclass(frozen=True, slots=True)
class SpellBaseDamageChangeEffectSpec:
    affected_spell_id: SpellId
    amount: AmountSpec

    def __post_init__(self) -> None:
        if not isinstance(self.affected_spell_id, SpellId):
            raise TypeError("affected_spell_id must be a SpellId")
        if not isinstance(self.amount, AmountSpec):
            raise TypeError("amount must be an AmountSpec")


EffectParameterSpec: TypeAlias = (
    DamageEffectSpec
    | LifeStealEffectSpec
    | HealEffectSpec
    | DamageSourceHealEffectSpec
    | DamageInterceptEffectSpec
    | ShieldEffectSpec
    | PushEffectSpec
    | PullEffectSpec
    | RecoilEffectSpec
    | TeleportEffectSpec
    | SwapEffectSpec
    | ApplyStateEffectSpec
    | RemoveStateEffectSpec
    | APChangeEffectSpec
    | MPChangeEffectSpec
    | MPStealEffectSpec
    | RangeChangeEffectSpec
    | EffectDurationChangeEffectSpec
    | SpellRangeChangeEffectSpec
    | CharacteristicChangeEffectSpec
    | CharacteristicGainPerAffectedActorEffectSpec
    | CombatStatChangeEffectSpec
    | SpellBaseDamageChangeEffectSpec
    | RevealInvisibleEffectSpec
    | PerMPUsedModifierEffectSpec
    | TargetSequenceChargeEffectSpec
    | SummonEffectSpec
)


_PARAMETER_MECHANICS: dict[type[object], MechanicKey] = {
    DamageEffectSpec: MechanicKey.DAMAGE,
    LifeStealEffectSpec: MechanicKey.LIFESTEAL,
    HealEffectSpec: MechanicKey.HEAL,
    DamageSourceHealEffectSpec: MechanicKey.DAMAGE_SOURCE_HEAL,
    DamageInterceptEffectSpec: MechanicKey.DAMAGE_INTERCEPT,
    ShieldEffectSpec: MechanicKey.SHIELD,
    PushEffectSpec: MechanicKey.PUSH,
    PullEffectSpec: MechanicKey.PULL,
    RecoilEffectSpec: MechanicKey.RECOIL,
    TeleportEffectSpec: MechanicKey.TELEPORT,
    SwapEffectSpec: MechanicKey.SWAP,
    ApplyStateEffectSpec: MechanicKey.APPLY_STATE,
    RemoveStateEffectSpec: MechanicKey.REMOVE_STATE,
    APChangeEffectSpec: MechanicKey.AP_CHANGE,
    MPChangeEffectSpec: MechanicKey.MP_CHANGE,
    MPStealEffectSpec: MechanicKey.MP_STEAL,
    RangeChangeEffectSpec: MechanicKey.RANGE_CHANGE,
    EffectDurationChangeEffectSpec: MechanicKey.EFFECT_DURATION_CHANGE,
    SpellRangeChangeEffectSpec: MechanicKey.SPELL_RANGE_CHANGE,
    CharacteristicChangeEffectSpec: MechanicKey.CHARACTERISTIC_CHANGE,
    CharacteristicGainPerAffectedActorEffectSpec: MechanicKey.CHARACTERISTIC_GAIN_PER_AFFECTED_ACTOR,
    CombatStatChangeEffectSpec: MechanicKey.COMBAT_STAT_CHANGE,
    SpellBaseDamageChangeEffectSpec: MechanicKey.SPELL_BASE_DAMAGE_CHANGE,
    RevealInvisibleEffectSpec: MechanicKey.REVEAL_INVISIBLE,
    PerMPUsedModifierEffectSpec: MechanicKey.PER_MP_USED_MODIFIER,
    TargetSequenceChargeEffectSpec: MechanicKey.TARGET_SEQUENCE_CHARGE,
    SummonEffectSpec: MechanicKey.SUMMON,
}


def mechanic_key_for_parameters(parameters: EffectParameterSpec) -> MechanicKey:
    mechanic = _PARAMETER_MECHANICS.get(type(parameters))
    if mechanic is None:
        raise TypeError(f"unsupported canonical effect parameter spec {type(parameters).__name__}")
    return mechanic


@dataclass(frozen=True, slots=True)
class PerTurnCastAreaProgressionSpec:
    """Effect areas selected by this spell's 1-based cast count in the active turn."""

    stages: tuple[AreaSpec, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.stages, tuple):
            raise TypeError("stages must be a tuple of AreaSpec values")
        if not self.stages:
            raise ValueError("stages cannot be empty")
        if any(not isinstance(stage, AreaSpec) for stage in self.stages):
            raise TypeError("stages must contain AreaSpec values")


@dataclass(frozen=True, slots=True)
class SpellEffectOccurrence:
    spell_id: SpellId
    grade: int
    branch: SpellEffectBranch
    order: int
    mechanic_key: MechanicKey
    parameters: EffectParameterSpec
    provenance: Provenance
    effect_id: EffectId | None = None
    area: AreaSpec | None = None
    area_progression: PerTurnCastAreaProgressionSpec | None = None
    target: EffectTargetSpec | None = None
    target_scope: EffectTargetScope = EffectTargetScope.AREA
    area_anchor: EffectAreaAnchor = EffectAreaAnchor.TARGET_CELL
    displacement_origin: DisplacementOrigin = DisplacementOrigin.CASTER_CELL
    duration_turns: int | None = None
    delay_turns: int | None = None
    max_stacks: int | None = None
    dispellable: bool | None = None
    additional_area_origins: AdditionalAreaOriginsSpec | None = None
    probability: ProbabilitySpec | None = None
    unresolved_semantics: tuple[str, ...] = ()
    condition: EffectConditionSpec | None = None
    trigger: EffectTriggerKind = EffectTriggerKind.IMMEDIATE

    def __post_init__(self) -> None:
        if not isinstance(self.spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        _require_non_negative_int("order", self.order)
        if isinstance(self.grade, bool) or not isinstance(self.grade, int):
            raise TypeError("grade must be an int")
        if self.grade < 1:
            raise ValueError("grade must be >= 1")
        if not isinstance(self.branch, SpellEffectBranch):
            raise TypeError("branch must be a SpellEffectBranch")
        if not isinstance(self.mechanic_key, MechanicKey):
            raise TypeError("mechanic_key must be a MechanicKey")
        expected = mechanic_key_for_parameters(self.parameters)
        if self.mechanic_key is not expected:
            raise ValueError(
                f"mechanic_key {self.mechanic_key.value} does not match "
                f"{type(self.parameters).__name__} ({expected.value})"
            )
        if self.effect_id is not None and not isinstance(self.effect_id, EffectId):
            raise TypeError("effect_id must be an EffectId or None")
        if self.area is not None and not isinstance(self.area, AreaSpec):
            raise TypeError("area must be an AreaSpec or None")
        if self.area_progression is not None and not isinstance(
            self.area_progression, PerTurnCastAreaProgressionSpec
        ):
            raise TypeError(
                "area_progression must be a PerTurnCastAreaProgressionSpec or None"
            )
        if self.target is not None and not isinstance(self.target, EffectTargetSpec):
            raise TypeError("target must be an EffectTargetSpec or None")
        if not isinstance(self.target_scope, EffectTargetScope):
            raise TypeError("target_scope must be an EffectTargetScope")
        if not isinstance(self.area_anchor, EffectAreaAnchor):
            raise TypeError("area_anchor must be an EffectAreaAnchor")
        if not isinstance(self.displacement_origin, DisplacementOrigin):
            raise TypeError("displacement_origin must be a DisplacementOrigin")
        if self.duration_turns is not None:
            _require_non_negative_int("duration_turns", self.duration_turns)
        if self.delay_turns is not None:
            _require_non_negative_int("delay_turns", self.delay_turns)
        if self.max_stacks is not None:
            if isinstance(self.max_stacks, bool) or not isinstance(self.max_stacks, int):
                raise TypeError("max_stacks must be an int or None")
            if self.max_stacks < 1:
                raise ValueError("max_stacks must be >= 1 when supplied")
        if self.dispellable is not None and not isinstance(self.dispellable, bool):
            raise TypeError("dispellable must be a bool or None")
        if self.additional_area_origins is not None and not isinstance(
            self.additional_area_origins, AdditionalAreaOriginsSpec
        ):
            raise TypeError("additional_area_origins must be an AdditionalAreaOriginsSpec or None")
        if self.probability is not None and not isinstance(self.probability, ProbabilitySpec):
            raise TypeError("probability must be a ProbabilitySpec or None")
        if self.condition is not None and not isinstance(self.condition, EffectConditionSpec):
            raise TypeError("condition must be an EffectConditionSpec or None")
        if not isinstance(self.trigger, EffectTriggerKind):
            raise TypeError("trigger must be an EffectTriggerKind")
        if not isinstance(self.provenance, Provenance):
            raise TypeError("provenance must be Provenance")
        if any(not isinstance(item, str) or not item.strip() for item in self.unresolved_semantics):
            raise ValueError("unresolved_semantics must contain non-empty strings")
        if len(set(self.unresolved_semantics)) != len(self.unresolved_semantics):
            raise ValueError("unresolved_semantics cannot contain duplicates")


def _validate_branch(
    *,
    label: str,
    effects: tuple[SpellEffectOccurrence, ...] | None,
    expected_branch: SpellEffectBranch,
    spell_id: SpellId,
    grade: int,
) -> None:
    if effects is None:
        return
    for effect in effects:
        if not isinstance(effect, SpellEffectOccurrence):
            raise TypeError(f"{label} must contain SpellEffectOccurrence values")
        if effect.spell_id != spell_id or effect.grade != grade:
            raise ValueError(f"{label} effect spell/grade backreference mismatch")
        if effect.branch is not expected_branch:
            raise ValueError(f"{label} effects must use {expected_branch.name} branch")
    orders = tuple(effect.order for effect in effects)
    if orders != tuple(range(len(effects))):
        raise ValueError(f"{label} effect order must be contiguous from zero")


@dataclass(frozen=True, slots=True)
class SpellCastRuleOverride:
    """Verified supplemental cast-rule fields absent or contradicted by the Static export.

    The raw Static grade is never mutated; consumers opt into the resolved overlay view.
    """

    cast_in_diagonal: bool | None = None
    max_global_cast_per_turn: int | None = None
    shared_cooldown: bool | None = None

    def __post_init__(self) -> None:
        if self.cast_in_diagonal is not None and not isinstance(self.cast_in_diagonal, bool):
            raise TypeError("cast_in_diagonal must be a bool or None")
        if self.shared_cooldown is not None and not isinstance(self.shared_cooldown, bool):
            raise TypeError("shared_cooldown must be a bool or None")
        if self.max_global_cast_per_turn is not None:
            if isinstance(self.max_global_cast_per_turn, bool) or not isinstance(self.max_global_cast_per_turn, int):
                raise TypeError("max_global_cast_per_turn must be an int or None")
            if self.max_global_cast_per_turn < 0:
                raise ValueError("max_global_cast_per_turn cannot be negative")


@dataclass(frozen=True, slots=True)
class SpellGradeMechanics:
    spell_id: SpellId
    grade: int
    normal_effects: tuple[SpellEffectOccurrence, ...] | None
    critical_effects: tuple[SpellEffectOccurrence, ...] | None
    provenance: Provenance
    cast_rule_override: SpellCastRuleOverride | None = None
    certified_projection_capabilities: frozenset[SpellProjectionCapability] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if isinstance(self.grade, bool) or not isinstance(self.grade, int):
            raise TypeError("grade must be an int")
        if self.grade < 1:
            raise ValueError("grade must be >= 1")
        if not isinstance(self.provenance, Provenance):
            raise TypeError("provenance must be Provenance")
        if self.cast_rule_override is not None and not isinstance(
            self.cast_rule_override, SpellCastRuleOverride
        ):
            raise TypeError("cast_rule_override must be a SpellCastRuleOverride or None")
        if not isinstance(self.certified_projection_capabilities, frozenset):
            raise TypeError("certified_projection_capabilities must be a frozenset")
        if any(
            not isinstance(item, SpellProjectionCapability)
            for item in self.certified_projection_capabilities
        ):
            raise TypeError(
                "certified_projection_capabilities must contain SpellProjectionCapability values"
            )
        _validate_branch(
            label="normal",
            effects=self.normal_effects,
            expected_branch=SpellEffectBranch.NORMAL,
            spell_id=self.spell_id,
            grade=self.grade,
        )
        _validate_branch(
            label="critical",
            effects=self.critical_effects,
            expected_branch=SpellEffectBranch.CRITICAL,
            spell_id=self.spell_id,
            grade=self.grade,
        )


@dataclass(frozen=True, slots=True)
class SpellMechanicsDefinition:
    spell_id: SpellId
    grades: tuple[SpellGradeMechanics, ...]
    provenance: Provenance
    class_id: ClassId | None = None
    tags: frozenset[SpellSemanticTag] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if not isinstance(self.provenance, Provenance):
            raise TypeError("provenance must be Provenance")
        if self.class_id is not None and not isinstance(self.class_id, ClassId):
            raise TypeError("class_id must be a ClassId or None")
        if not isinstance(self.tags, frozenset):
            raise TypeError("tags must be a frozenset of SpellSemanticTag values")
        if any(not isinstance(item, SpellSemanticTag) for item in self.tags):
            raise TypeError("tags must contain SpellSemanticTag values")
        if any(not isinstance(item, SpellGradeMechanics) for item in self.grades):
            raise TypeError("grades must contain SpellGradeMechanics values")
        if any(item.spell_id != self.spell_id for item in self.grades):
            raise ValueError("grade spell backreference does not match spell_id")
        grade_numbers = tuple(item.grade for item in self.grades)
        if grade_numbers != tuple(sorted(grade_numbers)):
            raise ValueError("spell mechanics grades must be ordered by grade")
        if len(set(grade_numbers)) != len(grade_numbers):
            raise ValueError("spell mechanics cannot contain duplicate grades")

    def grade(self, grade: int) -> SpellGradeMechanics | None:
        if isinstance(grade, bool) or not isinstance(grade, int):
            raise TypeError("grade must be an int")
        for item in self.grades:
            if item.grade == grade:
                return item
        return None
