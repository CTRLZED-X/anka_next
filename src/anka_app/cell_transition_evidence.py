"""Pure research-only assessment of observed cell *transitions*.

A position snapshot is not a movement event. Without a pre-action position
anchor, a new post-action position cannot prove no intervening displacement.
This utility never imports runtime/driver or grants state/action authority.
"""
from __future__ import annotations
from typing import Sequence

from anka_contracts.fight_semantic import FightResearchDraft


def observed_cell_change(
    drafts: Sequence,
    *,
    actor_id: int,
    before_index: int,
    cast_index: int,
    after_index: int,
) -> str:
    """Return NONE, PRE_ONLY, SAME_CELL, DISPLACEMENT, or UNANCHORED_POST_OBSERVATION.

    Scopes the search to the explicit verified comparison window. The latest
    pre-cast cell anchors post-cast observations. Distinct pre-cast cells also
    matter (movement might independently explain an MP delta). Source order
    and turn validity must be checked by the caller's full-trace validator.
    """
    pre = [d.cell_id for d in drafts[before_index:cast_index]
           if isinstance(d, FightResearchDraft) and
           d.kind == 'ACTOR_CELL_OBSERVED' and d.actor_id == actor_id]
    post = [d.cell_id for d in drafts[cast_index+1:after_index]
            if isinstance(d, FightResearchDraft) and
            d.kind == 'ACTOR_CELL_OBSERVED' and d.actor_id == actor_id]
    if not pre and not post:
        return 'NONE'
    if pre and not post:
        # Earlier MP baselines need not describe the actor's position. A
        # solitary pre-cast location may be a move or a repeated snapshot.
        return 'PRE_ONLY'
    if not pre:
        # A post-cast refresh might be the first observed *new* location.
        return 'UNANCHORED_POST_OBSERVATION'
    cells = pre + post
    return 'DISPLACEMENT' if any(a != b for a, b in zip(cells, cells[1:])) else 'SAME_CELL'
