# P46 — Historical Combat Observations and Cross-Family Causal Audit

**Release:** 21 October 2026. **Baseline:** complete ANKA_NEXT P45. **Scope:** OFFLINE HISTORICAL RESEARCH ONLY; absolutely no current-client adapter certification, production Canonical admission, live input, spell effect confirmation, or victory accounting.

## 1. High-value source reuse, not old-controller copying

P45 preserved the old version-scoped R5.198 source `actions.source.txt` and `lifecycle.source.txt`, backed by P45's immutable 7-file handler inventory and SHA-256 guard. P46 extracts only the high-confidence **historical field positions** for these four observations into a pure, version-pinned research decoder. It **does not import or execute** the old high-coupling R5.198 adapter.

| Historical source | Fields used | P46 interpretation | What remains unproven |
|---|---|---|---|
| Server `jsq` action `300` | `22=300`, `36=signed caster`, `2.2.1=SpellLevel record`, `2.2.2=spell ID`, `2.5=target cell` | `CAST_WIRE_OBSERVED`: an observed server **cast record** | Actual spell acceptance/effect, damage, AP/MP cost, cooldown, target entity or cast success |
| Server `jsq` action `5` | `22=5`, `5.1=signed target`, `5.2=from cell`, `5.3=to cell` | `DISPLACEMENT_OBSERVED`, subtype `PUSH`: a wire consequence showing cells | Which spell caused it; actual movement if same from/to; full walkability |
| Server `jsq` action `4` | `22=4`, `20.1=to cell`, `20.2=signed target` | `DISPLACEMENT_OBSERVED`, subtype `TELEPORT`; **origin unknown** | Origin, causal spell, movement cost |
| Server `jwp` | Presence of the historical result boundary; the older handler did not use result payload for win/lose classification | `FIGHT_RESULT_BOUNDARY_OBSERVED` | **Win/lose**, rewards, confirmed terminal roster and world reentry |

**Other `jsq` actions, including documented damage, heal, shield and AP/MP action families, remain `UNSUPPORTED_ACTION` with explicit `P46_JSQ_ACTION_EFFECT_UNSUPPORTED`.** Their mappings often depend on old mutable HP/shield/resource caches, actor/source correlators and independent capture evidence that is not present in this ZIP. Copying those branches with guessed initial HP would recreate the historical false-causality and no-progress problem. This is deliberate conservative scope, not missing an implementation step disguised as success.

The source archive's version is **Dofus 3.7.10.10**. This does not establish that a newer client has the same opcode names, field meanings, cell geometry or outcome rules.

## 2. New source and contracts

- `src/anka_contracts/historical_combat.py`: frozen and strongly checked `HistoricalCombatObservation` and `HistoricalCombatResult`. Output hardcodes `HISTORICAL_RESEARCH_ONLY`, `server_effect_confirmed=False`, `victory_confirmed=False`, `canonical_commits=0`, and `physical_input_sent=False`. A `jwp` result has `outcome=UNKNOWN` by construction.
- `src/anka_protocol/adapters/historical_combat.py`: pure bounded protobuf mapper. Requires **exact** historical build, server-to-client direction, caller-provided `LegacyFightScope`, SHA-256 flow-key match, matching transport generation and valid required scalar/nested fields. Unsupported action types never accidentally become legal cast/effect claims.
- `src/anka_protocol/historical_combat_audit.py`: independent single-flow/fight/build/generation chronology; rejects repeated packet/message cursors and any post-result observation. Reports known **causality and victory gaps**.
- `src/anka_protocol/historical_combined_audit.py`: a research-only timeline combining P45 Ready/turn observations with P46 combat observations. Reuses the same scoped packet ordering but never invents a cross-socket total order. Missing turn-owner evidence is `INSUFFICIENT_EVIDENCE`; cast by a different observed actor is a **research discrepancy**, not a false claim that the client/server action was illegal (reactive effects may exist).
- Two new permanent independent test modules, `tests/test_p46_historical_combat_effect_research.py` and `tests/test_p46_combined_lifecycle_combat_research.py`. Their hand-written protobuf fixtures are synthetic **format oracles**; they are not real PCAP.

No Kernel, AI, Execution, authoritative journal, ready-to-act permission, native Unity bridge, original static asset, archived protocol source, original R5.198 file or root BAT was changed. The two user BATs remain only `setup.bat` and `start.bat`. There is no dashboard or additional operator command. The new module is reachable through Python imports for developer-only offline research/tests, not wired into live game-state authority.

## 3. Safety tests and historical bug prevention

Independent positive and negative fixtures cover signed caster/target IDs, the difference between a SpellLevel record ID and a small spell grade, actual from/to field meanings, unknown teleport origin, cells `0` and invalid `560`, missing or repeated nested fields, malformed binary protobuf, unknown `jsq` action IDs, server/client direction, exact build and flow scope, source generation, duplicate packet/message cursors, differing same-fight flow identities, result-first cases, multiple result messages, actor/caster/owner disagreement and late actions after `jwp`.

The first verified chronological distinction is **`OBSERVED` vs `PROVEN`**. The mere occurrence of `jsq/300` cannot settle a physical action. The mere occurrence of `jwp` cannot increment a victory counter. The old `jwp` handler only ended its local fight phase; P46 follows that limited claim without inventing success.

## 4. Verification — provenance and scope

- New P46 two-file suite: **41 tests, 27 subtests**. Source-backed field layouts; test packet bytes synthetic.
- Broad affected regression groups: **247 tests, 74 subtests** across new P46, P45, P44, protocol wire/architecture, older research reconciliation and verifier controls. Overlaps with the full inventory; counts are not additive.
- Independent complete test inventory: **67/67 test modules and 1,231 unittest methods PASSED**. 66 modules/1,220 tests were executed under separate subprocesses with exact AST count/checkpoint checks and source/fixture fingerprint; the historically slow `test_p37_checkpointed_verification` module was executed **separately** with `python -m unittest -q` and passed 11 tests. This is a **complete independently executed module inventory**, but **not a single uninterrupted run of the project's built-in checkpointed verifier**. Do not substitute one for the other in future receipts.
- `python -m anka_app.cli check` and `setup`: **exit 0**. Architecture: 13 packages/259 Python source modules, **PASS**; reference assets 165/165 verified; native bridge and protocol archives pass source integrity.
- `python -m anka_app.cli start`: intentionally **exit 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`**. The resulting GPT-friendly incident ZIP passed standalone integrity validation.
- Historical source provenance remains protected. Tests and preflight do **not** certify current client, Windows/Npcap, Unity bridge runtime, physical driver, or complete CRA/ENU mission. **Complete live-fight acceptance: 0%.**

## 5. Next genuinely meaningful blocker

The remaining decisive gap is **current-client evidence**: capture with exact source/build/flow and independently witnessed CRA/ENU actor/HP/AP/MP/position/turn/cast/damage/fight outcomes. A research event can be promoted to an authoritative Canonical event only under a separately certified current-build adapter and trusted Windows/process/account/flow scope. Without those evidence sources, extending action-effect tables or asserting victories would increase risk rather than deliver quality. Pending genuine captures, the next offline work should focus on binding available historical cases to actual immutable source oracles and rehearsing Canonical/Live State crash/rollback boundaries—not creating more arbitrary heuristics.

**Roadmap estimate:** **91%** of subjective planned engineering milestones (previous P45: 90%), a planning estimate **not** a quality/reliability measure. **Complete integrated current-client live CRA/ENU acceptance:** **0%**.
