# 12 — Traceability, ADRs, Risks & Open Questions

## 1. Requirement traceability

This is a high-level matrix. Individual tests should reference requirement IDs in names/metadata where useful.

| Requirement family | Primary owner(s) | Main verification |
|---|---|---|
| RQ-PROD-001 authoritative observation | Protocol, Canonical, LiveState, Execution | semantic replay, state provenance, admission tests |
| RQ-PROD-002 multi-account | Coordination, Workflow | CRA/ENU barrier/handoff systemic cases |
| RQ-PROD-003 Kernel | GameKernel | pure mechanics/data tests |
| RQ-PROD-004 protocol isolation | Protocol + architecture | adapter substitution/import tests/current-build certification |
| RQ-PROD-005 input authority | Execution | architecture + fake-driver call-count + crash tests |
| RQ-PROD-006 settlement | Execution | operation-specific outcome/correlation tests |
| RQ-PROD-007 fault containment | all owners | injected failures/scoped control-state tests |
| RQ-PROD-008 regression conversion | Verification Lab | incident manifests + permanent cases |
| RQ-PROD-009 diagnostics | Observability | first-divergence/gap/incident bundle tests |
| RQ-PROD-010 minimal UX | App/packaging | release tree/operator acceptance |
| RQ-ID-* identity | Client/Coordination/Execution | wrong-window/class/loadout/epoch tests |
| RQ-CFG-* | App/Workflow | strict schema/precedence/golden effective plan |
| RQ-PROTO-* | Protocol | upgrade gates U0-U10 |
| RQ-REL-* | Canonical/Execution/Workflow/etc. | crash/liveness/fault tests |
| RQ-DIAG-* | Observability/App bootstrap | setup/runtime incident sabotage suite |
| RQ-TEST-* | test infrastructure | quality-gate receipts |
| RQ-MAINT-* | architecture/composition | import graph/substitution/migration gates |

---

## 2. Architecture Decision Records — accepted baseline

### ADR-001 — Modular monolith, not microservices

**Decision:** separate top-level packages, initially one application process.  
**Reason:** local Windows automation needs low latency, clear ownership and simple recovery; network-distributed services add unnecessary failure surfaces.  
**Reverse if:** measured isolation/performance evidence supports a specific process split.

### ADR-002 — Preserve Game Kernel

**Decision:** reuse existing pure Kernel and data where valid.  
**Reason:** major working mechanics foundation; rewrite risk outweighs aesthetic benefit.

### ADR-003 — Canonical and Live State separate logically, one durable commit path

**Decision:** Canonical owns journal/transaction; LiveState owns pure reducer/snapshot meaning, injected into commit workflow.  
**Reason:** preserves R5.198 atomicity while achieving public independence.

### ADR-004 — Outcomes remain inside Execution initially

**Decision:** no standalone Outcomes system.  
**Reason:** send uncertainty/settlement is safety-critical and tightly coupled to one physical action lifecycle.

### ADR-005 — One physical input authority

No system/diagnostic/watchdog may click directly except Execution through the controlled driver.

### ADR-006 — JSON/headless; no dashboard

Only `config/user.json`, terminal status, automatic local diagnostics. Unity bridge loopback technical endpoint is not operator UI.

### ADR-007 — Two normal BAT files

`setup.bat`, `start.bat` only. Developer tools remain Python/internal.

### ADR-008 — Protocol adapter release train

Wire-specific changes stay in `anka_protocol`; exact build/action-scoped certification required.

### ADR-009 — Diagnostics foundational/passive

Bootstrap evidence starts before Python dependencies; Observability cannot change gameplay authority.

### ADR-010 — Unknown is explicit

Missing/untrusted values remain unknown; no optimistic defaulting for safety-critical fields.

### ADR-011 — Cross-account vector coherence

No fabricated global revision/clock; Coordination proves required member states under a shared fight epoch.

### ADR-012 — No blind retry after possible physical send

Recovery uses authoritative reconciliation.

### ADR-013 — Offline/live acceptance separation

Status vocabulary and receipts make the distinction permanent.

---

## 3. Historical failure lessons

See Appendix A for detail. Consolidated lessons:

- schema/codec boundaries are runtime behavior, not “serialization detail”;
- quarantine/action identity must be canonical across layers;
- local delayed confirmation must not automatically trigger global disarm;
- current live evidence can supersede stale static geometry in scoped contexts;
- freshness must model causality, not one arbitrary timestamp floor;
- process/window ownership requires generation evidence;
- unknown protocol traffic should be classified/contained, not patched downstream;
- a successful first action does not prove the next protocol/lifecycle boundary;
- tests need independent oracles and negative variants.

---

## 4. Confirmed reference strengths

Preserve unless a failing test/evidence justifies change:

- separate deterministic Game Kernel;
- versioned Protocol adapters/evidence concepts;
- decoder context checkpoint/restore;
- Canonical reducer/store transactional concepts;
- single Execution input authority/arbiter;
- action settlement/uncertainty concepts;
- calibration/projection assets;
- incident/run journals/systemic zero-input simulations;
- fail-closed handling of unsupported critical truth.

---

## 5. Open questions / unvalidated assumptions

| Item | Status | Why it matters | Required evidence |
|---|---|---|---|
| Current Dofus client build/protocol | unresolved/current-time external | action semantics | fresh build/capture + adapter certification |
| Current calibration at user display/DPI | unvalidated | click accuracy | Windows projection/calibration acceptance |
| Automatic class/loadout source | design requires proof | wrong class/slot causes unsafe action | current-client identity/loadout evidence |
| Full CRA→ENU Ready/turn/reentry | historical live pending | main mission | bounded live acceptance |
| Exact tackle/lock mechanics if still unsupported | capability-specific | movement choices | Kernel implementation/data/tests or explicit unsupported |
| Map coverage beyond required route | incomplete | generalization | data inventory/current routes |
| 8-account scale | target only | CPU/capture/input scheduling | load + Windows tests |
| New protocol negative-absence semantics | per build | false “nothing happened” conclusions | current-build complete capture/oracle |
| Unity bridge current install/build | environment-specific | projection/identity | clean Windows setup + live endpoint evidence |

---

## 6. Risks and controls

### R1 — Architecture overengineering
Control: no new system/process without owner/state/test benefit; ADR required.

### R2 — Reusing stale data/calibration
Control: manifests + build/layout scope + live revalidation.

### R3 — Tests certify same wrong logic
Control: independent oracles, mutation tests, historical raw evidence labels.

### R4 — Diagnostics overload
Control: bounded queues/storage, priority evidence, passive behavior, drop counters.

### R5 — Protocol release falsely “green”
Control: staged structural/replay/observe/action gates; capability-scoped status.

### R6 — Big-bang migration
Control: milestone/cutover one authority at a time.

### R7 — False confidence from offline pass
Control: separate status vocabulary/live gates.

### R8 — Cross-account stale identity
Control: generation-bound Client/Coordination proofs before input.

### R9 — Exactly-once illusion for OS input
Control: durable pre-send ledger + uncertainty reconciliation; no blind retry.

### R10 — UI removal loses hidden domain logic
Control: trace/port mission/session/startup behaviors before deleting legacy web code.

---

## 7. Decision reversal criteria

A future design may revise baseline decisions when evidence shows, for example:

- Canonical/LiveState one transaction prevents required scalability and an asynchronous projection design passes full crash/replay proof;
- Execution Outcomes needs an independently durable/scaled lifecycle and split crash tests prove safety;
- a dashboard becomes necessary for a measured operational need that terminal/incident bundles cannot satisfy;
- a system-specific process boundary substantially improves reliability without violating input/state authority;
- Kernel data/architecture becomes incompatible with required current mechanics and targeted replacement is proven safer than adaptation.

Changes are evidence-driven, not trend-driven.

