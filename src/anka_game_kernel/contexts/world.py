from __future__ import annotations

from dataclasses import dataclass

from anka_game_kernel.domain.ids import ActorId, CellId, MapId


@dataclass(frozen=True, slots=True)
class WorldMonsterGroup:
    group_id: int
    cell_id: CellId | None = None
    member_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.group_id, bool) or not isinstance(self.group_id, int):
            raise TypeError("group_id must be an int")
        if self.cell_id is not None and not isinstance(self.cell_id, CellId):
            raise TypeError("cell_id must be a CellId or None")


@dataclass(frozen=True, slots=True)
class WorldContext:
    map_id: MapId | None = None
    player_actor_id: ActorId | None = None
    player_cell_id: CellId | None = None
    monster_groups: tuple[WorldMonsterGroup, ...] = ()
    monster_groups_complete: bool = False

    def __post_init__(self) -> None:
        if self.map_id is not None and not isinstance(self.map_id, MapId):
            raise TypeError("map_id must be a MapId or None")
        if self.player_actor_id is not None and not isinstance(self.player_actor_id, ActorId):
            raise TypeError("player_actor_id must be an ActorId or None")
        if self.player_cell_id is not None and not isinstance(self.player_cell_id, CellId):
            raise TypeError("player_cell_id must be a CellId or None")
        if any(not isinstance(item, WorldMonsterGroup) for item in self.monster_groups):
            raise TypeError("monster_groups must contain WorldMonsterGroup values")
