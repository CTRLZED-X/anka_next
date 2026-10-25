# 07 — Diagnostics, Observability & GPT-Friendly Forensics

## 1. Goal

Eliminate the recurring workflow where a live run fails, the user manually gathers partial files, a local symptom is patched, and the next run reveals another hidden boundary failure.

Diagnostics cannot eliminate all bugs. It can make the system **causally inspectable**, preserve enough evidence for offline reproduction, and turn confirmed incidents into permanent regression tests.

---

## 2. Architecture decision

Use:

- one runtime package: `anka_observability`;
- a tiny stdlib/batch bootstrap recorder in `anka_app/bootstrap` for failures before dependencies import;
- authoritative Canonical/Execution ledgers owned by those systems;
- Verification Lab offline tools/tests.

Do **not** create a separate diagnostics microservice or a second competing gameplay-state database.

---

## 3. Record transitions, not “everything”

Always record important boundaries:

- setup/start stage transitions;
- effective release/config identities;
- client/window/class attestation;
- capture flow start/gap/reconnect;
- protocol adapter/build and unknown messages;
- Canonical admission/commit failures/cursors;
- critical state field changes/freshness conflicts;
- party barriers and turn ownership;
- Decision frame/result/exclusions;
- Execution admission and physical attempt states;
- action outcome/settlement;
- Workflow phase/progress/recovery;
- observer/storage health;
- stop/crash/unclean recovery.

Do not permanently log every unchanged snapshot, full raw packet stream, or every pointer interpolation by default.

---

## 4. Bootstrap diagnostics

`setup.bat` and `start.bat` must write a minimal invocation/stage record before relying on the configured Python environment.

Recommended files:

```text
runtime/bootstrap/<invocation_id>/
  bootstrap.json
  stage.json
  console.log
```

Capture:

- operation (`setup`/`start`);
- invocation ID;
- start/end timestamps;
- cwd/release path;
- stage name;
- Python discovery/version if available;
- safe command identity;
- return code;
- bounded sanitized stderr/stdout tail;
- fallback diagnostic path.

Do not dump arbitrary environment variables or commands containing secrets.

---

## 5. Runtime diagnostic event

Illustrative schema:

```json
{
  "schema_version": 1,
  "event_id": "...",
  "event_name": "execution.preflight_rejected",
  "severity": "ERROR",
  "occurred_utc": "...",
  "monotonic_ns": 0,
  "producer_instance": "...",
  "producer_seq": 42,
  "run_id": "...",
  "account_id": "...",
  "client_generation": "...",
  "fight_epoch": 4,
  "turn_epoch": 7,
  "canonical_cursor": 512,
  "trace_id": "...",
  "action_id": "...",
  "attempt_id": "...",
  "owner_system": "anka_execution",
  "boundary": "pre_input_authorization",
  "failure_code": "WINDOW_FOCUS_MISMATCH",
  "physical_input_state": "NOT_SENT",
  "evidence_refs": ["..."],
  "payload": {}
}
```

Wall clocks are human context. Ordering across independent processes/accounts uses per-producer sequence, causal links and Canonical cursors—not assumed clock synchronization.

---

## 6. Correlation model

The diagnostic chain should connect:

```text
invocation
 -> run
 -> account/client generation
 -> connection/flow
 -> canonical cursor/snapshot
 -> workflow phase
 -> decision plan / ActionKey
 -> execution action/attempt/input lease
 -> protocol/canonical consequence
 -> settlement / coordination / next workflow transition
```

This lets a report distinguish:

- “AI chose no action”;
- “Execution rejected before input”;
- “Windows driver never sent input”;
- “input may have been sent but server proof is missing”;
- “server effect committed but Workflow missed transition.”

---

## 7. First-divergence analysis

For each operation define expected next boundaries. Diagnosis finds the earliest missing/contradictory edge.

Example: Ready flow

```text
READY_REQUESTED
 -> EXECUTION_ADMITTED
 -> READY_INPUT_SENT/MAY_HAVE_SENT
 -> SERVER_READY_OBSERVED
 -> PARTY_READY_BARRIER_SATISFIED
 -> FIGHT_ACTIVE/TURN_OWNER_PROVED
 -> DECISION_FRAME_CREATED
```

If “both windows look Ready” but nothing happens, the report names the first evidence-supported break rather than “READY_STUCK.”

### Finding structure

```text
finding_id
failure_code
first_divergent_boundary
suspected_owner
confidence = HIGH | MEDIUM | LOW | UNDETERMINED
supporting_evidence_ids[]
contradicting_evidence_ids[]
missing_evidence[]
control_state
recommended_next_test
```

Multiple plausible causes are preserved when not distinguishable.

---

## 8. Flight recorder and retention

Use a bounded per-run/per-account ring for recent context plus persistent priority events.

- Critical authoritative evidence remains in Canonical/Execution owner ledgers.
- Diagnostic queue drops low-priority repetitive events first under pressure.
- Dropped-event counters appear in bundle completeness.
- Incident trigger can pin relevant pre-failure window.
- Raw heavy capture is opt-in/time-bounded.

Retention defaults are shipped internal settings and should be tuned from real measurements.

---

## 9. Incident bundle

Default sanitized bundle:

```text
GPT_READ_FIRST.md
manifest.json
run_manifest.json
analysis/
  diagnosis.json
  boundary_graph.json
  evidence_gaps.json
  historical_matches.json
  next_verification.json
logs/
  bootstrap_summary.json
  relevant_timeline.jsonl
  relevant_errors.jsonl
snapshots/
  party_state.json
  actor_resources.json
  action_attempts.jsonl
  canonical_cursor.json
  window_bridge_attestation.json
metadata/
  release_versions.json
  effective_config_sanitized.json
  capture_protocol_summary.json
  artifact_integrity.json
```

### `GPT_READ_FIRST.md`

Must state:

- result/control state;
- first divergence + evidence ref;
- attempted operation;
- proven facts;
- expected-but-missing evidence;
- physical input state;
- suspected owner/confidence;
- evidence gaps/collector failures;
- recovery attempts/outcome;
- historical regression matches (similarity, not automatic same cause);
- one next targeted test/evidence request;
- privacy/redaction summary.

---

## 10. Completeness matrix

Every incident lists required sections as:

```text
PRESENT
PRESENT_STALE
PARTIAL
MISSING
NOT_APPLICABLE
EXPORT_FAILED
```

Never report a blanket `bundle_complete=true` without section receipts.

---

## 11. Privacy/security

- allowlist exported fields;
- second sanitization pass before ZIP;
- pseudonymize names/local paths in share bundle when feasible;
- raw PCAP/screenshots/dumps excluded by default;
- no passwords/tokens/auth headers/environment secrets;
- cap arbitrary string lengths and escape control characters;
- prevent ZIP path traversal;
- validate artifact size/checksums/schema before export;
- local only; user explicitly shares file.

---

## 12. Observer failure behavior

Observer failure must be visible but non-authoritative.

- queue full -> drop/sample low priority, increment loss;
- diagnostic disk full -> `OBSERVABILITY_PARTIAL`; gameplay safety continues based on authoritative ledgers;
- authoritative action/canonical ledger unavailable -> safety owner may block because **that** is required truth, not because observer failed;
- exporter crash -> preserve minimal envelope and original application error;
- recursive logging avoided.

---

## 13. Historical incidents to recognize

Diagnostics should have explicit regression fixtures for:

- action contract malformed + same-frame replanning (R5.142 family);
- late confirmation amplified into global disarm (R5.151 family);
- stale static placement geometry (R5.195 family);
- wrong resource freshness floor (R5.196 family);
- stale process/listener ownership (R5.197 family; browser server itself is removed in target);
- new unknown protocol wire after settled CRA cast (R5.198 family);
- both Ready/no first turn;
- wrong focus/window;
- legal plan but non-walkable/invalid projected target;
- End Turn sent but no next owner;
- fight end/world re-entry stall.

---

## 14. Diagnostic acceptance tests

- missing Python / corrupt venv;
- invalid config before third-party import;
- dependency install failure;
- client identity ambiguity;
- capture gap;
- protocol unknown/mutation;
- Canonical commit ambiguity;
- stale resource evidence;
- repeated ActionKey loop mutation;
- wrong focus before DOWN;
- sent but unconfirmed action;
- observer queue overload;
- disk full/permission denied;
- partial/corrupted ZIP;
- nested secret/redaction test;
- deliberately ambiguous root causes -> `MULTIPLE_PLAUSIBLE`.

A diagnostic test passes only if the **expected first boundary and forbidden assertions** are checked.

---

## 15. No extra user BAT tools

There are no normal `debug.bat`, `doctor.bat`, `verify.bat` or `replay.bat` files in the final operator UX. Failures from `setup.bat`/`start.bat` generate diagnostics automatically.

Developer operations use Python modules/tools, e.g. conceptually:

```text
python -m anka_tools.verify
python -m anka_tools.diagnose <bundle>
python -m anka_tools.replay <case>
python -m anka_tools.protocol_qualify ...
```

Exact commands are implementation details and should stay out of normal operator instructions.

