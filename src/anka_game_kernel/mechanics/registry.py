from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from anka_game_kernel.domain.mechanics import MechanicKey
from anka_game_kernel.errors import UnsupportedMechanicError


@dataclass(frozen=True, slots=True)
class MechanicRegistry:
    _items: Mapping[MechanicKey, object]

    def __post_init__(self) -> None:
        if any(not isinstance(key, MechanicKey) for key in self._items):
            raise TypeError("MechanicRegistry keys must be MechanicKey values")
        object.__setattr__(self, "_items", MappingProxyType(dict(self._items)))

    @property
    def supported_keys(self) -> frozenset[MechanicKey]:
        return frozenset(self._items)

    def get(self, key: MechanicKey) -> object | None:
        if not isinstance(key, MechanicKey):
            raise TypeError("mechanic lookup requires a MechanicKey")
        return self._items.get(key)

    def require(self, key: MechanicKey) -> object:
        mechanic = self.get(key)
        if mechanic is None:
            raise UnsupportedMechanicError(
                f"semantic mechanic {key.value} is not implemented in this Kernel build"
            )
        return mechanic
