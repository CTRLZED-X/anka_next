# P14 — Bounded offline tactical candidate research

**Scope:** Synthetic-only kernel-backed movement-plus-cast evaluation and AP/MP cost accounting. This milestone deliberately creates *no* execution plan, physical input API, FightAI controller or live-game permission.

## What was extracted from the preserved kernel

P14 composes existing P12/P13 scope and map gates with the unchanged kernel's:

- `fight_queries.reachable_cells` and `fight_queries.shortest_path` for actual movement feasibility and MP cost;
- `FightProjectionService.move_actor`, `spend_mp`, and `spend_ap` for immutable hypothetical branches;
- `spell_decisions.evaluate_cast_cell` for cast availability, range, LoS, target and occupied-cell validity;
- `spell_mechanics_overlay.require_grade` for independent, verified *historical* AP cost lookup.

No distance, LoS, spell-range or cast-restriction engine was reimplemented. The planner is deliberately bounded to **12 movement cells × 12 cast targets**, preserving deterministic order and recording reasons for every rejected or unknown pair. The list is sorted by kernel feasibility and movement cost, **not** by tactical damage or victory probability.

## Input/output contracts

- `anka_contracts.tactical_research.TacticalResearchRequest`: exact `CastProbe` account/fight/generation/revision identity, static map id, bounded movement/target cell sets, up to four spell IDs/grades for AP-only costing. Each spell sequence must start with the candidate cast.
- `anka_decision.tactical_research.inspect_tactical_research`: consumes explicitly supplied synthetic snapshot, immutable `MapDefinition`, `FightContext` and caller-owned kernel. It never mutates caller state or creates live input.
- `TacticalResearchReport` and `TacticalCandidate`: frozen typed reports; serialization hardcodes `authoritative=false`, `actionable=false`, `physical_input_permitted=false`.
- `anka_app.tactical_offline`: independent synthetic demo composition; `tactical_demo.bat` invokes the read-only CLI.

## Evidence admission and rejection

P14 first applies the P12/P13 evidence and map gates. Invalid scope, incomplete 560-cell map, incorrect account/fight/revision, actor-state conflict, missing cooldown completeness, uncertain occupancy, stale geometry overrides or static-data mismatches abort **before** hypothetical evaluation.

For every reachable destination, the kernel computes a path and projects the moved actor and remaining MP into an immutable context. Spell availability is **recalculated from that hypothetical cell**, not reused from the original location. Casting projects AP bookkeeping only if the kernel cost fits. Illegal targets and unreachable destinations receive explicit codes, with no fallback cast.

AP sums for *multiple* spells are `WITHIN_AP_BUDGET_COST_ONLY` or `OVER_AP_BUDGET`. They **do not establish sequence legality**, because per-target/per-turn counters, cooldown transitions, spell effects, damage, movement triggers and server confirmation after the first cast are not fully projected. Movement also carries explicit server-outcome, tackle and reactive-effects uncertainties; known per-MP reactive modifiers downgrade hypothetical legality to UNKNOWN. No synthetic preview can flow to Execution.

## Failure-mode regression gates

P14 includes tests for actual kernel cast/shortest-path results, LoS/range rejection, immutability, reproducible tie breaking, budget boundaries, occupied targets, unreachable destinations, invalid/oversized candidate sets, unsupported spells, stale scope/revision, missing history, reactive movement modifiers, injected kernel failures, no input authority, and demo CLI.

Do not treat this as a certified CRA/ENU tactical strategy. Future Decision milestones must use current-build semantic evidence, verified movement constraints, equipment-to-spell-slot mapping, full cast history, damage/effect outcomes, healing, retreat, target selection, and mission strategy, all behind new evidence gates. Windows acceptance, on-host protocol qualification and real fight verification remain open.

## Running offline

```bat
tactical_demo.bat
verify.bat
```

`start.bat` remains deliberately blocked with `LIVE_RUNTIME_NOT_IMPLEMENTED`. The old R5.198 source is unchanged.
