"""Kernel-native read-only fight decision queries."""

from anka_game_kernel.mechanics.fight_queries.service import FightQueryService
from anka_game_kernel.results.fight_queries import NearestActorResult

__all__ = ["FightQueryService", "NearestActorResult"]
