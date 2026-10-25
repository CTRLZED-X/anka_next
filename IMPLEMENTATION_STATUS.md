# ANKA_NEXT — Implementation Status

**Current release candidate:** `ANKA_NEXT_M12_006` — causal diagnostics, phase authority, and full-chain hardening.
**Physical input:** disabled. **Live acceptance:** still evidence-gated.
**Hardening details:** `docs/M12_006_CAUSAL_DIAGNOSTIC_AND_FULL_CHAIN_HARDENING.md` (building on the sealed M12_005 baseline).

**Roadmap authority:** `reference/master_specification/ANKA_NEXT_DEFINITIVE_BLUEPRINT/`  
**Starting implementation baseline:** ANKA_NEXT P66  
**Starting P66 ZIP SHA-256:** `9c0edf863de39be9479bbd25e39c22d089af088268f9cf0afcc87e37f7765297`  
**Legacy R5.198 ZIP SHA-256:** `f1a50a3555cbe89f27d58ef8411cfcb002ec3cd1cd5aefe4546b4285f47f62d6`  
**Current observed client build:** `BLOCKED_MISSING_EVIDENCE` — M12_006 collects privacy-safe executable ProductVersion on the next Windows `start`  
**Active current-build adapter:** none certified

> This file describes implemented/verified state under the definitive M0–M13 roadmap. The pre-roadmap P1–P66 status is preserved at `docs/history/IMPLEMENTATION_STATUS_P66_PRE_MASTER_ROADMAP.md`.

## 1. Milestone status

| Milestone | Status | Evidence receipt | Blockers / notes |
|---|---|---|---|
| M0 Baseline | **CONTRACT_VERIFIED** | `verification/Q0_baseline_receipt.json` | Offline provenance/evidence gate only; 0 physical input |
| M1 Contracts/Lab/Diagnostics | **CONTRACT_VERIFIED** | `verification/Q1_architecture_receipt.json`, `verification/Q2_contracts_receipt.json` | Offline/zero-input M1 complete; actual Windows bootstrap remains Q10 |
| M2 Kernel | **REPLAY_VERIFIED** | `verification/Q3_kernel_data_receipt.json` | 137/137 Kernel and 27/27 game-data byte parity; 214 Q3 tests PASS; current-live scope intentionally unaccepted |
| M3 Client | **FAULT_VERIFIED** | `verification/M3_client_offline_receipt.json` | Offline observe-only foundation complete; current Windows/current-client acceptance remains Q10/Q11 |
| M4 Capture | **FAULT_VERIFIED** | `verification/Q4_capture_protocol_receipt.json` | Definitive ordered `WireEnvelope` boundary; current Windows capture remains Q10/Q11 |
| M5 Protocol | **REPLAY_VERIFIED / BLOCKED_MISSING_EVIDENCE(current build)** | `verification/Q4_capture_protocol_receipt.json` | Historical exact-build SDK/adapter verified; no current-build adapter active |
| M6 Canonical | **FAULT_VERIFIED** | `verification/Q5_canonical_live_state_receipt.json` | Definitive durable writer/replay/decoder-linkage verified offline; current-build admission remains blocked |
| M7 Live State | **FAULT_VERIFIED** | `verification/Q5_canonical_live_state_receipt.json` | Immutable provenance/freshness reducer verified offline; no current authoritative live feed |
| M8 Decision | **FAULT_VERIFIED** | `verification/Q6_planning_coordination_workflow_receipt.json` | Deterministic semantic planning + retained tactical regressions; no physical authority |
| M9 Coordination | **FAULT_VERIFIED** | `verification/Q6_planning_coordination_workflow_receipt.json` | Generated barrier/turn matrix + generation-bound permits; current live acceptance absent |
| M10 Workflow | **ZERO_INPUT_INTEGRATED** | `verification/Q6_planning_coordination_workflow_receipt.json` | Bounded world→fight→world/fake-execution integration; live mission acceptance absent |
| M11 Execution | **FAULT_VERIFIED** | `verification/Q7_execution_safety_receipt.json` | 143 tests + 75 subtests PASS; sole physical-input authority remains disabled/unaccepted |
| M12 Packaging/Integration | **ZERO_INPUT_INTEGRATED** | `verification/Q8_diagnostics_receipt.json`, `verification/Q9_zero_input_integration_receipt.json`, `verification/M12_offline_release_receipt.json` | Offline release/composition complete; Q10 Windows acceptance remains blocked |
| M13 Live Acceptance | BLOCKED_MISSING_EVIDENCE | none | Requires Q11→Q13 current-build acceptance sequence |

The statuses above intentionally preserve the strongest *scoped* evidence already present in P66 without treating old P-series receipts as definitive master-roadmap gate receipts. Each milestone will be re-audited and re-receipted before it is called complete under the new roadmap.

## 2. System status

| System | Status | Current evidence | Known limitation |
|---|---|---|---|
| Capture | FAULT_VERIFIED / Q10_COLLECTOR_HARDENED | Q4 + M12_002 automatic exact-flow/interface/IPv4+IPv6 startup regressions | actual target-Windows/Npcap observation still required |
| Protocol | BLOCKED_MISSING_EVIDENCE | historical 3.7.10.10 research/replay | no current-build adapter certification |
| Canonical | FAULT_VERIFIED | durable transaction/source-bound admission work | production admission remains intentionally constrained |
| Live State | FAULT_VERIFIED | Q5 durable Canonical/replay + immutable provenance reducer | no current-build authoritative live feed |
| Game Kernel | REPLAY_VERIFIED | byte-preserved R5.198 kernel + data + tests | compatibility limited to evidenced data/mechanics scope |
| Decision | FAULT_VERIFIED | Q6 semantic planner + retained tactical regressions | no physical authority |
| Execution | FAULT_VERIFIED | durable settlement + fake-driver tests | no accepted physical driver/current-host action scope |
| Coordination | FAULT_VERIFIED | Q6 exhaustive CRA/ENU barrier/turn oracle | no current live CRA/ENU acceptance |
| Workflow | ZERO_INPUT_INTEGRATED | Q6 mission lifecycle + bounded recovery scenarios | no current live mission acceptance |
| Client | FAULT_VERIFIED / Q10_COLLECTOR_HARDENED | M3 + M12_002 process-generation/build/bridge coverage checks | current Windows identity/calibration/loadout acceptance still unvalidated |
| Observability | FAULT_VERIFIED | Q8 diagnostics/forensics matrix + verified incident fallback | current-client event coverage remains Q10/Q11 evidence |

## 3. Definitive quality-gate status

| Gate | Status | Receipt / basis |
|---|---|---|
| Q0 Baseline | **PASS** | `verification/Q0_baseline_receipt.json` |
| Q1 Architecture | **PASS** | `verification/Q1_architecture_receipt.json` |
| Q2 Contracts | **PASS** | `verification/Q2_contracts_receipt.json` |
| Q3 Kernel/data | **PASS** | `verification/Q3_kernel_data_receipt.json` |
| Q4 Capture/Protocol | **PASS** | `verification/Q4_capture_protocol_receipt.json` — 713 tests / 144 subtests PASS / 0 physical input |
| Q5 Canonical/State | **PASS** | `verification/Q5_canonical_live_state_receipt.json` — 405 tests PASS / 13 subtests / 0 physical input |
| Q6 Planning/Coordination/Workflow | **PASS** | `verification/Q6_planning_coordination_workflow_receipt.json` — 209 tests / 329 subtests / 0 physical input |
| Q7 Execution Safety | **PASS** | `verification/Q7_execution_safety_receipt.json` — 143 tests / 75 subtests / 0 physical input |
| Q8 Diagnostics | **PASS** | `verification/Q8_diagnostics_receipt.json` — 112 tests / 7 subtests / 0 physical input |
| Q9 Zero-input integration | **PASS** | `verification/Q9_zero_input_integration_receipt.json` — 22 tests / 9 subtests / 0 physical input |
| Q10 Packaging/Windows | **BLOCKED_MISSING_EVIDENCE / COLLECTOR_HARDENED** | M12_002 setup/start now performs release-bound prerequisite, build, process-generation, bridge, TCP/interface and bounded observe-only evidence collection; actual Windows rerun still required |
| Q11 Observe-only current build | BLOCKED_MISSING_EVIDENCE | fresh current-build evidence required |
| Q12 Action scopes | BLOCKED_MISSING_EVIDENCE | requires Q11 then individually accepted actions |
| Q13 Live mission | BLOCKED_MISSING_EVIDENCE | requires complete bounded CRA+ENU lifecycle |

## M12_002 systemic hardening evidence

- First real M12_001 Windows setup evidence confirmed installation PASS/exit 0 but exposed setup/live-readiness coupling. M12_002 separates installation from observe-only acceptance.
- Successful `setup.bat` ends with the explicit `ANKA SETUP COMPLETED SUCCESSFULLY` banner.
- Scapy is a pinned normal setup dependency; normal start discovers process-bound TCP scope and interface internally rather than requiring operator capture filters.
- Exact Dofus process generations, executable ProductVersion consistency, TCP scope, interface, Npcap readiness, bridge coverage/projection readiness and read-only Protocol framing are captured as bounded startup evidence.
- Unity bridge coverage is per process generation; partial/duplicate/missing bridge states cannot masquerade as a healthy two-account topology.
- Runtime release integrity verifies execution-affecting files only. Non-runtime docs/tests/verification receipts remain package-sealed by the offline release verifier but cannot become gameplay/startup authority.
- M12_002 hardening details: `docs/M12_002_SYSTEMIC_WINDOWS_STARTUP_HARDENING.md`.


## M12_006 causal diagnostics and full-chain hardening

- The zero-input lifecycle now exercises world movement, fight entry, follower join, placement, Ready, first owner, combat, End Turn/handoff, fight end and world re-entry through the real Decision -> authority -> Execution -> settlement chain.
- Action authority is phase-specific. `TURN` remains strict; pre-turn and world/fight scopes cannot borrow a turn permit, and JOIN is bound to the exact target fight ID/epoch/map.
- Placement/Ready uncertainty uses the same pending-action fence and no-blind-retry discipline as combat.
- Diagnostics use bounded recent + priority flight-recorder lanes; persistent journals are asynchronous and bounded so slow/broken disk I/O cannot hold gameplay producer locks.
- Export is snapshot-based and fault-contained; advanced-analysis failure still produces a verifier-clean emergency envelope when storage permits.
- READY analysis proves each account independently and is scoped to the newest fight epoch; Protocol/Canonical batch correlation prevents cross-batch borrowing.
- Per-action forensics link Decision plan -> Workflow request -> Execution admission/send -> exact durable settlement, with trace IDs and non-causal nearby semantic context.
- `analysis/gpt_summary.json`, recovery history, proven facts, historical similarity, snapshot index, evidence gaps, and required-artifact verification make incident ZIPs directly usable for GPT-assisted diagnosis.
- Physical-input state is distinct from logical fake-driver delivery; zero-input simulations report `NOT_SENT`.
- Diagnostic sanitization loss, timeline/index omissions, causal reordering, manifest/run completeness disagreement, and malformed foreign observer events are verifier/admission failures rather than silent degradation.
- The next `start` performs bounded, idempotent recovery of durable journals from prior unclean runs and exports them as `PARTIAL` / `source_tail_uncertain` incidents; crash-tail absence is never interpreted as success or failure.
- Incident self-verification now binds GPT-facing certainty to recorder truth: any known evidence loss forces non-conclusive absence and `INCLUDED_EVIDENCE_ONLY`; crash-tail uncertainty cannot be hidden by a rehashed summary.
- Observer persistence failure is non-authoritative: bounded memory evidence remains active, the CLI reports `ANKA_OBSERVABILITY=PARTIAL`, and commands do not abort solely because diagnostic storage is unavailable.
- GPT-facing diagnostics separate boundary certainty from cause certainty; ambiguous root causes are labeled `MULTIPLE_PLAUSIBLE` and verifier-bound to `analysis/diagnosis.json`.
- The isolated verification runner now uses file-backed capture and bounded process-family cleanup, preventing inherited stdout/stderr descendants from hanging release verification after a successful test parent exits.
- Current source remains offline/zero-input only. Q10-Q13 require external evidence and are not bypassed by these diagnostics.

Final test/gate counts and the sealed implementation hash are written only after the source/receipt/manifest freeze below.

## M12_005 falsification hardening

- Observer failures are contained at Capture/Protocol/ingress boundaries and finalized diagnostics are sealed against later mutation.
- Execution ledger transitions are atomic against concurrent authoritative outcome settlement; post-driver ledger loss is non-retryable and disarms the run.
- Protocol runtime proves descriptor/build/checkpoint/source causality and rollback truth; unsafe post-decode rollback paths poison the connection generation.
- Historical protocol `r1` is immutable; corrected replay-only `r2` adds safe TCP fragmentation, bounded frame fan-out and cross-envelope provenance.
- Canonical snapshot reads independently recompute semantic identity instead of trusting a coherently rewritten storage hash.
- Windows physical driver rebinds Q12 acceptance evidence and independently revalidates final lease/client/target proofs.
- Coordination requires the same positive turn epoch from every required account before issuing a permit.
- Workflow preserves the original resume target across repeated recovery timeouts and binds resumed snapshots to the exact compiled mission plan.
- These are offline/systemic hardenings only. Q10-Q13 remain live-evidence gates.

## M12_004 evidence-integrity and progress hardening (retained baseline)

- Startup acceptance now reports known Capture queue loss, transport uncertainty, and explicit driver-loss-visibility gaps independently of Protocol semantic certification.
- Release-bound Capture/Unity setup receipt staleness is no longer silently ignored; it is additive evidence and never substitutes for current-host probes.
- Bounded Capture sampling preserves the primary polling/consumer failure when evidence-marking or shutdown also fail, and post-quiesce draining has an explicit finite progress bound.
- `ProtocolInspector.finish()` participates in the same mutation-owner lock as `consume()`/`consume_poll()`.
- Protocol transaction checkpoint/rollback failure poisons that connection-generation transaction; subsequent decoding is rejected until a fresh transaction is created.
- Incident verification treats malformed/untrusted ZIP content as structured FAIL evidence instead of crashing.
- Diagnostic snapshot/final-state/export operations are serialized so a bundle observes one coherent bounded observer state.
- `LiveCaptureAudit` can represent a future backend whose every driver-loss observation is `AVAILABLE_CLEAN`; current Scapy/Npcap observation remains unaccepted until Q10 proves the target-host behavior.
- These corrections are offline-verifiable safeguards only. Q10–Q13 remain blocked by external/live evidence, not promoted by simulation.

## M12_003 deeper readiness hardening

- One host-wide Windows `start` lease prevents two ANKA processes from racing for the same clients.
- Effective config SHA and release-manifest SHA are revalidated after bounded observation; mixed-generation evidence is rejected.
- Pre-capture process generation is fenced before the sniffer starts, not only after capture.
- Live Capture has serialized start/quiesce/stop state so concurrent shutdown cannot seal evidence while callbacks remain active.
- Protocol transaction/registry, Capture transport assembly/audit, Canonical writer, Coordination and Workflow have explicit mutable-owner serialization.
- Win32 window observations are process-generation coherent through a held process handle plus final HWND→PID recheck.
- Future Windows action scope requires exact release/config/Q12/run/build/action binding and remains disabled/uncomposed.
- Input-arbiter faults permanently disarm the Execution service instance. Ctrl+C produces an `INTERRUPTED` incident and explicit `NOT_SENT` input evidence.
- Dedicated M12_003 live-readiness hardening suite is part of final M12 packaging acceptance.

## 3A. M12_003 final verification evidence

- Complete broad sweep: **113/113 top-level test files**, **1,859 tests + 707 subtests PASS**.
- Q1 architecture: **13 packages / 355 modules / 0 violations / 0 cycles / 0 unreviewed dynamic imports**.
- Q4 Capture/Protocol: **711 tests + 144 subtests PASS**.
- Q5 Canonical/State: **402 tests + 11 subtests PASS**.
- Q6 Decision/Coordination/Workflow: **204 tests + 329 subtests PASS**.
- Q7 Execution: **141 tests + 71 subtests PASS**.
- Q8 Diagnostics: **24/24 PASS**.
- Q9 full CRA+ENU zero-input integration: **22 tests + 9 subtests PASS**.
- M12 release integration: **50 tests + 2 subtests PASS**, **0 physical inputs**.
- All Q1–Q9 receipts are bound to the same final implementation source SHA.
- Q10–Q13 remain blocked only by real Windows/current-client/live-action evidence; no offline test is promoted to live acceptance.

## 4. M0 evidence summary

- Exact R5.198, starting-P66 and master-spec archives are bundled read-only and SHA-256 frozen.
- Complete file-level manifests exist for all three baselines.
- The authoritative master specification is extracted verbatim in-tree and independently verified.
- R5.198 evidence is classified without upgrading derived reports to raw evidence.
- Missing original historical PCAP/journal and current live evidence are explicit.
- A detailed reuse ledger records 171 source-bound reuse/migration decisions at M0.
- Key historical failure families and recurring symptoms are permanent catalog entries.
- M0 modifies no P66 runtime/config/assets/native/operator-launcher behavior.
- `anka_platform` remains absent from the new runtime import tree.
- Q0 physical input count is exactly 0.

## 5. Unresolved evidence / blockers

See `reference/m0/live_pending_boundaries.json`. The main blockers remain current-build protocol truth, current Windows/client identity and calibration, independent class/loadout evidence, CRA/ENU live lifecycle acceptance, and individually accepted physical action scopes.

## 6. M1 evidence summary

- Q1 architecture graph: 13 reviewed packages / 354 Python modules / 0 violations / 0 top-level SCC cycles / 0 unreviewed dynamic imports.
- Q1 architecture + mutation tests: 26/26 PASS.
- Q2 contract/diagnostic/bootstrap tests: 28/28 PASS.
- Definitive typed IDs, evidence, version, wire, state, mechanics, Decision, action, coordination, workflow, client, error and verification-receipt contracts are present.
- Dependency-inversion ports exist for all M1-required fakeable boundaries.
- Verification Lab includes virtual time, deterministic fault hooks and zero-OS-input fakes.
- The M1 contract walk crosses State -> Kernel -> Client -> Execution and records physical input count = 0.
- Fake diagnostic incident ZIP integrity verifies PASS.
- Actual Windows `cmd.exe` startup remains deliberately outside M1 and is retained for Q10.

## 7. M2 evidence summary

- Legacy/current Kernel source parity: 137/137 files byte-identical.
- Legacy/current scoped game-data parity: 27/27 files byte-identical.
- Kernel has zero forbidden imports from ANKA runtime/platform systems.
- The host-side `KernelQueries` adapter keeps static readiness separate from live legality and returns `INDETERMINATE` whenever live context is required.
- CRA (class 9), Enutrof (class 3), 47 verified spell-mechanics entries and bundled map scope are explicitly recorded with provenance.
- Q3 current adapter/data tests: 8/8 PASS.
- Q3 independent legacy mechanics oracle: 206/206 parametrized cases PASS across geometry, range, LoS, AoE, movement, casting, readiness, targeting, displacement, collision and relocation.
- Q3 total: 214 PASS / 0 FAIL / physical input count 0.
- The remaining legacy Kernel fixtures stay immutable and hash-addressable for targeted regressions; Q3 does not claim current-client mechanics acceptance.

## 8. M3 evidence summary

- M3 offline receipt: `verification/M3_client_offline_receipt.json` PASS.
- Client ambiguity/fault matrix: 170/170 PASS, physical input count 0.
- Historical calibration is source-hash bound, contains 22 spell slots, and cannot self-promote to current certification.
- PID + HWND + process creation, foreground/visibility, size/DPI, bridge map/projection generations, calibration generation and loadout generation are explicit invalidation inputs.
- Spell projection requires a fresh same-generation loadout-to-slot proof; slot coordinates alone never prove spell identity.
- Native Unity bridge source parity: 14/14 compared files byte-identical to R5.198.
- `anka_client` contains zero physical-input primitives and cannot grant input authority.
- Current Windows host/client acceptance remains explicitly outside M3 and blocked pending Q10/Q11 evidence.

## 9. Next authorized milestone

**Q10 — Windows packaging/startup acceptance, then Q11 observe-only current-build acceptance.**

M0–M12 are complete to the maximum offline/zero-input level supported by this environment. No further source feature should be promoted merely to increase a percentage. The next admissible evidence must come from an actual Windows host: clean `setup.bat`/`start.bat`, process/window generation, network-flow ownership, calibration/projection/loadout observations, dependency artifact hashes, and verified incident output. Physical input remains disabled. After Q10, Q11 must certify the exact current Dofus build in observe-only mode before any Q12 action scope can be considered.


## 10. M4/M5 evidence summary

- Q4 receipt: `verification/Q4_capture_protocol_receipt.json` PASS.
- Capture regression: 162 pytest cases + 80 subtests PASS.
- Protocol regression: 551 pytest cases + 64 subtests PASS.
- Q4 total receipt test count: 713 PASS + 144 subtests / 0 FAIL / physical input count 0.
- Capture owns exact flow/client binding, connection generations, ordering, retransmission/overlap, explicit gaps/loss fences and replay parity through `WireEnvelope`; it imports no Protocol implementation.
- Protocol now has a version-independent SDK, explicit exact-build registry, stepwise release lifecycle, semantic impact diff, current-build intake, exact opaque fingerprint policy and transactionally rollbackable decoder context.
- Historical Protocol release `r1` is preserved byte-for-byte under `reference/m5/releases/` at its original code hash. The corrected executable historical replay adapter is `adapter-dofus-3.7.10.10-historical-m5-r2`, has a distinct hash, remains `REPLAY_CERTIFIED` only, has no action scope, and cannot auto-activate.
- `FRAMING_IN_PROGRESS` permits zero-semantic checkpoint progress for genuine cross-envelope TCP fragmentation without granting game-state truth. Complete unknown/unproven traffic remains fail-closed. Canonical reject/uncertain paths prove rollback and fence the connection generation so rejected bytes cannot create a hidden stream hole.
- No current-build adapter is certified or active; fresh current-build evidence remains required for Q11/Q12.


## 11. M6/M7 evidence summary

- Q5 receipt: `verification/Q5_canonical_live_state_receipt.json` PASS.
- Q5 regression total: 405 pytest cases + 13 subtests PASS / 0 FAIL / physical input count 0.
- Canonical exact-release admission accepts only semantic candidates or exact evidence-certified zero-semantic opaque batches; `NO_SEMANTIC_MAPPING` cannot advance trusted decoder context.
- Candidate source connection/generation/order, source relabeling, duplicate candidate IDs, batch identity and account/client scope are fail-closed.
- SQLite journal uses WAL + synchronous FULL; event history, projected snapshot and decoder checkpoint linkage commit atomically.
- Pre-commit crash cuts leave no partial truth; commit acknowledgement ambiguity fences the writer and requires reopen/audit/replay rather than blind append.
- `anka_app.adapters.protocol_canonical.CanonicalAdmissionAdapter` preserves the Protocol/Canonical dependency boundary and causes decoder rollback on reject/uncertain outcomes.
- Live State is a pure immutable reducer with field provenance/freshness; missing HP/AP/MP/cooldowns remain unknown rather than zero.
- R5.196 regression is preserved: same-fight absolute AP/MP evidence is not falsely invalidated merely by `TURN_STARTED`; turn end does invalidate turn-scoped resources.
- Ready evidence is fight-epoch scoped and fight/world geometry remains separated.
- Canonical and Live State have zero forbidden concrete-system imports under Q5.
- Historical P55–P59 synthetic journals remain regression fixtures and are not silently promoted into definitive authority.

## 12. M8/M9/M10 evidence summary

- Q6 receipt: `verification/Q6_planning_coordination_workflow_receipt.json` PASS.
- Q6 test total: 209 pytest cases + 329 generated subtests PASS / 0 FAIL / physical input count 0.
- Decision emits deterministic semantic `ActionPlan` objects only; no pixel/HWND/OS-input fields or APIs exist in `anka_decision`.
- Retained Decision regressions: P12 43/43, P14 20/20 + 10 subtests, P15 20/20 + 16, P16 29/29 + 6.
- Coordination independently proves required-member fight/map/epoch coherence, Join→Placement→Ready causality and coherent turn ownership.
- An exhaustive generated oracle covers barrier/owner combinations and one-account health/gap faults; it found and permanently regressed an early Ready-without-Placement defect.
- Turn permits now carry both party-generation and permit-generation; explicit coordinator lifetime invalidation makes prior permits structurally stale.
- Workflow owns mission phases, semantic watchdogs, bounded recovery, idempotent counters, stop policies and resume rules. Fight end never implies victory.
- Uncertain/terminal-unresolved action side effects block Workflow rather than triggering blind retry/fallback End Turn.
- User capture schema now documents the parser-supported interface/duration/raw-evidence fields.
- Historical Sufokia route asset is exact-hash provenance-bound to the frozen R5.198 reference.
- Current Windows/current-client/live-action acceptance remains explicitly outside Q6.

## 13. M11 evidence summary

- Q7 receipt: `verification/Q7_execution_safety_receipt.json` PASS.
- Q7 regression total: 143 pytest cases + 75 subtests PASS / 0 FAIL / physical input count 0.
- `anka_execution` is the sole physical-input/settlement owner; no other system contains an OS-input implementation.
- Durable action lifecycle separates PREPARED, SEND_STARTED, PENDING/CONFIRMED_UNSETTLED, UNCERTAIN and terminal settlement states.
- Restart after `SEND_STARTED` is conservatively uncertain and never blindly retried; duplicate semantic ActionKeys are fenced.
- Final admission rechecks state, client generation, focus/geometry/projection, loadout, Kernel legality, Coordination permit and unresolved side effects under the host-wide input lease.
- The Windows input driver is present only as a disabled implementation and is not constructed by normal composition; Q12 is required before any real action scope.

## 14. M12_006 / current offline release evidence summary

- M12_006 retains the M12_005 observer-isolation regressions and extends them with bounded flight-recorder, crash-recovery, forensic-correlation, phase-authority, and full-chain lifecycle hardening. Ordinary diagnostic sink failures never become gameplay authority.
- The architecture guard now rejects additional direct Win32 window-control primitives outside `anka_execution`: `SetForegroundWindow`, `SetActiveWindow`, `SetFocus`, `PostMessageW`, and `SendMessageW`.
- Current root handoff documentation is release-truth checked. Historical P-series documents may preserve obsolete behavior, but `README.md`, `IMPLEMENTATION_STATUS.md`, and `00_READ_FIRST_NEXT_CHAT.md` must describe the current release.
- Resumable verification fingerprints include those current handoff documents, preventing cached PASS reuse after release-truth changes.
- Fresh Q0-Q9 and M12 receipts have been regenerated on implementation source SHA-256 `9f7d27d098bf70bbddac38cbfaaf441c278001c0ebe92d23e9b58039dd846c56`. Current gate totals are Q4 **713 + 144 subtests**, Q5 **405 + 13**, Q6 **209 + 329**, Q7 **143 + 75**, Q8 **112 + 7**, Q9 **22 + 9**, and M12 **202 + 21**, all with zero physical OS input.
- M12 release-content attestation is now non-circular: the M12 receipt verifies a self-excluding release-selection model, while `RELEASE_MANIFEST.json` plus `tools/verify_release_offline.py` own the definitive post-receipt package hash.
- The final isolated whole-project verifier must run from a deleted/empty checkpoint after the final release manifest is written; its exact module/test total is intentionally not predeclared here, so documentation cannot create a circular verification dependency.
- `check` must pass on the final sealed tree. On this non-Windows environment, `start` is expected to fail closed with `START_WINDOWS_REQUIRED` / exit 40 and generate a verifiable incident bundle.
- Crash-recovered incidents self-verify before they are marked handled; known observer loss downgrades missing-edge conclusions to evidence-scoped candidates rather than proven first divergence.
- Long-run action indexes preserve high-risk/unresolved actions before recent normal actions, and READY reconstruction uses the latest same-fight attempt per account.
- This remains the maximum offline/zero-input confidence available here, **not** Q10-Q13 live acceptance.
