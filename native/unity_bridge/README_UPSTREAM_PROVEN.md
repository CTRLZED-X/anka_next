# Dofus Unity Coordinate Bridge — authoritative cell map

The BepInEx IL2CPP plugin listens on `127.0.0.1:8765`.

## Authoritative runtime source

The bridge compiles only against stable BepInEx/Unity generated interop assemblies. It does **not** compile against any Dofus-specific assembly name or against obfuscated `CustomGridGenerator` member names. `CustomGridGenerator` is resolved by its runtime full type name across loaded IL2CPP interop assemblies, so Dofus assembly splits/merges do not block the build.

At runtime it:

1. discovers live `CustomGridGenerator` instances through Unity resources and
   reflected static accessors;
2. enumerates instance methods whose semantic signature is
   `UnityEngine.Vector3 method(System.Int32)`;
3. probes all 560 cell IDs and rejects candidates that do not provide at least
   500 finite and 500 distinct positions;
4. caches the selected delegate or `MethodInfo` invoker; and
5. requires at least two real actor placements with correct nearest-cell
   associations before marking the source verified.

The direct Dofus result and component-transformed result are both tested. The
mode with the lowest actor-placement error is selected. No guessed grid
constants or actor-relative coordinate reconstruction are used.

Optional map metadata is not required, so a renamed metadata member cannot stop
the bridge from compiling.

The complete static walkable-cell table is generated before readiness. `/resolve`
only reads that cache.

## Diagnostics

`/automation`, `/health`, `/discover`, and evidence JSON now expose:

- all reflected static grid accessors;
- every candidate `Vector3(Int32)` method signature;
- invocation mode (`CACHED_DELEGATE` or `CACHED_METHODINFO_INVOKE`);
- valid and distinct position counts;
- invocation failures and rejection reasons;
- the selected method signature; and
- actor-cell validation samples.

If no trustworthy converter exists, the bridge stays fail-closed with
`CELL_POSITION_SOURCE_UNVERIFIED` instead of guessing coordinates.

## API

```text
GET  /health
GET  /automation
GET  /coordinates
POST /observe
POST /resolve
POST /discover
```

Expected progression:

```text
WAITING_FOR_DECODER
DISCOVERING_CELL_POSITION_SOURCE
CELL_POSITION_SOURCE_UNVERIFIED
GENERATING_MAP_COORDINATES
MAP_COORDINATES_READY
```

Evidence is written under:

```text
BepInEx\config\DofusCoordinateBridge\evidence\*.json
BepInEx\config\DofusCoordinateBridge\DofusCoordinateBridge.discovery.<PID>.json
```

The bridge serializes explicitly selected primitive values only. It never
recursively walks Unity properties.

## Build

Close Dofus, then run `BUILD_BRIDGE.bat`. Required compile-time references are limited to stable BepInEx/Unity interop assemblies. Dofus-specific files such as `Core.dll` and `Ankama.Dofus.Core.World.dll` are optional runtime inventory evidence, **not build prerequisites**.

Original Dofus assemblies are never copied into the release ZIP.
