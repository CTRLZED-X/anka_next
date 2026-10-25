"""Canonical immutable domain types."""

from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.domain.spell_effects import (
    ApplyStateEffectSpec,
    DamageEffectSpec,
    HealEffectSpec,
    PullEffectSpec,
    RecoilEffectSpec,
    PushEffectSpec,
    RemoveStateEffectSpec,
    ShieldEffectSpec,
    SpellEffectBranch,
    SpellEffectOccurrence,
    SpellCastRuleOverride,
    SpellGradeMechanics,
    SpellMechanicsDefinition,
    SwapEffectSpec,
    TeleportEffectSpec,
)
from anka_game_kernel.domain.values import AmountSpec, ProbabilitySpec, ValueReference, ValueUnit

__all__ = [
    "AmountSpec",
    "ApplyStateEffectSpec",
    "DamageEffectSpec",
    "HealEffectSpec",
    "MechanicKey",
    "ProbabilitySpec",
    "PullEffectSpec",
    "RecoilEffectSpec",
    "PushEffectSpec",
    "RemoveStateEffectSpec",
    "ShieldEffectSpec",
    "SpellEffectBranch",
    "SpellEffectOccurrence",
    "SpellCastRuleOverride",
    "SpellGradeMechanics",
    "SpellMechanicsDefinition",
    "SwapEffectSpec",
    "TeleportEffectSpec",
    "ValueReference",
    "ValueUnit",
]
