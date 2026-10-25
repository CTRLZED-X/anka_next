from __future__ import annotations

from dataclasses import dataclass, replace

from anka_game_kernel.domain.effects import EffectDefinition
from anka_game_kernel.domain.actors import ActorState
from anka_game_kernel.domain.ids import EffectId, SpellId, StateId
from anka_game_kernel.domain.spell_effects import (
    ApplyStateEffectSpec,
    RemoveStateEffectSpec,
    SpellGradeMechanics,
    SpellMechanicsDefinition,
)
from anka_game_kernel.domain.spells import SpellDefinition, SpellGradeDefinition
from anka_game_kernel.domain.spell_modifiers import SpellRangeBound
from anka_game_kernel.domain.states import StateDefinition
from anka_game_kernel.errors import DefinitionNotFoundError
from anka_game_kernel.knowledge.spell_mechanics import SpellMechanicsPack
from anka_game_kernel.registries.base import DefinitionRegistry


@dataclass(frozen=True, slots=True)
class ResolvedSpellGradeView:
    static_grade: SpellGradeDefinition
    mechanics: SpellGradeMechanics | None
    definition: SpellMechanicsDefinition | None = None

    @property
    def effective_grade(self) -> SpellGradeDefinition:
        override = None if self.mechanics is None else self.mechanics.cast_rule_override
        if override is None:
            return self.static_grade
        changes: dict[str, object] = {}
        if override.cast_in_diagonal is not None:
            changes["cast_in_diagonal"] = override.cast_in_diagonal
        if override.max_global_cast_per_turn is not None:
            changes["max_global_cast_per_turn"] = override.max_global_cast_per_turn
        return self.static_grade if not changes else replace(self.static_grade, **changes)


@dataclass(frozen=True, slots=True)
class SpellMechanicsOverlay:
    spells: DefinitionRegistry[SpellId, SpellDefinition]
    mechanics_pack: SpellMechanicsPack | None
    effects: DefinitionRegistry[EffectId, EffectDefinition] | None = None
    states: DefinitionRegistry[StateId, StateDefinition] | None = None
    game_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.spells, DefinitionRegistry):
            raise TypeError("spells must be a DefinitionRegistry")
        if self.mechanics_pack is None:
            return
        if not isinstance(self.mechanics_pack, SpellMechanicsPack):
            raise TypeError("mechanics_pack must be SpellMechanicsPack or None")
        pack_game_version = self.mechanics_pack.manifest.game_version
        if (
            self.game_version is not None
            and pack_game_version is not None
            and self.game_version != pack_game_version
        ):
            raise ValueError(
                "spell mechanics game version does not match Knowledge Pack game version"
            )
        self._validate_pack()

    @staticmethod
    def _grade(spell: SpellDefinition, grade_number: int) -> SpellGradeDefinition | None:
        for grade in spell.grades:
            if grade.grade == grade_number:
                return grade
        return None

    def _validate_pack(self) -> None:
        assert self.mechanics_pack is not None
        for mechanics_definition in self.mechanics_pack.spells:
            spell = self.spells.get(mechanics_definition.spell_id)
            if spell is None:
                raise DefinitionNotFoundError(
                    f"spell mechanics references unknown spell {mechanics_definition.spell_id}"
                )
            for grade_mechanics in mechanics_definition.grades:
                if self._grade(spell, grade_mechanics.grade) is None:
                    raise DefinitionNotFoundError(
                        f"spell mechanics references unknown grade {grade_mechanics.grade} "
                        f"for spell {spell.spell_id}"
                    )
                for effects in (
                    grade_mechanics.normal_effects,
                    grade_mechanics.critical_effects,
                ):
                    if effects is None:
                        continue
                    for occurrence in effects:
                        if occurrence.effect_id is not None and self.effects is not None:
                            if occurrence.effect_id not in self.effects:
                                raise DefinitionNotFoundError(
                                    f"spell effect occurrence references unknown effect "
                                    f"{occurrence.effect_id}"
                                )
                        if self.states is not None and isinstance(
                            occurrence.parameters,
                            (ApplyStateEffectSpec, RemoveStateEffectSpec),
                        ):
                            if occurrence.parameters.state_id not in self.states:
                                raise DefinitionNotFoundError(
                                    f"spell effect occurrence references unknown state "
                                    f"{occurrence.parameters.state_id}"
                                )

    def get_grade(self, spell_id: SpellId, grade: int) -> ResolvedSpellGradeView | None:
        if not isinstance(spell_id, SpellId):
            raise TypeError("spell_id must be a SpellId")
        if isinstance(grade, bool) or not isinstance(grade, int):
            raise TypeError("grade must be an int")
        spell = self.spells.get(spell_id)
        if spell is None:
            return None
        static_grade = self._grade(spell, grade)
        if static_grade is None:
            return None
        mechanics = None
        mechanics_definition = None
        if self.mechanics_pack is not None:
            mechanics_definition = self.mechanics_pack.spells.get(spell_id)
            if mechanics_definition is not None:
                mechanics = mechanics_definition.grade(grade)
        return ResolvedSpellGradeView(
            static_grade=static_grade,
            mechanics=mechanics,
            definition=mechanics_definition,
        )

    def resolve_projected_grade(
        self,
        view: ResolvedSpellGradeView,
        actor: ActorState,
    ) -> tuple[SpellGradeDefinition | None, tuple[str, ...]]:
        """Apply caller-owned hypothetical spell-range modifiers to one resolved grade.

        Static data and verified cast-rule overrides remain immutable. Selector metadata is
        evaluated only from verified spell-mechanics definitions; missing metadata fails closed.
        """
        if not isinstance(view, ResolvedSpellGradeView):
            raise TypeError("view must be a ResolvedSpellGradeView")
        if not isinstance(actor, ActorState):
            raise TypeError("actor must be an ActorState")
        base = view.effective_grade
        if base.spell_id in actor.spell_range_unknown_spell_ids:
            return None, (f"spell:{int(base.spell_id)}:live_range_modifier",)
        if not actor.spell_range_modifiers:
            return base, ()

        minimum_delta = 0
        maximum_delta = 0
        missing: list[str] = []
        for modifier in actor.spell_range_modifiers:
            definition = view.definition
            if modifier.affected_spell_ids and base.spell_id not in modifier.affected_spell_ids:
                continue
            if modifier.affected_class_id is not None:
                if definition is None or definition.class_id is None:
                    key = f"spell:{int(base.spell_id)}:class_id"
                    if key not in missing:
                        missing.append(key)
                    continue
                if definition.class_id != modifier.affected_class_id:
                    continue
            if modifier.required_tags:
                if definition is None:
                    key = f"spell:{int(base.spell_id)}:semantic_tags"
                    if key not in missing:
                        missing.append(key)
                    continue
                if not modifier.required_tags.issubset(definition.tags):
                    continue
            if modifier.bound is SpellRangeBound.MINIMUM:
                minimum_delta += modifier.amount
            else:
                maximum_delta += modifier.amount

        if missing:
            return None, tuple(missing)
        minimum = base.min_range + minimum_delta
        maximum = base.max_range + maximum_delta
        if minimum < 0 or maximum < minimum:
            raise ValueError(
                "projected spell-range modifiers produced an invalid intrinsic range; "
                "that combination is not verified"
            )
        return replace(base, min_range=minimum, max_range=maximum), ()

    def require_grade(self, spell_id: SpellId, grade: int) -> ResolvedSpellGradeView:
        view = self.get_grade(spell_id, grade)
        if view is None:
            spell = self.spells.get(spell_id)
            if spell is None:
                raise DefinitionNotFoundError(f"canonical spell {spell_id} was not found")
            raise DefinitionNotFoundError(
                f"canonical grade {grade} for spell {spell_id} was not found"
            )
        return view
