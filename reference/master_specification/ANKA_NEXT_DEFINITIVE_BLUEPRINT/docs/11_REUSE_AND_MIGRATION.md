# 11 — Reuse & Migration from R5.198

## 1. Principle

Build a **new composition and package topology**, not a new knowledge base from nothing. The old project is a read-only reference and source of proven assets/regressions.

Every reused item is classified:

- `UNCHANGED_REUSE`
- `ADAPTED_REUSE`
- `REIMPLEMENTED_FROM_BEHAVIOR`
- `HISTORICAL_FIXTURE_ONLY`
- `DISCARDED`

---

## 2. Reuse map

| Legacy area | Target | Strategy |
|---|---|---|
| `src/anka_game_kernel/*` | `anka_game_kernel` | UNCHANGED_REUSE where practical |
| Kernel verified spell/data assets | `assets/game_data`, Kernel data | reuse with manifests/hashes/scope |
| `calibration/*`, shared 1280×649 points | `anka_client/calibration`, assets | ADAPTED_REUSE; current host revalidation |
| `projection/*`, Unity bridge | `anka_client/projection`, `native/unity_bridge` | ADAPTED_REUSE behind new public ports |
| Windows identity/focus logic | Client/Execution split | extract narrow logic; do not copy giant service boundaries |
| Capture transport helpers | `anka_capture` | selectively reuse pure stream logic |
| `protocol/*`, adapters | `anka_protocol` | reuse historical adapter logic/evidence; rebuild registry/promotion boundary |
| live reducer/store | Canonical + Live State | preserve semantics/atomicity; new contracts |
| core fight/FightAI | `anka_decision` | reuse policies/algorithms; eliminate runtime coupling |
| party/campaign/scripting | Coordination + Workflow | reuse state-machine behavior, rebuild ownership/wiring |
| Execution control/arbiter/settlement | `anka_execution` | preserve safety mechanisms; split internal modules |
| observability/diagnostics/simulation | Observability + test lab | reuse scenarios/forensic ideas, simplify/passive boundary |
| web/Script Studio | none | DISCARD UI; extract hidden domain/session behavior first |

---

## 3. Reuse manifest

`REUSE_MANIFEST.json` fields:

```text
legacy_release_sha
legacy_path
legacy_file_sha256
target_path
target_sha256
reuse_mode
semantic_change = true/false
rationale
required_tests
build/data scope
known limitations
ADR/regression IDs
```

This makes future developers aware whether a target file is known-good preserved logic or new rewrite.

---

## 4. Important reference assets and cautions

### Kernel
Strong reuse candidate. Keep independent.

### Calibration
Historical measured profile; not current-window proof. Preserve numbers/provenance, revalidate.

### Game data
`COMPATIBILITY.json` scope is limited. Do not advertise full current-game compatibility.

### Protocol
Historical adapters are useful replay evidence. Adapter label and observed client build can differ; do not rename evidence to pretend exact-build certification.

### Mission/config
Legacy config/mission files contain precedence differences. Define one new compiler; parity tests specify intentional behavior.

### FightAI
Preserve useful class strategy, but one stable ActionPlan codec must replace ad-hoc serialization boundaries.

### UI
Before deleting Script Studio/web, locate every domain responsibility it currently performs: config validation, mission compile, process lifecycle, startup status, control authority, shutdown. Move those to proper systems/App, then discard UI.

---

## 5. Migration anti-patterns

Do not:

- copy entire `anka_platform` into renamed directories;
- move files while changing wire semantics and state schema simultaneously;
- keep both old/new state writers active;
- keep two physical input drivers during migration;
- replace tests with weaker tests because paths changed;
- delete legacy fixes because new architecture looks cleaner;
- call a file “unused” before tracing runtime/test/package entry points;
- upgrade dependencies casually during architectural extraction.

---

## 6. Migration evidence

For each extracted system compare, where applicable:

- serialized public output;
- canonical event stream;
- state snapshots/hashes;
- Decision plans/ActionKeys;
- Execution receipts/outcomes;
- workflow transitions/counters;
- incident diagnostics.

Differences are either regressions or documented intended corrections with independent evidence.

---

## 7. Legacy command simplification

The old project has many BAT tools. Target operator UX keeps only `setup.bat` and `start.bat`.

Before removal, preserve their essential behaviors inside:

- setup validation;
- app startup/preflight;
- automatic diagnostics;
- developer Python tools;
- internal verification gates.

Do not delete a safety check merely because its old entrypoint was a BAT file.

---

## 8. Migration is complete when

- no target runtime depends on `anka_platform` compatibility facade;
- all target systems have clean public APIs and architecture tests;
- reused assets have provenance/hash manifests;
- legacy regression corpus still passes or intentional changes documented;
- old web/operator code can be removed without loss of required domain behavior;
- exact packaged new release passes relevant gates.

