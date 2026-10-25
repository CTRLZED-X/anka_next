from __future__ import annotations

import re

from anka_game_kernel.domain.ids import StateId
from anka_game_kernel.domain.state_criteria import (
    AllStateCriteria,
    AnyStateCriteria,
    StateAbsentCriterion,
    StateCriterion,
    StatePresentCriterion,
)

_ATOM_RE = re.compile(r"HS([=!])([1-9][0-9]*)\Z")


def parse_states_criterion(raw: str | None) -> StateCriterion | None:
    """Normalize the currently observed SpellLevels.statesCriterion grammar.

    Supported source forms are HS=<state_id>, HS!<state_id>, '&', '|', and
    parentheses. Empty/null source criteria mean no state restriction. Unknown
    or malformed syntax fails closed with ValueError.
    """
    if raw is None or raw == "" or raw == "null":
        return None
    if not isinstance(raw, str):
        raise TypeError("statesCriterion must be a string or None")
    if any(character.isspace() for character in raw):
        raise ValueError("statesCriterion whitespace is not part of the observed grammar")
    return _parse_expression(raw)


def _parse_expression(text: str) -> StateCriterion:
    if not text:
        raise ValueError("statesCriterion contains an empty expression")

    depth = 0
    top_level_operators: list[tuple[int, str]] = []
    matching_outer_close: int | None = None

    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("statesCriterion has an unmatched closing parenthesis")
            if depth == 0 and text.startswith("(") and matching_outer_close is None:
                matching_outer_close = index
        elif character in "&|" and depth == 0:
            top_level_operators.append((index, character))

    if depth != 0:
        raise ValueError("statesCriterion has an unmatched opening parenthesis")

    operator_kinds = {operator for _, operator in top_level_operators}
    if len(operator_kinds) > 1:
        raise ValueError(
            "statesCriterion mixes '&' and '|' at the same level; parentheses are required"
        )

    if top_level_operators:
        operator = top_level_operators[0][1]
        parts = _split_top_level(text, operator)
        if any(part == "" for part in parts):
            raise ValueError("statesCriterion contains an empty boolean operand")
        criteria = tuple(_parse_expression(part) for part in parts)
        if operator == "&":
            return AllStateCriteria(criteria)
        return AnyStateCriteria(criteria)

    if text.startswith("("):
        if matching_outer_close != len(text) - 1:
            raise ValueError("statesCriterion has adjacent or trailing parenthesized content")
        inner = text[1:-1]
        if not inner:
            raise ValueError("statesCriterion contains an empty parenthesized expression")
        return _parse_expression(inner)

    if "(" in text or ")" in text:
        raise ValueError("statesCriterion contains malformed parentheses")

    match = _ATOM_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"unsupported statesCriterion atom: {text!r}")

    operator, raw_state_id = match.groups()
    state_id = StateId(int(raw_state_id))
    if operator == "=":
        return StatePresentCriterion(state_id)
    return StateAbsentCriterion(state_id)


def _split_top_level(text: str, operator: str) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(text):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == operator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return tuple(parts)
