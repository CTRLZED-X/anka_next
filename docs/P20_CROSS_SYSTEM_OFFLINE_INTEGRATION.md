# P20 — Cross-System Replay & Two-Command Operator Workflow

## Scope

Replays real P8 Canonical journal commits and audited projections, real P17 party coordination, a real P12 Kernel-backed Decision probe and real P18/P19 durable synthetic execution. Modules remain owned by their systems; composition belongs to `anka_app`. There is **no app/service process split**, no dashboard, and no physical input.

## Two Windows commands

- `setup.bat`: bootstrap, configuration check, reuse-manifest hash check, historical calibration audit, Kernel load, healthy + broken P20 replay, first-failure diagnostic capture.
- `start.bat`: same safeguards, then an explicit live-readiness refusal (exit 40) until current-client and live execution gates pass. The blocked run generates an incident ZIP automatically.

All old demo/check/debug/audit BAT wrappers are removed. Python developer tests and diagnostic modules remain accessible for regression coverage, without cluttering the operator workflow.

## Evidence and authority boundaries

1. Canonical fixtures are type-checked, hash-linked, SQLite-committed and replay-verified. Synthetic evidence is never promoted to current-client authority.
2. Coordination independently replays Ready, Fight Started, Turn Start, End-Turn Intent, Turn End Confirmation and ENU Turn Start.
3. Integration reconciles CRA/ENU journal state against party turn ownership, fight IDs and account generations. Mismatches block further processing.
4. Decision runs preserved Kernel availability checks, but can return **RESEARCH_ONLY** at most.
5. An **explicit, independent synthetic fixture action**, not a converted decision, is passed to a fake-only driver using a durable dispatch boundary and exact-scope outcome fixture. No actual input is possible.
6. Any failure is labeled by the first observed failing boundary and recorded by the observer; later steps must not run after an upstream failure.

`SYNTHETIC_REPLAY_PASS` proves only this offline fixture path. It does not mean the spell is equipped or game-server accepted a physical command.

## Failure matrix

| Fixture | Detection | Fake attempts |
|---|---|---:|
| happy CRA → ENU handoff | SYNTHETIC_REPLAY_PASS | 1 |
| missing Turn End confirmation | overlapping/early turn | 0 |
| CRA state still owns turn | P20_CRA_TURN_STILL_ACTIVE | 0 |
| stale ENU state | P20_ENU_TURN_NOT_RECONCILED | 0 |
| incorrect ENU fight ID | P20_ENU_STATE_SCOPE_MISMATCH | 0 |
| focus lost after dispatch boundary | P19_WINDOW_FOCUS_NOT_VERIFIED; uncertain | 0 |
| no outcome evidence | P19_NO_INDEPENDENT_OUTCOME_EVIDENCE; uncertain | 1 |
| fake driver raises after possible send | P19_FAKE_DRIVER_RAISED_AFTER_POSSIBLE_ATTEMPT; uncertain | 1 |
| duplicate attempt | P18 duplicate-detection fence | 1 total |

## Limitations and future criteria

These scenarios use synthetic actor identities and independently supplied synthetic ACCEPTED evidence. Future live integration needs current-build protocol qualification, shared event/turn epoch correlation, production identity attestation, state completeness, actual path/cast replay and genuine outcome observers. Never use a research result to authorize live input. Windows BAT execution was not exercised in this Linux release environment.

> **P22 extension:** Before Decision, exact event-level party/journal source-link matching is now required. See `docs/P22_CAUSAL_EVENT_PROVENANCE_OFFLINE.md`. This older document describes the P20 baseline only.
