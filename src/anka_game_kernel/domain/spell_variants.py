from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import SpellId, SpellVariantId
from anka_game_kernel.domain.provenance import Provenance


@dataclass(frozen=True, slots=True)
class SpellVariantDefinition:
    variant_id: SpellVariantId
    spell_ids: tuple[SpellId, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if len(self.spell_ids) < 2:
            raise ValueError("spell variant group must contain at least two spells")
        if len(set(self.spell_ids)) != len(self.spell_ids):
            raise ValueError("spell variant group cannot contain duplicate spell ids")
