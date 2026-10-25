# 09 — Testing, Verification & Quality Gates

## 1. Verification philosophy

The purpose of testing is not to produce a high count. It is to falsify unsafe assumptions before another live run and to preserve every discovered failure family.

No single test type is sufficient.

---

## 2. Required test layers

### 2.1 Unit tests

Pure local logic: codecs, reducers, rules, classifiers, policy functions, calibration validation.

### 2.2 Contract tests

Producer/consumer meaning at every boundary. Test real serialized forms and invalid/missing values.

### 2.3 Architecture tests

Forbidden imports, cycles, private implementation access, one input driver/writer, composition bindings.

### 2.4 Integration tests

Adjacent real systems via public interfaces:

```text
Capture -> Protocol
Protocol -> Canonical
Canonical -> Live State
State/Kernel -> Decision
State/Coordination/Client/Kernel -> Execution
Coordination -> Workflow
Execution outcome -> Workflow
```

### 2.5 Replay/regression tests

Historical raw/journal/diagnostic/derived fixtures with evidence-class labels.

### 2.6 Fault injection

Crashes, storage errors, gaps, delays, duplicates, focus changes, unsupported builds, queue overload.

### 2.7 Stateful/model-based tests

Generate sequences of Ready/turn/action/reconnect/recovery transitions and assert invariants. Record/shrink failing sequence where practical.

### 2.8 Zero-input systemic tests

Run the complete production logic with fake driver and synthetic/captured evidence. Assert physical input count.

### 2.9 Packaging/Windows tests

Clean extraction/setup/start, resource discovery, bridge/process/window behavior.

### 2.10 Bounded live acceptance

Explicit operator-approved tests on exact current build; separate evidence/status.

---

## 3. Independent oracle requirement

A critical test must not obtain its expected answer from the same production implementation under test.

Examples:

- Kernel geometry: hand-authored cases/independent expected cells;
- Protocol: raw evidence + independently established semantic values;
- State: hand-written event sequences and expected snapshots;
- Coordination: independently specified partial-order/turn constraints;
- Input: fake driver asserts call count/order;
- Crash recovery: inspect actual temporary DB/ledger after fault injection;
- diagnostics: manually authored expected first divergence.

---

## 4. Historical mandatory regressions

See `appendices/A_HISTORICAL_FAILURES.md`. At minimum include:

- R5.142 action codec/quarantine/liveness;
- R5.151 delayed confirmation/global disarm;
- R5.195 placement/static geometry;
- R5.196 resource freshness/turn handoff;
- R5.197 process ownership lesson adapted to current helpers;
- R5.198 exact opaque protocol drift after settled cast;
- Ready/no first turn;
- ENU does not join;
- End Turn does not hand off;
- wrong/nonwalkable cell target;
- 3 PM route click when 2 PM available;
- focus lost before action;
- no-action/stall diagnostics.

A derived fixture is labeled `DERIVED_REGRESSION`, not primary raw evidence.

---

## 5. Safety mutation tests

Deliberately break a critical invariant in a test-only mutant and prove the suite fails, for example:

- remove latest-state Execution recheck;
- map UNKNOWN AP to 0/known;
- permit second send after `MAY_HAVE_SENT`;
- accept old fight permit after generation change;
- let Protocol ignore mutated opaque fingerprint;
- let Decision repeat quarantined ActionKey;
- mark Observer heuristic as authoritative.

This checks that tests can actually detect dangerous regressions.

---

## 6. Crash-cut matrix

### Canonical

Inject failure:

- before transaction;
- mid-event insert;
- checkpoint write;
- commit call/ambiguous result;
- after DB commit before in-memory publish.

Expected: replay produces one durable truth; no duplicate event/state advance.

### Execution

Inject:

- before durable prepare;
- after prepare/before possible send;
- during send boundary;
- after driver acceptance/before server proof;
- after server outcome commit/before Workflow receives it.

Expected: no duplicate physical action; correct `NOT_SENT`/`UNCERTAIN`/settled recovery.

---

## 7. Quality gate ladder

| Gate | Meaning |
|---|---|
| Q0 Baseline | source/assets/evidence frozen and hashed |
| Q1 Architecture | dependency/authority rules enforced |
| Q2 Contracts | public schemas/producer-consumer semantics verified |
| Q3 Kernel/data | required mechanics and data scope verified |
| Q4 Capture/Protocol | exact stream and semantic adapter evidence verified |
| Q5 Canonical/State | durable/replay/freshness consistency verified |
| Q6 Planning/Coordination/Workflow | legal deterministic/bounded lifecycle behavior verified |
| Q7 Execution Safety | latest-state/identity/input/outcome crash tests verified |
| Q8 Diagnostics | deliberately injected failures correctly explained/gaps reported |
| Q9 Zero-input integration | full CRA+ENU lifecycle simulation; no OS input |
| Q10 Packaging/Windows | clean setup/start and host identity/projection verified |
| Q11 Observe-only current build | real acquisition/state with input disabled |
| Q12 Action scopes | bounded current-build actions accepted individually |
| Q13 Live mission | complete bounded CRA+ENU mission lifecycle accepted |

Do not skip directly from unit tests to live action.

---

## 8. Verification receipt

Every gate/release emits machine-readable receipt:

```text
source/release hash
config schema/effective config hash
Python/dependency hashes
adapter/build hash
Kernel/data hashes
calibration/profile hashes
fixture/test manifest hash
test counts: pass/fail/skip/not-run/missing-evidence
environment identity
duration
physical-input count/state
known limitations
artifact paths/checksums
```

Cached PASS is invalid if an input hash changes.

---

## 9. Status discipline

Never use “100% ready” from arbitrary scoring. Use explicit statuses from README.

`SKIP`, `NOT_RUN`, and `MISSING_EVIDENCE` are not PASS.

A tool named `READY` must clarify whether it means structural packaging, replay semantics, observe-only, or live action readiness.

---

## 10. Live acceptance sequence

After all offline/Windows gates:

1. current-build observe-only, both accounts;
2. verify world identity/resources/positions/party binding;
3. controlled join/placement/Ready;
4. prove first turn owner;
5. one minimal CRA action and settlement;
6. CRA End Turn and authoritative ENU owner;
7. one ENU action and settlement;
8. continue bounded fight;
9. fight end;
10. world re-entry;
11. mission counter/route resumes;
12. incident bundle on any first failure before changing code.

Stop at the first unproven boundary; do not patch multiple downstream systems based on symptoms.

---

## 11. Performance verification

Measure before setting thresholds. Test at least:

- 2-account target;
- simulated higher account counts;
- capture backlog/overflow;
- decoder throughput;
- Canonical commit contention;
- decision latency;
- input arbiter wait;
- observer overload/export;
- memory/disk retention.

Eight-account capability remains `NOT_ACCEPTED` until measured/verified on suitable host/client setup.

---

## 12. Release gate rule

No release is “final” because source compiles. The exact ZIP must be extracted and verified as delivered. Packaging/resource paths are part of functionality.

