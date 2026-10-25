# System 05 — Game Kernel (`anka_game_kernel`)

## Purpose

The Game Kernel is ANKA's pure deterministic mechanics engine. The R5.198 package is the strongest existing reusable component and SHOULD be ported with minimal semantic change.

## Owned mechanics

- map/cell geometry and distance;
- walkability/static geometry data;
- line of sight;
- range/min/max/modifiable-range rules;
- linear/diagonal restrictions;
- AoE shapes;
- movement/path/collision mechanics already supported;
- push/pull/displacement mechanics already supported;
- spell/action costs;
- cooldown/readiness constraints;
- per-turn/per-target constraints;
- target types and effects supported by current knowledge packs;
- deterministic effect/cast legality queries.

## Must NOT own

- raw packets/protocol builds;
- live observed HP/AP/MP authority;
- Windows coordinates/focus;
- mission progress;
- tactical candidate scoring;
- physical execution;
- assumptions for unsupported mechanics.

## Reuse rules

1. Copy the complete existing package with file/hash provenance.
2. Keep old fixtures/regressions.
3. Separate game-data/ruleset revision from protocol adapter revision.
4. Add a narrow `KernelQueries` facade/adapter for host systems without changing internals unnecessarily.
5. Unsupported rules stay `INDETERMINATE/UNSUPPORTED`; do not guess to improve liveness.

## Data compatibility

The supplied compatibility file only proves a scoped subset. Each release must document required route/maps/spells/classes and whether their data/rules are certified.

## Tests

Preserve existing rule tests plus explicit CRA/ENU required loadouts, range/LoS/AoE, movement, spell readiness, non-walkable cells, linear/diagonal cases, data-missing behavior, and deterministic result hashes.

Kernel tests are pure: no network, Windows or capture dependencies.

