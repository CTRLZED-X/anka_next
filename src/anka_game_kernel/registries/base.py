from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Generic, Iterable, Iterator, Mapping, TypeVar

from anka_game_kernel.errors import DefinitionNotFoundError, DuplicateDefinitionError

K = TypeVar("K")
V = TypeVar("V")


@dataclass(frozen=True, slots=True)
class DefinitionRegistry(Generic[K, V]):
    _items: Mapping[K, V]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_items", MappingProxyType(dict(self._items)))

    @classmethod
    def from_items(
        cls,
        items: Iterable[V],
        *,
        key: Callable[[V], K],
    ) -> "DefinitionRegistry[K, V]":
        indexed: dict[K, V] = {}
        for item in items:
            identifier = key(item)
            if identifier in indexed:
                raise DuplicateDefinitionError(
                    f"duplicate canonical definition id {identifier}"
                )
            indexed[identifier] = item
        return cls(indexed)

    def get(self, identifier: K) -> V | None:
        return self._items.get(identifier)

    def require(self, identifier: K) -> V:
        item = self.get(identifier)
        if item is None:
            raise DefinitionNotFoundError(
                f"canonical definition {identifier} was not found"
            )
        return item

    def keys(self):
        return self._items.keys()

    def values(self):
        return self._items.values()

    def items(self):
        return self._items.items()

    def __contains__(self, identifier: object) -> bool:
        return identifier in self._items

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[V]:
        return iter(self._items.values())
