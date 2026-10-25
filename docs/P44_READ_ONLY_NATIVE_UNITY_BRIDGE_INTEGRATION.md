# P44 — Read-only Unity coordinate bridge source recovery and P43 client integration

**Milestone:** P44, 21 October 2026. **Authority:** RESEARCH_ONLY, no native compilation or installation, no physical input, no current-build certification. The R5.198 source archive and P43 baseline remain unchanged.

## What was implemented

1. Recovered the R5.198 `unity_bridge/` native source into `native/unity_bridge/`: 11 original C# source files plus the `.csproj` and two original readmes (14 files). Exact source hashes and historical per-file provenance attestations are stored in `provenance/P44_native_bridge_source.json`. The historical `BUILD_BRIDGE.bat` is deliberately **not shipped**: only `setup.bat` and `start.bat` are operator BAT commands.
2. Added immutable public research DTOs and a `BridgeEvidenceReader` port (`anka_contracts/bridge.py`). No permission, character ID or gameplay state is inferred from a window title, PID match, or coordinate table.
3. Added `anka_client/unity_bridge.py`: bounded **GET-only** localhost transport for `/health` and `/coordinates` (not `/observe`, `/resolve`, `/discover` or any POST), strict duplicate-JSON-field checks, exact process ID + Windows creation FILETIME + bridge-port matches, client dimensions, map/coordinate generations, stable camera/window/projection geometry signatures, and **560 unique source-verified cell entries**. It compares health before and after the coordinate read to reject stale or cross-generation observations. All returned coordinates are `RESEARCH_PROJECTION_ONLY`, never click targets authorized by Execution.
4. Added `anka_client/bridge_source.py`: verify the imported files against immutable per-file source hashes. Integrated the source audit into the normal app `check`/`setup`/`start` preflight with a bounded, privacy-neutral observation event. The bootstrap **does not** compile, install, connect to, or trust the bridge.
5. Added two P44 regression files covering process reuse, wrong bridge port, missing/stale map and generation, window resize/minimization, camera fingerprint drift, invalid coordinates, duplicate cell, incomplete 560-cell table, oversized/malformed loopback responses, hash tampering and path traversal.

## Why this approach

P43 had validated calibration references and Win32 read-only discovery, but the actual BepInEx/IL2CPP map/cell source was absent. The R5.198 native project is a valuable recovered asset; copying the old 1,897-line input driver or wiring physical execution now would bypass ANKA_NEXT's authority contracts. The bridge is an *observational port* controlled by Client; Execution does not import the bridge and the complete current-build/Win32 proof remains blocked.

**Two separate safety scopes:** A `BridgeIdentityReport(status=PROCESS_MATCHED)` establishes at most process-generation continuity for an already independently identified window. It cannot prove CRA vs ENU, selected character or spell loadout. A `BridgeMapReport(status=RESEARCH_PROJECTION_ONLY)` represents a coherent *snapshot* of map-cell-to-client-relative positions; it is not a current-millisecond target validation and cannot authorize a physical click. Recheck physical focus, current map, character, client generation and slot mapping in later milestones.

## Verification — independently executed on this P44 source

- `PYTHONPATH=src python -m pytest -q -p no:cacheprovider tests/test_p44_native_source_audit.py tests/test_p44_unity_bridge_readonly.py`: **20 tests + 42 subtests passed**.
- Client and cross-boundary selection including P44, geometry, discovery, P21 architecture, P35, P43: **109 tests + 42 subtests passed**.
- More extensive P18/P19/P20/P22/P23/P25/P33/P42/capture+P44 cross-system selection: **211 tests + 127 subtests passed**. Groups overlap; totals must not be added.
- App `check` exit 0, app `setup` exit 0, and app `start` **intentionally** exit 40 `LIVE_RUNTIME_NOT_IMPLEMENTED` with a generated incident ZIP. Source audit reports 14 historically matched files, **not compiled, not installed, not live certified**.
- Full 63-module isolated verifier was attempted, but outer execution timeout interrupted it: **7 modules with 135 tests recorded in a source-bound checkpoint**, not a full pass. The previous P43 61-module/1,138-test full receipt is historic evidence, not rerun for P44.
- Architecture and reference asset checks are run by `check/setup`; `setup` has no gameplay control authority.

## Known limitations and next action

- No Windows/Npcap/Unity instance exists in this Linux test environment; no `.dll` was built, installed or executed. The original `.csproj` requires specific BepInEx and Unity IL2CPP interop assemblies and may need adaptation for the current client.
- There is no current-build authoritative character↔window↔network-flow↔bridge-port proof, no live calibration, no full fight snapshots, and no live spell slots, physical dispatch or server settlement. A verified old native SHA means *identical source*, not current-client compatibility.
- The bridge's local HTTP listener and its native runtime behavior require additional Windows security and operational verification before any unattended use (including binding authentication and multi-account port ownership). The Python port deliberately only uses `127.0.0.1`, bounded JSON and GET routes.
- **P45** should extract historical protocol decoding behind an offline, exact-build, non-authoritative adapter with a golden corpus and consumer contracts. Keep original research admission and Kernel unchanged; do not authorize current-client gameplay from historical compatibility.

**Development estimate:** 89% subjective weighted roadmap coverage (88% P43 baseline; +1 only for recovering and integrating a substantive missing Client subsystem). **Complete live CRA/ENU fight acceptance:** 0%.
