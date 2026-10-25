# 05 — Protocol Evolution & Biweekly Upgrade Process

## 1. Operational assumption

Dofus protocol details may change frequently (planning assumption: roughly every two weeks). Protocol maintenance is therefore a normal product lifecycle, not an emergency patch path.

The target promise is conditional and precise:

> **If the game semantics required by ANKA are unchanged, a wire-only protocol update should normally be integrated by replacing/adding a version-scoped Protocol adapter, evidence and release metadata without modifying unrelated systems.**

No architecture can safely promise automatic compatibility with genuinely new rules/semantics or missing evidence.

---

## 2. Four change classes

### A — Wire-only equivalent change

Examples: renamed/obfuscated field, changed framing/layout, same semantic value.  
**Expected change:** adapter + evidence/manifests only.

### B — Optional semantic extension

Canonical vocabulary can already represent it or consumers do not require it.  
**Expected change:** adapter; optional Canonical additive schema if truly useful and backward compatible.

### C — New required game semantic/rule

Old Canonical/Kernel cannot represent/validate it.  
**Expected change:** explicit contract/Kernel/consumer design change + new tests/ADR. Never hide this inside adapter-only code.

### D — Insufficient/ambiguous evidence

Unknown critical traffic, unsupported build, lost stream continuity, unverified identity.  
**Expected result:** observation/disarm for affected capabilities; collect evidence. No guessing.

---

## 3. Required version tuple

Every active stream/run pins:

```text
observed_client_build
adapter_release_id/hash
canonical_schema_version
game_data_revision
kernel_ruleset_revision
required capability set
certified scenario manifest
```

Build detection itself is evidence. Prefix/nearest-version matching is not safe default behavior.

---

## 4. Adapter lifecycle

```text
STAGED
 -> STRUCTURALLY_VALID
 -> REPLAY_CERTIFIED
 -> OBSERVATION_CERTIFIED
 -> ACTION_SCOPED_CERTIFIED
 -> ACTIVE
```

A release may be `QUARANTINED` from any pre-active/active state. `RETIRED` is explicit.

`ACTION_SCOPED_CERTIFIED` names exactly which action/scenario capabilities are proven; it is not blanket live certification.

---

## 5. Required upgrade workflow

| Phase | Work | Exit evidence |
|---|---|---|
| U0 Fingerprint | Record exact new build, old adapter/release, capture/client identities | build/evidence manifest |
| U1 Collect | Controlled world/placement/CRA+ENU/fight-end evidence + independent oracles | evidence inventory/hashes/gaps |
| U2 Diff | Run old decoder offline, classify raw/wire/semantic changes | impact report by Canonical field/consumer/action |
| U3 Implement | New version-scoped adapter only | manifest, no forbidden imports |
| U4 Structural | SDK/import/schema/build/hash validation | STRUCTURALLY_VALID |
| U5 Semantic replay | Canonical/state/oracle comparison | mandatory semantic fields/scenarios pass |
| U6 Fault/mutation | unknown/changed bytes, missing fields, wrong direction, gaps, reconnect | no false commits/unsafe action |
| U7 Observe-only | Real capture/current client, physical input disabled | stable build/identity/state health |
| U8 Bounded actions | Explicit authorization for representative action scope | cast/settlement/handoff/reentry evidence as applicable |
| U9 Promote | disarmed safe boundary, no unresolved action, fresh stream/context | atomic selected adapter tuple |
| U10 Watch/rollback | early-run drift monitoring | active or quarantined with incident evidence |

---

## 6. Certification matrix

Required semantic areas include:

- world/map identity and local actor;
- group/monster information needed by route selection;
- fight identity/team/actors;
- actor cell/position;
- HP/AP/MP resources required by policies;
- current turn owner/round/lifecycle;
- spell/loadout/cooldown/per-target facts required for enabled casts;
- placement/Ready/join;
- action confirmation/settlement evidence;
- fight end and world re-entry;
- CRA/ENU same-fight coherence.

A 99% aggregate decode rate cannot authorize an action if the missing 1% contains turn ownership.

---

## 7. Candidate release evidence package

Recommended shape:

```text
protocol_evidence/<adapter_release_id>/
  manifest.json
  provenance.json
  wire_samples/
  expected_canonical.jsonl
  expected_state.jsonl
  scenario_matrix.json
  drift_diff.json
  action_trace.jsonl              # when safely available
  certification_report.json
  review.md
```

Manifests record hashes and evidence class. Raw/private PCAP can remain outside the distributable runtime while fixture excerpts/hashes prove provenance.

---

## 8. Consumer-driven compatibility

For every Canonical semantic consumed by Live State/Coordination/Decision/Execution/Workflow, Protocol certification asks:

- Is the field/event produced under the new build?
- Is actor/fight/turn scope correct?
- Is the value equivalent to the stable contract?
- Is absence meaningful or merely unobserved?
- Is the event ordering/decoder context correctly reproduced?
- Which action becomes unsafe if this proof is missing?

This is stronger than “decoder didn't crash.”

---

## 9. Exact opaque traffic rule

The R5.198 pattern remains useful:

- exact observed direction;
- exact length;
- exact hash/content fingerprint;
- zero Canonical state mutation;
- no invented semantic meaning;
- changed variant remains unknown.

Do not generalize an exact known opaque instance into “ignore all messages with this name.”

---

## 10. Promotion and rollback

Never hot-swap mutable decoder context mid-fight.

Promotion sequence:

1. disarm physical input;
2. reconcile/quarantine unresolved sends;
3. close/fence current stream generation;
4. atomically select certified adapter tuple;
5. start a fresh connection/decoder generation or explicitly supported bootstrap;
6. re-establish live truth before action permission.

Rollback means returning to a certified adapter **compatible with the observed client build**. If the new client no longer speaks the old format, safe rollback may mean stop/disarm until a valid adapter is available—not decoding new bytes with the old adapter.

---

## 11. Mandatory falsification tests

- rename/change a required wire field;
- one-byte mutation of certified opaque payload;
- reuse same raw ID for different semantic in another version;
- unchanged build string but changed payload schema;
- missing turn-ended/new-owner event;
- duplicate/reordered frames;
- lost TCP segment;
- decoder exception after context update;
- Canonical commit failure -> decoder rollback;
- new adapter tries to import old adapter internals;
- staged candidate exists but must not become active;
- active switch attempted with unresolved `MAY_HAVE_SENT` action;
- old adapter replay after adding new adapter;
- current-build negative-absence claim without current-build evidence.

---

## 12. Protocol completion definition

A wire-equivalent update is successfully isolated when:

- downstream stable source hashes remain unchanged for Kernel/State/Decision/Execution/Coordination/Workflow except explicit generated manifests;
- Canonical/state semantic oracle matches expected current-build behavior;
- old adapter regressions still pass;
- no unknown critical capability remains for enabled actions;
- zero-input real observation is accepted;
- bounded action scopes have explicit current-build evidence;
- promotion/rollback path is tested;
- incident diagnostics can identify first protocol divergence.

