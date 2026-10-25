# 10 — Development Roadmap

## 1. Roadmap principle

Build **foundations before authorities**, and move one authority at a time. Do not perform a big-bang package rewrite. Preserve old reference behavior/evidence while the new project gains independently verifiable systems.

Diagnostics and tests start at the first milestone, not at the end.

---

## M0 — Freeze reference baseline and evidence catalog

### Objective
Prevent rediscovery and accidental rewriting of history.

### Work
- hash exact R5.198 reference ZIP/files;
- inventory Kernel/data/calibration/protocol/adapters/tests/docs;
- classify evidence: `ARCHIVED_RAW`, `ARCHIVED_JOURNAL`, `ARCHIVED_DIAGNOSTIC`, `DERIVED`, `SYNTHETIC`, `MISSING`;
- freeze historical regression inputs;
- record known live-pending boundaries;
- create `REUSE_MANIFEST.json` skeleton.

### Completion
Reference can be reproduced/read without modification; test/evidence claims clearly scoped.

---

## M1 — Contracts, architecture gates, Verification Lab, bootstrap diagnostics

### Objective
Create the shared language and test infrastructure **before** moving business code.

### Work
- scaffold target package tree;
- implement IDs/versions/evidence/error/action/state contracts;
- implement architecture import checks;
- fake State/Kernel/Client/Execution ports;
- virtual clock/fake input/fault hooks;
- minimal bootstrap recorder from setup/start;
- structured diagnostic envelope + fake incident ZIP;
- implementation-status/verification receipt schema.

### Completion
- forbidden import mutant is caught;
- missing Python/fake setup error produces evidence;
- contracts serialize/round-trip/invalid cases pass;
- fake full-stack can run with zero input.

---

## M2 — Preserve Game Kernel and scoped game data

### Objective
Reuse the strongest proven foundation without changing its meaning.

### Work
- copy full `anka_game_kernel` with provenance;
- migrate required data assets/manifests;
- preserve old unit fixtures;
- create KernelQueries adapter/port;
- document unsupported mechanics/data scope.

### Completion
Kernel tests/parity pass; no runtime/platform imports; exact data/rulepack hashes recorded.

---

## M3 — Client identity, calibration and projection (observe-only)

### Objective
Prove who/where the physical client is before building real input.

### Work
- import validated calibration model/data;
- extract Windows identity/focus discovery behind public API;
- wrap Unity bridge/projection;
- implement automatic configured-name→live-character/class/window binding;
- implement invalidation/revalidation generation model;
- add spell-slot/loadout evidence model.

### Completion
Wrong/ambiguous PID/HWND/class/size/DPI/map/slot produces zero input proof; current Windows host still requires later live acceptance.

---

## M4 — Capture

### Objective
Own ordered transport evidence independent of Dofus semantic decoder.

### Work
- extract transport capture/reassembly;
- exact process/flow binding;
- bounded queues/gaps/reconnect health;
- replay backend.

### Completion
Known PCAP/stream fixtures produce exact envelopes; gaps are explicit; no Protocol imports.

---

## M5 — Protocol SDK + historical adapters + current-build qualification pipeline

### Objective
Make biweekly wire changes an isolated workflow.

### Work
- extract version-independent SDK/registry;
- port historical adapters/fixtures without cross-version imports;
- implement candidate/promotion/certification metadata;
- implement semantic diff/impact matrix;
- retain decoder checkpoint/rollback semantics;
- create current-build intake workflow.

### Completion
Historical replay passes; mutation/unknown tests fail safely; a staged adapter cannot auto-activate; current build remains blocked until evidence exists.

---

## M6 — Canonical durable authority

### Objective
Create one semantic journal/writer with crash-safe ordering.

### Work
- port admission/idempotence/cursor model;
- preserve/port SQLite transaction invariants;
- inject pure StateProjector;
- implement replay/migrations;
- decoder context/commit linkage.

### Completion
Crash-cut matrix proves no duplicate/lost committed truth; restart reproduces expected cursor.

---

## M7 — Live State

### Objective
Reconstruct authoritative snapshots with field provenance/freshness.

### Work
- port/rewrite reducers behind new contract;
- immutable snapshots;
- field proof/unknown/stale model;
- fight/world geometry overlay semantics;
- historical freshness regressions.

### Completion
Golden event histories reproduce expected actor/resource/turn/world state; false-READY and false-BLOCKED tests pass.

---

## M8 — Decision

### Objective
Extract CRA/ENU/world/placement policies into replaceable planners.

### Work
- stable DecisionFrame/ActionPlan codec;
- KernelQueries use;
- class policies and candidate scoring;
- ActionKey quarantine/anti-loop;
- bounded planner budgets;
- no-action/wait semantics.

### Completion
Same frame -> expected decision; rejected plan cannot loop; dummy planner substitution proves consumers are independent.

---

## M9 — Coordination

### Objective
Establish explicit multi-account fight/Ready/turn truth.

### Work
- roster/client binding model;
- same-fight/epoch coherence;
- join/placement/Ready barriers;
- turn permits;
- cursor vector/freshness;
- delayed/duplicate/missing event handling.

### Completion
CRA→ENU scenarios converge or fail with bounded typed reason; wrong account never gets permit.

---

## M10 — Workflow

### Objective
Own the mission lifecycle with strict config and bounded recovery.

### Work
- compile mission from one JSON + internal assets;
- patrol/group selection;
- fight entry/active/end/reentry phases;
- attempts/wins/stop policies;
- semantic progress/watchdogs;
- restart/resume rules;
- fake Decision/Execution integration.

### Completion
Full zero-input world→fight→world mission simulation; counters idempotent; no infinite Ready/turn loop.

---

## M11 — Execution (real input authority last)

### Objective
Introduce physical input only after upstream proof is strong.

### Work
- extract/rewrite admission;
- one control lease/input arbiter;
- Win32 driver;
- action prepared/send ledger;
- settlement/outcome modules;
- pointer motion;
- uncertain side-effect recovery.

### Completion
Fault-cut matrix, stale/focus/wrong-window tests, zero duplicate sends; real input remains disabled by default outside explicit Windows acceptance.

---

## M12 — Full app/observability hardening and release packaging

### Objective
Make the systems a coherent releasable Windows product.

### Work
- single `anka_app` composition root;
- complete setup/start bootstrap diagnostics;
- dependency/resource packaging;
- incident ZIP privacy/integrity;
- clean shutdown/recovery;
- remove legacy UI/service dependencies not required by technical bridge;
- final architecture/import gate.

### Completion
Clean ZIP extract -> setup/start observe-only works on Windows; one fake fault yields complete sanitized diagnostic bundle; no extra BAT launchers.

---

## M13 — Exact-current-build observe-only and action acceptance

### Objective
Prove external boundaries that offline code cannot establish.

### Work
- identify exact current client build;
- qualify adapter/data/calibration/bridge;
- observe both accounts with input disabled;
- bounded action scopes;
- full CRA/ENU fight and world reentry acceptance.

### Completion
Separate live acceptance receipt with exact release/evidence hashes. If any boundary is missing, status remains live-pending.

---

## 2. Per-milestone mandatory artifacts

Every milestone produces:

- source changes;
- public contract updates if any;
- unit/contract/fault/integration tests;
- diagnostics coverage;
- verification receipt;
- known limitations/missing evidence;
- reuse/ADR updates;
- rollback/cutover plan if replacing an old authority.

No milestone is complete because code was moved or compiles.

---

## 3. Cutover rules

- never run old/new mutable authority simultaneously for live input/state;
- shadow compare only read-only/proposal outputs;
- physical input from one implementation only;
- preserve legacy baseline until new gate passes;
- a parity difference is investigated—do not automatically copy old behavior if it was the defect;
- explicit semantic corrections need independent oracle + ADR.

---

## 4. Priority categories

### Critical foundation
Contracts, durable state/action safety, protocol isolation, identity, coordination, diagnostics, regression lab.

### High-value structural
Package dependency inversion, JSON/headless operation, reproducible packaging, class/profile abstraction, performance/observer bounds.

### Useful but deferrable
Eight-account performance tuning, richer routing/classes, more advanced tactical policies, optional additional calibration profiles.

### Rejected/low-value now
Dashboard, microservices, cloud observability, full rewrite of Kernel, extra BAT launchers, automatic semantic protocol inference.

