# P36 — Target-effect confounder audit and reproducible per-module verification

**Release scope:** offline research and verification only. **No live input, canonical production admission, current-build adapter promotion, or server-confirmed damage/heal/MP removal.**

## Root problem
P35 relates a cast to a before/after observation **of the caster**. The project still needs a safe research interface to inspect changes to a **different observed actor**, such as HP changes to an enemy after a CRA cast or MP changes to an enemy after ENU action. The tempting shortcut—claim that the cast dealt that damage/removed that MP from the delta—is wrong if another cast, earlier snapshot change, movement, stale target-cell proof, or server-driven effect was present.

## Implemented P36 behavior
- `anka_contracts.target_effect_research` owns immutable `TargetEffectWindow`, `TargetEffectComparison`, `TargetEffectResearchReport`. The window explicitly identifies `before_index`, `cast_index`, `after_index`, `target_actor_id`, the `HP/AP/MP` metric, and optional target-cell witness index. No arbitrary actor or source can grant authority.
- `anka_app.target_effect_research_offline.audit_target_effect_windows` runs the *existing P34 whole-trace* provenance/turn/roster+P33 shadow verification before comparing any values. Wrong fight/stream/actor/turn/generation still fails closed. It checks distinct packet/message source coordinates, target metric types, exact actor identity, turn-boundary containment and duplicate/reused post snapshot.
- A target-cell observation matching the cast target is an **observed spatial coincidence**, not proof of a hit, spell range, AoE damage, server acknowledgement, or an action/actor-causal relationship. Missing, mismatching, or overridden cell evidence is exposed explicitly.
- Any other cast between pre/post observations, intervening target absolute snapshot, or observed target cell movement after cast marks the result `AMBIGUOUS`. Before/after values remain *private research deltas*, never part of `to_dict()` or GPT bundles.
- Both a changed and an unchanged target value report **unproven** server effect/causality. No code in P36 emits live actions, requests canonical commits or changes Game Kernel rules.
- `setup` adds one bounded positive/negative P36 smoke to the existing P33/P34/P35 diagnostics. `start` remains blocked.

## Verification runner improvement
`anka_app.verification_runner.verify_isolated(..., module_isolation=True)` uses the **same complete AST inventory and exact test count checks** but starts a fresh Python interpreter for **each test module** instead of placing several unrelated test modules in one child. The developer-only CLI `verify` chooses this mode. This reduces cross-module shared-global contamination and narrows a stalled module to one name. The default grouped mode is retained for backward compatibility. No extra BAT command exists.

**Limitation:** In this session two attempts to finish all 53 modules exceeded the tool execution limit without producing a complete all-module receipt (the first reached 13 module passes; the second reported 30 module passes). They did not report an assertion failure, but **an incomplete run cannot be counted as full PASS**. Developer verification should continue from individually reported module receipts on an environment with adequate execution budget. Do not present the historical P35 `1033 tests PASS` as a new P36 full-suite result.

## Test and setup evidence
- P36 tests: `tests/test_p36_target_effect_research.py` (26 tests) and `tests/test_p36_module_isolation.py` (3 tests).
- Focused neighborhood regression: **137 passed** (`P24`, `P33`, `P34`, `P35`, `P36`).
- Direct `check`: PASS (13 system packages, 247 Python files by architecture guard, 165/165 reused assets). Direct `setup`: PASS, with P36 research smoke. Direct `start`: deliberate `LIVE_RUNTIME_NOT_IMPLEMENTED`/BLOCKED; no physical input.
- No current Dofus 2026 protocol evidence/witness is contained in this ZIP. Current-client exact build, true damage and MP-removal causal effect remain unknown.

## Adversarial tests included
- Target HP change and unchanged HP **both** fail to imply cast success/failure.
- Target AP and MP differences remain research-only.
- Before/cast/after actor mismatch, metric mismatch, wrong cast index, wrong cell witness, wrong stream generation, bad index, duplicate windows and reused post snapshot are blocked.
- Competing cast **and** intervening absolute target-HP snapshot flag ambiguous deltas; observed movement flags location uncertainty.
- Same-cell witness has only spatial relation; stale/mismatched witness cannot prove direct hit.
- Public report omits HP/AP/MP numerical values, private character/account IDs, session, network packet bytes and numeric deltas.
- Module isolation tests cover each child, legacy grouped behavior, and exact stalled-module errors.

## What P36 cannot prove / next work
1. No observed packet source in this release independently proves spell effect, target damage, heal, MP reduction or true attack geometry.
2. No cross-account server order, exact-client wire capability, signed action acknowledgement, window/calibration or real physical input is certified.
3. **Next high-value milestone:** acquire the genuine current-client CRA+ENU capture and independent game-state/turn oracles, then pin a current-build research adapter and verify source-backed cast/effect/target identity. Build production Canonical admission **only after** that evidence exists. Avoid more research-only layers without new evidence.

**Estimated weighted roadmap coverage P36: 87%** (subjective implementation milestones; not software quality). **Full live CRA+ENU mission acceptance: 0%**.
