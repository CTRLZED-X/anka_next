# 01 — Product Requirements & Engineering Principles

## 1. Product mission

ANKA_NEXT is a local Windows automation platform for controlling one or more Dofus clients from **verified live game state**, deterministic game rules, replaceable planning logic, tightly controlled physical input, and evidence-based outcome verification.

The first fully accepted production configuration is:

- CRA leader;
- ENU follower;
- one shared mission/run;
- automatic game-client/window association;
- world route / encounter selection;
- join, placement, Ready, first-turn, combat, handoff, fight end and world re-entry;
- headless terminal operation;
- one user JSON file;
- no browser dashboard;
- automatic local forensic evidence on setup/start/runtime failure.

Longer-term architecture must support additional accounts/classes without rewriting the foundation. However, only configurations with explicit evidence may be declared accepted.

---

## 2. Primary product goals

### RQ-PROD-001 — Authoritative observation before action

The system MUST base safety-critical actions on authoritative, correctly attributed, sufficiently fresh evidence. It MUST distinguish:

- observed external evidence;
- committed canonical truth;
- derived state;
- deterministic kernel result;
- heuristic planning result;
- physical input attempt;
- authoritative game outcome.

No layer may silently treat one category as another.

### RQ-PROD-002 — Multi-account coordination

The platform MUST coordinate at least CRA + ENU with explicit account identity, same-fight proof, placement/Ready barriers, turn ownership, per-account state cursors, and bounded recovery.

### RQ-PROD-003 — Reusable deterministic Kernel

Game rules/mechanics MUST be owned by `anka_game_kernel`, isolated from networking, Windows input, workflow, and protocol dialects. Existing proven kernel assets from R5.198 SHOULD be preserved rather than rewritten.

### RQ-PROD-004 — Replaceable protocol adapters

Protocol-specific details MUST be isolated. A wire-only game build change SHOULD normally require a new/updated adapter and evidence package, not changes to Kernel, Decision, Execution, Coordination, or Workflow.

### RQ-PROD-005 — One physical input authority

All real mouse/keyboard input MUST pass through `anka_execution`. No Decision, Workflow, Coordination, Client, diagnostics, watchdog, or UI helper may bypass it.

### RQ-PROD-006 — Evidence-based settlement

A successful Windows input API call MUST NOT be treated as a successful game action. Action send state and game-outcome settlement are separate.

### RQ-PROD-007 — Fault containment and recovery

Failures SHOULD be contained to the narrowest safe scope. Global disarm is justified only when required shared invariants are no longer provable.

### RQ-PROD-008 — Permanent regression conversion

Every confirmed important runtime failure SHOULD become a deterministic test/fixture so the same failure family does not require another live discovery cycle.

### RQ-PROD-009 — First-divergence diagnostics

On error/stall, the system SHOULD report the earliest evidence-supported boundary where expected progress diverged from reality, not merely the final timeout/symptom.

### RQ-PROD-010 — Minimal operator UX

Normal operator workflow MUST use only:

- `setup.bat`;
- `start.bat`;
- `config/user.json`.

No extra user-facing debug/test/replay/calibration BAT scripts are part of the default product. Developer tools may exist as Python modules. Calibration repair may be an internal/CLI workflow invoked through the application, not another top-level BAT launcher.

---

## 3. User configuration requirements

### RQ-CFG-001 — One normally edited file

`config/user.json` is the only file an ordinary operator is expected to edit. Internal technical configuration remains versioned release assets/defaults.

### RQ-CFG-002 — Strict schema

The file MUST reject:

- unknown keys;
- duplicate JSON keys;
- missing required fields;
- invalid types;
- min/max contradictions;
- impossible attempt/win budgets;
- duplicate player identities;
- conflicting roles;
- unsupported route/policy identifiers.

### RQ-CFG-003 — Example user intent

```json
{
  "schema_version": 1,
  "players": [
    {"name": "Curseni", "role": "leader"},
    {"name": "Sosoking", "role": "follower"}
  ],
  "mission": {
    "route_id": "sufokia_direction_cycle",
    "min_monsters": 6,
    "max_monsters": 8,
    "target_wins": 5,
    "max_attempts": 10
  }
}
```

Values are illustrative. The implementation MUST freeze an **effective configuration snapshot** with its hash for every run.

### RQ-CFG-004 — Explicit precedence

The new system MUST have one documented precedence rule:

1. immutable shipped defaults;
2. selected internal class/route/profile assets;
3. validated `config/user.json` operator choices;
4. temporary developer test overrides only in explicit non-production modes.

Legacy conflicting `config.yaml`/mission defaults MUST NOT be copied as hidden precedence.

---

## 4. Automatic identity requirements

### RQ-ID-001 — Names are hints, not proof

A configured player name identifies the desired character. It does not by itself prove:

- class/breed;
- process;
- HWND/window;
- socket flow;
- current fight actor;
- spell loadout;
- calibration generation.

### RQ-ID-002 — Attestation tuple

Before physical input, Client/Coordination SHOULD be able to establish, at minimum where supported:

```text
configured_player_name
character/account identity
live class/breed
process PID + creation generation
HWND/window identity
client build
capture/flow association
bridge/projection generation
calibration profile + size/DPI
fight actor identity (when in combat)
spell/loadout proof required for requested action
```

Ambiguity yields `IDENTITY_NOT_VERIFIED` / `LOADOUT_UNKNOWN`, not a guessed click.

### RQ-ID-003 — Revalidation triggers

Identity/projection proof MUST be invalidated or rechecked after relevant changes such as process restart, HWND change, reconnect, map/scene change, display/DPI/viewport change, bridge restart, calibration revision, fight generation, or target-account mismatch.

---

## 5. Headless operation requirements

### RQ-OPS-001 — No dashboard

The final product MUST NOT depend on a dashboard, browser UI, or Script Studio for mission execution or debugging.

### RQ-OPS-002 — Terminal status

`start.bat` MUST display concise status sufficient for the operator:

```text
ANKA_STATUS=RUNNING | BLOCKED | STOPPED | FAILED
RUN_ID=...
ACTIVE_ADAPTER=...
CRA=READY/BLOCKED/UNKNOWN
ENU=READY/BLOCKED/UNKNOWN
PHASE=...
WAIT_REASON=...
INCIDENT_BUNDLE=... (when relevant)
```

The underlying diagnostics remain structured files, not terminal-only text.

### RQ-OPS-003 — Safe shutdown

Ctrl+C/application shutdown MUST:

- revoke input authority;
- stop new plans/actions;
- identify unresolved action attempts;
- close capture/worker resources;
- commit/flush required durable state;
- record stop reason;
- never reinterpret an unresolved external side effect as NOT_SENT solely because the process is exiting.

---

## 6. Reliability requirements

### RQ-REL-001 — Fail closed on critical unknowns

If required identity, state, protocol meaning, window target, action settlement, or turn ownership is not proven, affected physical input MUST be denied.

### RQ-REL-002 — Avoid unnecessary global failure

A non-critical observer/export failure, unrelated unknown wire, or recoverable delayed confirmation SHOULD NOT globally disable unrelated proven-safe behavior.

### RQ-REL-003 — No blind retries after possible send

If a physical action may have been delivered, the system MUST reconcile authoritative state before another semantically duplicate action is allowed.

### RQ-REL-004 — One writer / authority

There MUST be one authoritative writer/owner for:

- Canonical event sequence;
- action attempt/input lease;
- workflow/run phase;
- party/turn permits;
- process/run generation.

### RQ-REL-005 — Progress must be semantic

Heartbeats, log traffic, repeated Ready clicks, repeated identical decisions, or dashboard/observer activity do not count as gameplay progress. Progress deadlines are reset only by defined semantic transitions.

### RQ-REL-006 — Recovery is bounded

Every wait/recovery loop MUST have:

- owner;
- expected evidence;
- monotonic deadline/budget;
- progress transition;
- terminal disposition;
- diagnostics.

No infinite silent loops.

---

## 7. Protocol-change resilience requirements

### RQ-PROTO-001 — Explicit version dimensions

Track independently:

- observed client build;
- adapter release ID/hash;
- canonical contract version;
- game-data revision;
- kernel ruleset revision;
- calibration/projection generation.

Do not overload one `version` field.

### RQ-PROTO-002 — New build defaults to unqualified

A new/unknown client build MUST NOT inherit full action permission from a numerically similar old adapter without explicit evidence.

### RQ-PROTO-003 — Adapter-only target for wire-equivalent changes

When semantics are unchanged, the maintenance objective is to change only:

- `anka_protocol/adapters/<build>/`;
- associated evidence/fixtures/manifests;
- release selection/certification metadata.

Changes outside this boundary require justification.

### RQ-PROTO-004 — Capability-scoped readiness

A protocol release MUST report readiness by required semantic capability/action, not only one aggregate percentage or Boolean.

### RQ-PROTO-005 — Unknown traffic remains explicit

An exact known opaque fingerprint MAY be admitted as nonmutating if supported by evidence. A changed payload/direction/length/hash remains unknown until qualified.

---

## 8. Diagnostics requirements

### RQ-DIAG-001 — Earliest possible bootstrap recording

`setup.bat` and `start.bat` MUST produce diagnostic stage evidence even before third-party Python dependencies can import.

### RQ-DIAG-002 — Typed structured evidence

Critical transitions MUST use versioned structured events containing run/account/fight/action correlation IDs, owner/boundary, severity, causal references, and explicit physical-input state.

### RQ-DIAG-003 — Bounded overhead

Diagnostics MUST use bounded queues/storage. Observer overload may degrade diagnostics and MUST report dropped evidence; it may not silently block/alter gameplay authority.

### RQ-DIAG-004 — GPT-friendly incident archive

A significant failure SHOULD automatically create one sanitized local ZIP with:

- summary;
- manifest/checksums;
- relevant timeline;
- first-divergence analysis;
- evidence gaps;
- build/config/adapter/rulepack identities;
- canonical/action references;
- recovery history;
- suggested next targeted verification.

No automatic upload.

### RQ-DIAG-005 — Honest uncertainty

Root-cause result is `UNDETERMINED` or `MULTIPLE_PLAUSIBLE` when evidence cannot distinguish causes.

---

## 9. Testing requirements

### RQ-TEST-001 — Each system needs five proof layers

A system is not complete without:

1. unit tests;
2. producer/consumer contract tests;
3. adversarial/fault tests;
4. adjacent-system integration tests;
5. relevant full-stack replay/no-input scenarios.

Stateful/durable systems additionally require crash/restart tests.

### RQ-TEST-002 — Independent oracle

Expected results for critical safety tests MUST not be generated solely by the same production algorithm under test.

### RQ-TEST-003 — Historical incident regressions

At minimum, preserve tests for the historical families documented around R5.142, R5.151, R5.195, R5.196, R5.197, and R5.198, plus recurring Ready/handoff/focus/cell failures.

### RQ-TEST-004 — Zero-input systemic suite

The full software chain MUST be testable with a fake/no-input driver. Offline/systemic tests MUST be able to prove `physical_input_emitted=false` where expected.

### RQ-TEST-005 — Live acceptance is separate

Live Windows/Dofus acceptance is never inferred from offline tests. It has independent evidence/status.

---

## 10. Maintainability requirements

### RQ-MAINT-001 — Stable public APIs

Each top-level system exposes a small public API/ports. Other systems MUST NOT import its private implementation.

### RQ-MAINT-002 — Architecture checks in CI/verification

Tests MUST enforce legal dependency direction and fail on forbidden cross-imports/dynamic bypasses.

### RQ-MAINT-003 — Reuse proven code

Do not rewrite the game Kernel, calibrated coordinates, protocol fixtures, reducer semantics, or settlement safety merely to obtain new names/folders. Reuse with provenance and tests.

### RQ-MAINT-004 — No generic “integration” dumping ground

Adapters/translators must have a clear owner/port. `anka_app` wires implementations but contains no hidden game/business rules.

### RQ-MAINT-005 — Explicit deprecation during migration

Old and new implementations MUST NOT both own the same live state/input/mission authority. Compatibility facades MAY forward old APIs temporarily, but there is one active implementation.

---

## 11. Performance and scalability requirements

- Critical queues MUST be bounded and observable.
- No silent packet/event loss for gameplay-relevant streams.
- Decision and admission paths MUST not scan the full historical SQLite journal.
- Diagnostics/export MUST not block input/canonical critical sections.
- Performance thresholds MUST be established from measured baselines, not invented numbers.
- The architecture SHOULD support eventual 8-account operation, but acceptance MUST be evidence-based through load scenarios and Windows tests.

Metrics to measure include capture backlog, decode lag, Canonical commit latency, state publication lag, decision time, input lease wait, action settlement time, coordination handoff latency, SQLite lock/commit time, observer queue loss, CPU/RAM per account and incident-export duration.

---

## 12. Security/privacy requirements

- No secret/token/password dumping into diagnostics.
- Share bundles MUST be sanitized again before export.
- Raw PCAP/screenshots/full dumps are opt-in separate artifacts, not default GPT attachments.
- Untrusted packet/log strings must be escaped/truncated before report rendering.
- Zip read/write must prevent path traversal.
- No external telemetry/upload by default.
- Local debug artifacts use user permissions and retention limits.

---

## 13. Non-goals and rejected ideas

The following are deliberately **not** target requirements:

- 11 independent network microservices;
- Kafka/service-bus infrastructure for a local automation process;
- a browser dashboard;
- an autonomous LLM directly controlling the game;
- automatic protocol semantic guessing;
- automatic retry of ambiguous physical input;
- blanket ignore-lists for unknown packets;
- full-packet/full-mouse permanent logging;
- “one readiness percentage” replacing explicit proof states;
- rewriting the Kernel for naming uniformity;
- treating simulation as proof of Windows/Dofus behavior;
- creating extra BAT files because a developer tool exists.

---

## 14. Quality philosophy

The project optimizes for **falsifiable correctness**, not appearance of sophistication. The preferred change is the smallest change that:

- eliminates a high-impact failure class;
- clarifies authority;
- reduces future coupling;
- makes failure evidence better;
- adds permanent regression protection;
- can be verified independently.

Architectural complexity must earn its cost through measurable safety, reliability, maintainability, or diagnostic value.

