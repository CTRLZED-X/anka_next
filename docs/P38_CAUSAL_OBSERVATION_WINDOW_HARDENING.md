# P38 — Causal observation-window hardening (research only)

**Date:** 21 October 2026  
**Baseline:** complete P37 project; preserve all prior source and operator assets.  
**Scope:** fix a concrete false-clarity class in the existing P35/P36 research comparison algorithms. No protocol adapter promotion, current-client certification, production Canonical event admission, or physical game input.

## Source-grounded defects

The P35 before/cast/after comparison formerly marked a total HP/AP/MP/range/cooldown/cell difference as `CHANGED` or `UNCHANGED` even when an **intermediate absolute observation of the same actor and metric** already explained the net difference. P36 already marked certain intermediate target snapshots as ambiguous, making P35/P36 inconsistent at the consumer boundary. P35 also failed to flag a movement observation in an MP window as a competing explanation. Both P35 and P36 allowed a baseline from a *previous completed turn* to be presented as a simple clean single-turn change; current-turn evidence preceding the first `TURN_START` must remain acceptable (R5.196's historical false-freshness guard lesson).

These were confirmed limitations in *research result classification*, not evidence of an actual wrong physical game action: P35/P36 were already non-actionable and explicitly refused to prove spell effects. P38 closes these misleading labels without changing the underlying delta or inventing a server causality proof.

## Changes and semantics

- `src/anka_app/effect_reconciliation_offline.py` (P35): mark a window `AMBIGUOUS` when it contains intervening same-actor/same-metric observations (including HP, cooldown and cell), when a completed turn ends after the baseline but before cast, or when an MP window contains actor-cell observations that may reflect movement. A different actor's snapshot and a different resource metric do **not** trigger these guards.
- `src/anka_app/target_effect_research_offline.py` (P36): mark a target HP/AP/MP window `AMBIGUOUS` if its before snapshot crosses a completed turn before the selected cast. Preserve its existing competing-cast, intervening-target-absolute, and after-cast movement checks.
- Keep `CHANGED` and `UNCHANGED` for clean *research* windows, not for any proven effect or action acceptance. In every case, `actionable=False`, `current_build_certified=False`, `server_effect_proven=False`, `physical_input_sent=False`, and no Canonical commit.
- Source coordinates and proof-scopes continue to be checked by P34 before any comparison; unrelated clients/epochs are rejected by prior guards.
- Preserve existing P35's historical `P35_INTERVENING_CAST_MAKES_DELTA_AMBIGUOUS` reason for consumer compatibility and add P38-specific caveats and general `P38_OBSERVATION_WINDOW_CONFOUNDED` when relevant.

**Important nuance:** An earlier `TURN_START` alone is not a confounder: current-turn AP/MP evidence can legitimately be received before TURN_START. This avoids recreating the false rejection from the historical R5.196 guard.

## Falsification tests

`tests/test_p38_causal_window_confounders.py` adds 12 independent tests covering: pre-cast AP change; equal before/after value with an intervening change; cooldown, HP and cell observations; MP movement; unrelated actor; unrelated resource; pre-window crossing completed turn in P35 and P36; valid first turn with earlier resource observation; and no external causal authority. All source fixtures use distinct same-flow packet coordinates and P34 whole-trace validation.

## Verification truth

- New P38 suite: **12 passed**.
- Focused P24/P32–P38 and protocol-architecture regression: **191 passed** before release metadata updates; final rerun details in `verification/P38_offline_acceptance_receipt.json`.
- Current `check` and `setup`: PASS, 13 source packages / 247 audited Python files, 165/165 reused source assets. Direct `start` exits **40** (`LIVE_RUNTIME_NOT_IMPLEMENTED`), with incident ZIP. No input is sent.
- Full 55-module regression inventory: **23/55 completed, 449 test methods passed** through isolated per-module verification; the second batch exceeded the external execution limit while module 24 was starting. Checkpoint preserved the 23 passes. Overall status **INCOMPLETE**, not PASS. Windows/Npcap/Unity bridge and current-build Dofus evidence are not available in this local environment.

## Progress and next priorities

Estimated weighted development coverage **remains 88%**: this milestone prevents a research interpretation error but does not complete additional live integration. Complete live CRA+ENU fight acceptance **0%**. These are separate non-quality metrics, not measured reliability.

The next material blocker is independently witnessed **current-client CRA+ENU server protocol evidence** and Windows account/window ownership. Once available, prioritize version-local protocol semantic mapping, source-level actor/fight/turn and spell outcome qualification, and only then production Canonical admission. Do not add synthetic scoring or unsafe guessed effects while these gates remain blocked.

**Operator surface unchanged:** only root `setup.bat` and `start.bat`. Do not create a standalone handoff attachment for each milestone; release notes and source evidence live inside the complete ZIP.
