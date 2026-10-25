# P47 — One-flow historical wire replay, evidence gaps, and offline preflight

**Source baseline:** full P46 archive. **Status:** implemented and focused offline verified, **NOT** current-client certified or live-action ready. **Date:** 2026-10-21.

## 1. Engineering motivation and the actual missing boundary

P45 and P46 separately decoded four lifecycle messages and selected combat messages, and P46 could audit a preselected list of successfully decoded observations. That approach left a significant integration blind spot: a caller could simply omit an unsupported `jsq`, an unknown obfuscated wire message, or a repeated source cursor, and then run a combined audit that reported an apparently coherent subset. In particular, the `P46` combined audit had no way to inspect *the wire messages that were not included in its observation list*.

P47 adds a **single bounded research replay over a complete caller-supplied sequence of wire observations**. It invokes the existing version-specific P45/P46 decoders internally and validates source identity and chronology **before** reducing the replay to historical observations. It preserves unknown and unsupported traffic in the output as evidence gaps, and it separately exposes the earliest gap and the first hard blocker. It never creates Canonical events or authorizes gameplay.

## 2. Files and responsibilities

- `src/anka_protocol/historical_stream_replay.py`: `replay_historical_server_stream(tuple[WireMessage,...],scope=LegacyFightScope(...))`; frozen `HistoricalStreamReplay` receipt. One historical 3.7.10.10 server-direction flow only, bounded to 4,096 messages / 16 MiB aggregate payloads / 1,024-byte flow keys. Requires caller-bound flow digest and generation, checks every packet/message-index source cursor for strict increase, decodes known lifecycle/combat families, accounts for unknown names/unsupported action types, runs P45, P46 and combined chronology audits.
- `src/anka_app/historical_stream_offline.py`: a tiny independent hand-written synthetic replay smoke for a clean, partial and duplicate-source flow. No real Windows/network driver or current client required.
- `src/anka_app/cli.py`: automatically runs the above smoke in existing setup/check preflight and records `protocol.historical_stream_replay_checked`; never changes the readiness or physical-action boundary.
- `tests/test_p47_historical_stream_replay.py`: 25 adversarial/positive tests.
- `tests/test_p47_historical_stream_setup_smoke.py`: 3 smoke/immutable receipt tests.

**No new runtime process, operator BAT launcher, dashboard or Canonical writer was introduced.** Existing Kernel, reference/calibration assets, historical adapter inventories, tactical decision/coordination/execution logic, and Windows input contracts remain unchanged.

## 3. Why the data has three different statuses

| Status | Meaning | Never means |
|---|---|---|
| `RESEARCH_REPLAY_ONLY` | All supplied messages in the selected flow are historically understood, source ordered, and chronology-audited | The capture is complete, the client/build is current, the actor is bound to a verified window, or the gameplay event is authoritative |
| `PARTIAL_EVIDENCE` | A required source/turn/field proof is missing, a new wire name appeared, or an unsupported `jsq` action was included | That unknown traffic is safe or irrelevant to current gameplay |
| `BLOCKED_EVIDENCE` | Invalid scope/direction/flow, duplicated source cursor, corruption, wrong chronology, invalid data/size budget | A new game input or a request to ignore data and continue |

Each report records counts, bounded distinct unknown names, research observations with source identities, audits, `first_issue`, and separately `blocking_issue`. This distinction prevents an early non-fatal unknown from obscuring a later hard flow mismatch. The report is immutable and explicitly fixes `canonical_commits=0`, `physical_input_sent=False`, `actionable=False`, `current_client_certified=False` and `source_completeness_verified=False`.

**Source completeness is unproven by design.** Packet numbers show an order among received messages; they do not certify that no TCP data was lost, that all account flows were captured, or that the server actually performed a successful spell. `LegacyFightScope` is caller-supplied offline evidence, not a Windows identity attestation. Current-build certification requires independent capture/actor/witness verification beyond these fixtures.

## 4. Failure scenarios covered

Synthetic fixtures demonstrate clean owner→cast→push→teleport→turn-end→result chronology; unknown wire between owner and cast; unsupported `jsq`; duplicate/reordered wire source even in otherwise ignored messages; same-packet increasing message indices; cross-flow and generation confusion; wrong direction/build/fight; missing actor turn; reactive cast by a different actor (research discrepancy, not false illegality); event after result; owner switch without end; round regression; malformed protobuf; invalid/malicious flow-key types and unicode; stream size/budget exhaustion; truncated evidence; ambiguous earliest soft anomaly followed by later hard blocker; explicit no-authority on every path.

The historical `jwp` only establishes a **result boundary**, not victory/defeat, reward allocation or world re-entry. The historical `jsq` cast record only establishes that an old server message was observed, not AP/MP settlement, damage, cooldown changes or action confirmation.

## 5. Verification performed and limitations

- New P47 tests: **28 passing unittest methods**, independently rerun after the final source changes.
- P45/P46/P47 focused decoder and audit set: **101 passing tests**.
- Earlier separate adjacent research suite: **94 passing tests** (P35/P36/P43/P47; overlaps the above).
- Broader late-module P41–P47 plus state/protocol/reference tests: **326 passing tests** in one process; a nonfatal `ConnectionResetError` was emitted by an existing mock Unity HTTP server worker during teardown. The test process exited 0; this warning was not falsely labeled an assertion failure.
- `python -m anka_app.cli check` and `setup`: **PASS**, 165 reused assets verified; architecture boundaries **PASS**, 13 packages/261 Python modules.
- `python -m anka_app.cli start`: expected `LIVE_RUNTIME_NOT_IMPLEMENTED`, exit **40**. Its generated incident ZIP passed `verify_incident`.
- The full 69-module regression inventory **was not completed**. Independently isolated modules and overlapping focused suites passed, but an attempted combined middle/tactical group timed out, with previously existing SQLite `ResourceWarning`s. An exit-0 subprocess without parsed test count is not treated as a complete test result. No 69/69 full-suite PASS is claimed. P46's 67/67 pass is previous-release evidence and cannot be substituted for a P47 full pass.
- Physical Windows/Npcap capture, Unity bridge build/install, exact-current-build protocol equivalence, authoritative Canonical admission, actual physical input, CRA/ENU handoff and live missions **remain unverified**.

## 6. Next work worth doing

**Priority:** obtain an authorized capture of the **actual current client build** plus independently observed CRA/ENU actor, position, AP/MP/HP, spell effect and fight-result ground truth. Bind packet source and flow generation to the exact Windows client, implement/qualify the current adapter, then test an authoritative Canonical admission contract behind the existing fail-closed gate. Historical stream replay is a useful diagnostic/qualification substrate, but a synthetic replay cannot replace that evidence. Until then, focus on source-backed, independently testable integration or fixing the full verification timeout rather than inventing semantic effects or adding more user-facing commands.

**Progress report:** subjective engineering scope **91% (unchanged from P46; not software-quality score)**; verified end-to-end current-client CRA/ENU mission acceptance **0%**. Safe live start remains blocked.
