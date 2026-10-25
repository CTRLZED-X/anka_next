# M2 — Preserved Game Kernel & Scoped Game Data

## Decision

The R5.198 Game Kernel is preserved as knowledge, not rewritten. Every legacy Kernel file is hash-mapped in `reference/m2/kernel_reuse_provenance.json`; every migrated external game-data file is mapped in `reference/m2/game_data_provenance.json`.

The Kernel remains independently reusable: it imports neither `anka_contracts` nor any other ANKA_NEXT system. Composition-specific translation lives in `anka_app.adapters.kernel_queries.GameKernelQueriesAdapter`.

## Scope

`reference/m2/KERNEL_SCOPE.json` is authoritative for the M2 offline mechanics scope. The bundled static/Mapuse data is historical `3.6.10.10`, while the verified spell-mechanics pack currently contains 47 scoped CRA/ENU mechanics entries. This is **not** current-client certification.

The adapter intentionally distinguishes static proof from live action legality. Static data may prove a cell impossible. A statically walkable cell does not prove a live move is legal because occupancy/path/epoch truth may be missing. Likewise, structurally supported spell mechanics do not prove a live cast is currently legal.

## Legacy regression oracle

The immutable R5.198 archive contains 105 eligible top-level pure Kernel test files / 868 test functions identified in `reference/m2/legacy_kernel_oracle_manifest.json`. Q3 actively replays a fast 206-test subset against the current preserved Kernel covering geometry, range, LoS, AoE, movement, cast availability, spell readiness, targeting, displacement, collision and relocation. The full legacy fixture inventory remains hash-addressable for targeted later regressions.

## Unsupported / incomplete behavior

Unsupported mechanics, missing map/cell/spell data and incomplete runtime context remain explicit and fail closed. The Kernel does not own protocol truth, observed combat resources, fight freshness, Windows coordinates, Decision scoring, Workflow progress or physical input.

## Cutover / rollback

M2 does not replace a mutable live authority. The Game Kernel remains byte-preserved. Any future semantic Kernel edit must cease claiming unchanged reuse, document an ADR, add an independent oracle, and regenerate Q3.
