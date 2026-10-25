# P33 — Research-to-Canonical shadow replay compatibility

**Scope:** implemented and offline-verified. Does **not** certify the current Dofus client, admit production Canonical events, write SQLite, or perform game input. This milestone closes a *contract compatibility gap* between P31 historical/research semantic observations and P8 deterministic Live State projections without crossing the production safety fence.

## Source-based finding

Before P33, P31 research fight events had a different shape from P8 `OfflineStateEvent`. The reducer could track positions, HP, AP/MP, cooldowns, turn boundaries and fight ends, but there was no tested compatibility bridge between these independently developed systems. In particular, `SPELL_CAST_OBSERVED` has no corresponding reducer event, `ACTOR_SEEN` requires separate actor evidence, and no mechanism could prove that a P31 research fact belonged to the same fight, flow or transport generation as another fact. A coherent-looking set of protocol observations could therefore be mistaken for a state reconstruction that had never actually been exercised end-to-end.

## Implemented solution

- `anka_contracts.shadow_replay`: immutable `ShadowScope`, `ShadowEventSpec` and `ShadowReplayReport`; no writable live-authority fields.
- `anka_canonical.shadow_bridge`: pure, bound-checked research-to-fixture *specification* bridge, with exact protocol build, adapter ID, source-flow digest, transport generation, fight ID and source-order checks. Reject duplicate/conflicting semantic claims for the same source occurrence. Multiple **distinct** resource fields in one protobuf message are preserved.
- `anka_app.shadow_replay_offline`: the **only** cross-system composition. Converts compatible shadow specs to immutable `OfflineStateEvent` objects and runs the *actual* pure `anka_live_state.reducer.apply_offline_event` in memory. No `SQLiteFixtureJournal`, no `ExecutionLedger`, no input driver, and no capability to admit live state.
- `setup` integrates a fast positive/negative research bridge smoke. Its output is `shadow_projection_smoke`; the negative check deliberately attempts an incorrect turn-end owner. This adds **no** BAT launcher and never extends `start` with expensive synthetic tests.

## Fail-closed and honesty requirements

1. A synthetic actor roster must be supplied **explicitly** via `ShadowScope.roster_fixture` and is injected as test-only `ACTOR_SEEN`. This tests reducer prerequisites but is **not observed identity evidence**. Real Canonical admission must obtain actual actor appearance and account identity separately.
2. The first source observation must be `FIGHT_START_OBSERVED`; events must have consistent exact source/flow/generation/build/adapter provenance and monotonic packet/ordinal coordinates. Source ordering **within one flow** does not prove ordering across CRA/ENU flows.
3. Any unknown actor, duplicated fact, contradictory turn, fight-epoch mismatch, changed transport generation, or event after fight end blocks the shadow projection.
4. `SPELL_CAST_OBSERVED` is **explicitly unsupported** by the current reducer. It blocks with `P33_SPELL_CAST_REDUCER_UNSUPPORTED` instead of silently dropping an important gameplay event.
5. A truncated but internally consistent fight returns `SHADOW_INCOMPLETE_RESEARCH`; a complete synthetic projection returns `SHADOW_CONSISTENT_RESEARCH_ONLY` — **neither is certified or actionable**.
6. Reports only contain stable reason codes, counts and synthetic phase; actor IDs, packet content, names, flow hashes and resource values never enter the diagnostic output. The observer is passive.
7. Actual live Canonical admission, current-build protocol semantics, server-event cross-flow chronology, authoritative actor registers, spell/action-outcome reducers and Windows input are **not implemented** by P33.

## Verification

- 30 new negative/positive tests in `tests/test_p33_shadow_projection_bridge.py`, including input provenance attacks, resource collisions, multi-field wire messages, duplicate packet ordinals, actor-roster mismatch, turn conflicts, unknown spell-cast projection, no SQLite/open input dependencies, privacy, and forged report authority.
- 936 inherited test methods remain passing, making **966/966 across all 49 modules**, executed via isolated Python module processes; this is not a claim that the intermittent long-running grouped verifier has been cured.
- Setup command (`python -m anka_app.cli setup`, Python 3.13 Linux): exits 0, verifies 165 reused assets, reports successful shadow smoke and zero production commits.
- Start command: exits 40 with `LIVE_RUNTIME_NOT_IMPLEMENTED` and an incident ZIP, unchanged from P32.
- Architecture audit: 13 package boundaries, **0 forbidden imports**. The root operator surface is still only `setup.bat` and `start.bat`.
- Native Windows scripts, Npcap, current-build Dofus protocol, calibration and end-to-end CRA/ENU gameplay remain untested here.

## Why this is not live certification

The P8 reducer consumes immutable, explicitly synthetic fixture events. Matching its state after a P31 observation replay is a **contract compatibility test**, not evidence that a real server sent those facts or that a given account owns the corresponding window. The production admission design will need trusted source provenance, real current-build witnesses, account/actor binding, capture-loss limits, cross-flow turn ordering, atomic Canonical+Live State transactions and independent action confirmations.

**Roadmap estimate:** 84% implementation coverage (up from 83%); not a measured project-quality score. **Integrated live CRA/ENU fight acceptance: 0%.**
