# ANKA R5 Unity Coordinate Bridge

This directory packages the proven BepInEx IL2CPP coordinate bridge used by the earlier certified DofusAuto runtime, now as a narrow projection-edge dependency of ANKA R5.

It is **not** the old classifier service. ANKA does not start port 8011 and does not restore the old classifier database/API. The only runtime API is the in-process Dofus plugin on `127.0.0.1:8765`:

```text
GET  /health
GET  /automation
GET  /coordinates
POST /observe
POST /resolve
POST /discover
```

ANKA's `ProjectionObservationSynchronizer` posts confirmed canonical map/fight/actor facts plus Kernel Mapuse floor/walkability to `/observe`. `ProjectionService` then resolves cells through `/resolve` and still fails closed on map/request/generation/source/viewport mismatches.

## Install

1. Run `setup.bat` once for the Python platform.
2. Close Dofus completely.
3. Run the root `install_bridge.bat`.
4. Start Dofus once and keep it open.
5. Run `start.bat`; ANKA will automatically begin canonical → bridge observation synchronization.

If BepInEx is outside the standard Ankama folders, define `BEPINEX_PATH` before running the installer.

## Build requirements

- A .NET SDK (`dotnet --list-sdks` must return at least one SDK).
- BepInEx IL2CPP already installed for the active Dofus client.
- Current BepInEx `core` assemblies plus the generated Unity interop assemblies (`Il2Cppmscorlib`, `UnityEngine`, `UnityEngine.CoreModule`).
- **No Dofus-specific interop DLL name is required at compile time.** `Core.dll`, `Ankama.Dofus.Core.World.dll`, and future split/merged game assemblies are runtime-discovered rather than hardcoded build dependencies.

The release ZIP intentionally contains **no** BepInEx, Unity, or Dofus DLLs. `BUILD_BRIDGE.bat` references only stable BepInEx/Unity assemblies from your local installation. Dofus runtime types are discovered by fully-qualified type name after the plugin loads. The installer writes `runtime/bridge_environment.json` before build/install so a failure records the exact local interop inventory, then installs only `DofusCoordinateBridge.dll` under `BepInEx\plugins\DofusCoordinateBridge`.

The historical bridge technical notes are retained in `README_UPSTREAM_PROVEN.md`.
