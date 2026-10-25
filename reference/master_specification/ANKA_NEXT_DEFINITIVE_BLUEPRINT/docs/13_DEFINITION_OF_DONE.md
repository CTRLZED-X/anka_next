# 13 — Definition of Done

## 1. What “done” does NOT mean

Not sufficient:

- project imports;
- all folders exist;
- one fight succeeds;
- offline tests pass;
- adapter tool says READY;
- dashboard/terminal looks correct;
- “95% coverage”;
- no exception occurred;
- physical click returned successfully.

---

## 2. System-level Done

Each runtime system is complete only when:

- responsibility/public API documented;
- owned mutable state/authority identified;
- legal dependencies enforced;
- unit tests pass;
- producer/consumer contracts pass;
- malformed/unknown input tests pass;
- relevant fault/crash/restart tests pass;
- diagnostics events and deliberate failure explanation pass;
- adjacent integration passes;
- relevant full-stack zero-input replay passes;
- verification receipt tied to exact source/fixtures exists;
- known limitations are explicit.

Stateful/action systems have additional durable/crash requirements.

---

## 3. Protocol Adapter Done

An adapter is not Done until:

- exact supported build(s) identified by evidence;
- immutable code/evidence hashes;
- wire fixtures/provenance;
- semantic canonical oracle;
- field/capability matrix;
- unknown/malformed/mutation tests;
- reducer/state replay;
- historical adapter regressions;
- observe-only current-build acceptance;
- explicit action-scope live acceptance for enabled actions;
- safe promotion/rollback/quarantine;
- no undocumented downstream code changes for wire-only change.

---

## 4. Offline release Done

`OFFLINE_VERIFIED` requires:

- exact release manifest/hashes;
- architecture/contract gates;
- Kernel/data scoped verification;
- Capture/Protocol replay gates;
- Canonical/LiveState crash/replay gates;
- Decision/Coordination/Workflow scenarios;
- Execution fake-driver/fault gates;
- diagnostic sabotage/bundle gates;
- full zero-input CRA+ENU mission scenarios;
- packaging/resource tests that can run without game input;
- no hidden SKIP/NOT_RUN counted as PASS.

---

## 5. Windows startup Done

`WINDOWS_STARTUP_VERIFIED` requires clean release extraction and:

- setup succeeds/reports precise failure;
- Python/dependencies/resources coherent;
- Unity/native component as required installed/identified;
- start discovers target clients without killing unknown processes;
- strict config loads;
- process/window identity and calibration checks execute;
- no physical input until explicitly authorized readiness;
- Ctrl+C/shutdown safe;
- deliberate startup failure yields GPT incident bundle.

---

## 6. Observe-only Done

`OBSERVE_ONLY_ACCEPTED` on exact current build requires both CRA/ENU:

- client/build/adapter binding;
- capture continuity;
- world/fight identity;
- actor/class identity;
- HP/AP/MP/cell/turn fields required by enabled policy;
- join/Ready/placement/fight lifecycle observations;
- no unexplained critical unknown protocol traffic;
- Canonical/state consistency;
- party coherence;
- zero physical input from ANKA during test.

---

## 7. Action-scope Done

Each physical action category (`JOIN`, `READY`, `MOVE`, `CAST`, `END_TURN`, world transition) requires current-build proof of:

- semantic request/admission;
- correct actor/account/window;
- final state/Kernel/party/projection validation;
- actual input attempt classification;
- authoritative outcome evidence;
- no duplicate action on late/ambiguous evidence;
- failure diagnostics.

Scopes may be accepted separately.

---

## 8. Live mission Done

`LIVE_MISSION_ACCEPTED` requires a bounded real CRA+ENU run proving at least:

```text
world observation
 -> valid encounter/fight entry
 -> ENU joins same fight
 -> placement/Ready
 -> first turn proven
 -> CRA action settled
 -> CRA end-turn / ENU ownership proven
 -> ENU action settled
 -> subsequent legal turns/actions
 -> fight end outcome committed once
 -> world re-entry proven
 -> mission progress resumes/counter correct
 -> no duplicate input or unexplained critical evidence gap
```

Failure must produce a useful incident archive and acceptance stops at the first unproven boundary.

---

## 9. Full project Done

The ideal final ANKA_NEXT is finished when:

- all mandatory systems/contracts implemented under target boundaries;
- no legacy `anka_platform` dependency remains in production runtime;
- only setup/start user BATs remain;
- JSON/headless workflow covers full required mission;
- exact current supported client build(s) have adapter/action certification;
- CRA+ENU live mission accepted on delivered release;
- historical regression corpus protected;
- clean Windows packaging/setup reproducible;
- diagnostics reliably explains deliberately injected failures and real accepted-run faults;
- performance/resource behavior within measured supported targets;
- documentation/status/reuse/ADR manifests match implementation;
- known unsupported rules/builds/account counts/routes are explicit;
- future protocol update process is exercised at least once end-to-end without unrelated subsystem modifications for a wire-equivalent change.

No claim of “bug-free forever” is part of Done.

---

## 10. Evidence packet for final release

A final candidate stores:

```text
RELEASE_MANIFEST.json
IMPLEMENTATION_STATUS.md
REUSE_MANIFEST.json
verification/
  architecture.json
  contracts.json
  kernel_data.json
  protocol_certifications/
  crash_fault_matrix.json
  zero_input_systemic.json
  diagnostics.json
  windows_startup.json
  live_acceptance.json
known_limitations.md
```

Every file is tied to the exact release hash.

