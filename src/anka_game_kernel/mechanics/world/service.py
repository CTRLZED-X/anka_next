from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum

from anka_game_kernel.domain.ids import MapId
from anka_game_kernel.domain.maps import MapDefinition
from anka_game_kernel.registries.base import DefinitionRegistry


class WorldDirection(str, Enum):
    TOP = "TOP"
    RIGHT = "RIGHT"
    BOTTOM = "BOTTOM"
    LEFT = "LEFT"


@dataclass(frozen=True, slots=True)
class WorldTransition:
    source_map_id: MapId
    target_map_id: MapId
    direction: WorldDirection
    available_in_mapuse: bool


@dataclass(frozen=True, slots=True)
class WorldRoute:
    reachable: bool
    map_ids: tuple[MapId, ...] = ()
    steps: tuple[WorldTransition, ...] = ()
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class WorldService:
    maps: DefinitionRegistry[MapId, MapDefinition]

    def transitions(self, map_id: MapId) -> tuple[WorldTransition, ...]:
        definition = self.maps.require(map_id)
        pairs = (
            (WorldDirection.TOP, definition.neighbors.top),
            (WorldDirection.RIGHT, definition.neighbors.right),
            (WorldDirection.BOTTOM, definition.neighbors.bottom),
            (WorldDirection.LEFT, definition.neighbors.left),
        )
        return tuple(
            WorldTransition(
                source_map_id=map_id,
                target_map_id=target,
                direction=direction,
                available_in_mapuse=target in self.maps,
            )
            for direction, target in pairs
            if target is not None
        )

    def route(self, source_map_id: MapId, target_map_id: MapId) -> WorldRoute:
        if source_map_id not in self.maps:
            return WorldRoute(False, reason="SOURCE_NOT_IN_MAPUSE")
        if target_map_id not in self.maps:
            return WorldRoute(False, reason="TARGET_NOT_IN_MAPUSE")
        if source_map_id == target_map_id:
            return WorldRoute(True, map_ids=(source_map_id,), steps=())

        queue = deque([source_map_id])
        parent: dict[MapId, tuple[MapId, WorldTransition] | None] = {source_map_id: None}
        while queue:
            current = queue.popleft()
            for transition in self.transitions(current):
                if not transition.available_in_mapuse:
                    continue
                nxt = transition.target_map_id
                if nxt in parent:
                    continue
                parent[nxt] = (current, transition)
                if nxt == target_map_id:
                    queue.clear()
                    break
                queue.append(nxt)

        if target_map_id not in parent:
            return WorldRoute(False, reason="NO_MAPUSE_ROUTE")

        reverse_maps = [target_map_id]
        reverse_steps: list[WorldTransition] = []
        cursor = target_map_id
        while cursor != source_map_id:
            record = parent[cursor]
            assert record is not None
            previous, transition = record
            reverse_steps.append(transition)
            reverse_maps.append(previous)
            cursor = previous
        return WorldRoute(
            True,
            map_ids=tuple(reversed(reverse_maps)),
            steps=tuple(reversed(reverse_steps)),
        )
