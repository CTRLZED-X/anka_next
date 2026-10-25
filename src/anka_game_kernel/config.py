from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from anka_game_kernel.errors import ExternalGameDataError


REQUIRED_STATIC_FILES = frozenset(
    {
        "Areas.json",
        "Breeds.json",
        "CompanionSpells.json",
        "Companions.json",
        "Effects.json",
        "MapPositions.json",
        "MonsterRaces.json",
        "MonsterSuperRaces.json",
        "Monsters.json",
        "SpellLevels.json",
        "SpellStates.json",
        "SpellVariants.json",
        "Spells.json",
        "SubAreas.json",
        "SuperAreas.json",
    }
)


@dataclass(frozen=True, slots=True)
class ExternalGameDataConfig:
    """Filesystem configuration for caller-owned Static and Mapuse data.

    The Kernel intentionally has no machine-specific filesystem defaults. A caller
    must inject paths directly or provide them through the documented environment
    variables.
    """

    static_directory: Path
    mapuse_directory: Path
    static_source_version: str = "external-static"
    mapuse_source_version: str = "external-mapuse"
    pack_version: str = "external-game-data-v1"
    game_version: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "static_directory", Path(self.static_directory))
        object.__setattr__(self, "mapuse_directory", Path(self.mapuse_directory))
        if not self.static_source_version.strip():
            raise ValueError("static_source_version must not be empty")
        if not self.mapuse_source_version.strip():
            raise ValueError("mapuse_source_version must not be empty")
        if not self.pack_version.strip():
            raise ValueError("pack_version must not be empty")

    @classmethod
    def from_environment(cls) -> "ExternalGameDataConfig":
        static = os.environ.get("ANKA_KERNEL_STATIC_DIR")
        mapuse = os.environ.get("ANKA_KERNEL_MAPUSE_DIR")
        if not static:
            raise ExternalGameDataError(
                "ANKA_KERNEL_STATIC_DIR is required when Kernel configuration is loaded from environment"
            )
        if not mapuse:
            raise ExternalGameDataError(
                "ANKA_KERNEL_MAPUSE_DIR is required when Kernel configuration is loaded from environment"
            )
        return cls(
            static_directory=Path(static),
            mapuse_directory=Path(mapuse),
            static_source_version=os.environ.get(
                "ANKA_KERNEL_STATIC_SOURCE_VERSION", "external-static"
            ),
            mapuse_source_version=os.environ.get(
                "ANKA_KERNEL_MAPUSE_SOURCE_VERSION", "external-mapuse"
            ),
            pack_version=os.environ.get("ANKA_KERNEL_PACK_VERSION", "external-game-data-v1"),
            game_version=os.environ.get("ANKA_KERNEL_GAME_VERSION"),
        )

    def validate(self) -> "ExternalGameDataConfig":
        if not self.static_directory.exists():
            raise ExternalGameDataError(
                f"Static directory does not exist: {self.static_directory}"
            )
        if not self.static_directory.is_dir():
            raise ExternalGameDataError(
                f"Static path is not a directory: {self.static_directory}"
            )
        if not self.mapuse_directory.exists():
            raise ExternalGameDataError(
                f"Mapuse directory does not exist: {self.mapuse_directory}"
            )
        if not self.mapuse_directory.is_dir():
            raise ExternalGameDataError(
                f"Mapuse path is not a directory: {self.mapuse_directory}"
            )

        missing = tuple(
            sorted(
                name
                for name in REQUIRED_STATIC_FILES
                if not (self.static_directory / name).is_file()
            )
        )
        if missing:
            raise ExternalGameDataError(
                "Static directory is missing required files: " + ", ".join(missing)
            )

        if not any(path.is_file() for path in self.mapuse_directory.glob("map_*.json")):
            raise ExternalGameDataError(
                "Mapuse directory contains no map_*.json files: "
                f"{self.mapuse_directory}"
            )
        return self
