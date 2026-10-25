from __future__ import annotations

from enum import StrEnum


class ActorKind(StrEnum):
    UNKNOWN = "unknown"
    PLAYER = "player"
    MONSTER = "monster"
    COMPANION = "companion"
    OTHER = "other"


class SummonKind(StrEnum):
    NORMAL = "normal"
    STATIC = "static"
    MONSTER = "monster"
    OTHER = "other"
    UNKNOWN = "unknown"
