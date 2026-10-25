# P34 — Fight reconstruction coverage and unsupported-effects audit

**Status: implemented and independently tested offline; RESEARCH ONLY.** No authoritative Canonical admission, live protocol certification, SQLite commit, operating-system input or automatic new-build adapter activation.

## Why this milestone exists

P33 correctly blocked a `SPELL_CAST_OBSERVED` research event because the deterministic P8 reducer cannot represent spell effects. However, a single `P33_SPELL_CAST_REDUCER_UNSUPPORTED` blocker did not show whether the remaining resource, turn, position and fight observations were otherwise reducer-compatible, or which effects would be missing from any shadow projection.

**The failure to avoid:** discarding spell-cast observations and then mistaking a coherent reducer snapshot for a complete account of what happened. Spell observations carry important effects and cooldown/limits information that a position/HP/AP snapshot cannot infer safely.

## Added source boundaries

- `src/anka_contracts/reconstruction_gaps.py`: immutable `ReconstructionCoverageReport` and `CoverageEntry`. No caller-controlled authority fields. `to_dict()` contains reason codes and counts only; no character, actor, spell, target, resource or packet values.
- `src/anka_app/reconstruction_gaps_offline.py`: application-only orchestration of the existing P33 pure bridge/reducer, with a **separate research-only trace for observed spell casts**. It never applies casts, guesses AP/HP/damage/MP changes, or manufactures action outcomes. No Capture, Protocol or Execution implementation imports.
- `src/anka_app/cli.py`: the existing fast synthetic `setup` shadow check also exercises one valid cast-with-unknown-effects trace and one invalid out-of-turn cast. No new operator launchers or extra commands.
- `tests/test_p34_reconstruction_gap_audit.py`: 33 adversarial cases, including stale flow, wrong actor, wrong fight, duplicate/reordered packet occurrence, out-of-turn casts, forged authority, no SQLite/input and diagnostic privacy.

## Reconstruction responsibility matrix

| Research event | Offline reducer handling | Remaining proof obligations |
|---|---|---|
| Fight Start | Starts synthetic fight, injects **fixture** roster | Current build, server fight ID, actual actor/account identity |
| HP / AP / MP / Range absolute | Records explicit fixture fact | Independent source/witness, freshness, actor binding, server ordering |
| Cooldown snapshot | Records supplied fixture cooldown list | Complete cast-history/cooldown chronology and current spell data |
| Actor cell | Records explicit fixture position | Movement path, MP spend, current fight walkability, push/pull, teleports |
| Turn Start / End | Updates synthetic turn-owner state | Cross-account server event ordering, turn epoch, actual delivery/confirmation |
| Spell Cast | **Observation only; excluded from reducer by design** | Server acceptance, AP consumption, cast counter, cooldown, damage/heal/shields/push/pull and target effects |
| Fight End | Marks synthetic fight phase ended | Confirmed victory/defeat, outcomes, mission result and reward evidence |

For *every* observation, the audit checks exact build/adapter/flow/transport generation, nondecreasing source coordinates, fight boundary, declared actor-fixture roster and duplicate claims. Casts must be inside the corresponding actor's observed turn. A malformed or contradictory input returns `BLOCKED_RESEARCH_ONLY` with the first failing observation index and a stable reason code. Every verified non-cast event is replayed with the unchanged `run_shadow_replay` P33 composition. Cast count remains visible and adds explicit unresolved-effect reasons.

## No incorrect completeness claims

- A reducer result of `ENDED` does **not** certify server victory, mission success or spell outcomes.
- Synthetic roster membership does **not** certify character or window identity.
- Two actor states with all HP/AP/MP/cell/cooldown fields present do **not** prove how those values changed or whether casts succeeded.
- Same-flow packet ordering does **not** establish cross-flow CRA/ENU server ordering.
- Full source continuity, modern protocol semantic correctness, independent witness evidence, calibration and physical outcome evidence are still unverified.
- Reports are deliberately labelled `GAPS_FOUND_RESEARCH_ONLY`, `INCOMPLETE_RESEARCH_ONLY`, or `BLOCKED_RESEARCH_ONLY`. None has a live-ready or actionable status.

## Example (synthetic; not real traffic)

`Fight Start → Cell → AP → CRA Turn Start → Cast → CRA Turn End → Fight End`

Expected audit result: projected non-cast events are consistent in memory; one **spell-cast observation** is retained in the report but not applied to state; `CAST_EFFECTS_UNVERIFIED`, `CAST_AP_SETTLEMENT_UNVERIFIED`, `CAST_LIMITS_AND_COOLDOWNS_UNVERIFIED`, `SERVER_CAST_ACCEPTANCE_UNVERIFIED`, `MOVEMENT_PATH_AND_MP_COST_UNVERIFIED`, `FIGHT_OUTCOME_NOT_VERIFIED`, and missing actor fields are recorded. **Zero Canonical commits, zero physical actions.**

## Verification and acceptance

- **33/33 P34 tests pass**, with no modifications to P33 test expectations; P33 still rejects unsimulated casts.
- **526 distinct relevant P34 and inherited integration tests passed across four bounded test groups.** This is not a claim that all P33 test modules were re-run.
- The additional attempt to run every inherited test in sequence exceeded the command's execution limit; the known historical verifier slowness remains unresolved.
- `setup` returned exit 0 with `shadow_projection_smoke.reconstruction_coverage` reporting `PASS_RESEARCH_ONLY`, an expected negative cast-in-wrong-turn result and `physical_input_sent=false`.
- Architecture import boundary audit: PASS (13 packages). Reused asset integrity: 165 verified. No third root-level `.bat` file.
- Windows batch execution, current-build decoding, server-confirmed outcomes and live CRA/ENU fight acceptance: **not tested**.

**Progress estimate:** 85% roadmap implementation coverage (up from P33's 84%). This is not a measured percentage of software quality. **Full live CRA/ENU fight acceptance: 0%.**

## Next high-value milestone

Implement and independently verify true research/evidence semantics for spell casting, movement and server outcomes (including required AP/MP deltas, turn/cast counters and causally matched outcomes), then qualify those against current-client evidence. Do not weaken the Canonical admission gate to make a synthetic audit pass.
