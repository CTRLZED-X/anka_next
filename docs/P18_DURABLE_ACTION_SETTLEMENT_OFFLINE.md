# P18 — Durable synthetic execution-settlement boundary

**Scope:** Offline fixture-only execution state machine and SQLite ledger. No physical input, no Windows actuator, no certified protocol/state authority, no autonomous gameplay. This milestone does *not* make live actions safe.

## Why this system exists

R5.198's recurring "did it click?" incidents often needed causal evidence distinguishing an intended action, a physical attempt, and a server-observed result. Retrying a command after a timeout can duplicate casts or End Turn. P18 establishes a deterministic model to prevent this **class of error** during future integration.

The durable ordering contract for a future real executor is:

```
  decision (verified, not yet available)
       |
       v
  PREPARED (durable, no IO)
       |     \__ CANCELLED (before dispatch only)
       v
  DISPATCH_UNCERTAIN (COMMITTED BEFORE any possible IO)
       |  \__ no proof / timeout / crash => remains UNCERTAIN, NO RETRY
       |
       +---- exact scoped evidence ACCEPTED -> CONFIRMED (fixture only)
       +---- exact scoped evidence REJECTED -> REJECTED (fixture only)
       +---- INCONCLUSIVE -> DISPATCH_UNCERTAIN
```

P18 **never invokes** the physical IO shown as a future requirement. `mark_dispatch_boundary()` models committing an intention boundary without sending anything. The CLI's synthetic `CONFIRMED` means only that a fabricated outcome fixture matches the fabricated intent; it is NOT real server confirmation.

## Package ownership

- `src/anka_contracts/execution_flow.py`: immutable fixture contracts, exact scoped identities, no-authority flags.
- `src/anka_execution/settlement.py`: pure allowed-transition table and reason codes.
- `src/anka_execution/ledger.py`: durable transaction-backed intent/event/evidence store, hash-chain replay validation, read-only audits and single global uncertain dispatch gate.
- `src/anka_app/execution_offline.py`: composition-only demo, evidence reporting, observation and incident export.
- `tests/test_p18_execution_settlement.py`: positive, negative, concurrent-writer, corruption, crash and CLI regression tests.

No `anka_execution` module imports a decision, kernel, client, capture, coordination, workflow, Windows mouse or keyboard implementation. Future execution authority must be gated through contracts and a separately verified physical-input adapter.

## Important invariants

1. `PREPARED` is not sent. `DISPATCH_UNCERTAIN` means IO *could* have happened in a future runtime; never retry it automatically.
2. `action_id` is unique and a `(session, fight, actor, turn, action_key)` logical action cannot be prepared again, even if its first settlement is terminal.
3. Only one action can be `DISPATCH_UNCERTAIN` globally. SQLite `BEGIN IMMEDIATE` prevents two writers acquiring the gate together.
4. A second pending request targeting the same `(client_id, window_generation)` is rejected.
5. A scoped outcome must match all original identity/fight/turn/window fields, have a unique evidence ID, and have a strictly newer synthetic state revision.
6. Every transition updates event log, evidence table (if applicable) and state projection inside one SQLite transaction. Failpoints verify rollback.
7. A read-only audit reconstructs all actions using the global event hash chain, compares projection flags and evidence IDs, and reports contradictions instead of repairing them silently.
8. An audit must not create missing databases. It runs using SQLite read-only mode and one coherent transaction.
9. Diagnostic evidence includes action ID, settlement reason, event count, evidence IDs and first reported failure. The ZIP excludes raw SQLite content and any raw network packets; the local `.sqlite3` journal is retained under its own run folder for deeper investigation.
10. All contracts/reports explicitly say synthetic-only, not actionable and not permitted to send physical input. No component in this release can promote fixture evidence to live authority.

## Windows commands

```
execution_demo.bat
execution_demo.bat accepted-fixture
execution_demo.bat duplicate-dispatch
execution_demo.bat wrong-evidence
execution_demo.bat inconclusive
execution_audit.bat "C:\path\to\p18_synthetic_action_ledger.sqlite3"
```

`execution_demo.bat` defaults to an intentionally uncertain fixture; this **demonstration** exits 0 and emits an incident. `execution_audit.bat` returns 10 when any action remains `DISPATCH_UNCERTAIN`, 0 for a consistent synthetic non-uncertain ledger, or 40 for malformed/missing evidence. No action is sent in any scenario. The audit is read-only.

`start.bat` must continue refusing live operation with `LIVE_RUNTIME_NOT_IMPLEMENTED` and exit code 40.

## Adversarial verification

Tested in a Linux Python 3.13 host with `PYTHONPATH=src`: duplicate ID and logical key, wrong process generation and turn scope, repeated/late evidence, attempts to settle before dispatch, cancellation of uncertain actions, SQLite writer races, fault injection at atomic commit boundaries, event/projection tampering, and contract authority-forgery attempts.

The historic occasional full-suite timeout is still an open operational concern. P18 adds `verification.suite_timed_out` diagnostics with the last captured test output, but **does not claim to have eliminated the underlying causes of slow or stalled suites**.

## Missing safety-critical capabilities before live execution

- Real account/window/character/class and current spell-slot identity verified on Windows.
- Current-client semantic protocol certification and authoritative Canonical state/evidence.
- Game-kernel decision facts from live fight geometry, turn owner, inventory and counters.
- An exclusive Windows input authority/actuator proven to observe the transaction order above, with accurate process generation, focus checks, click/move timing, calibrated coordinates and watchdogs.
- Strong causal *server* observation matching. Generic AP changes or time delays cannot count as confirmation. The fixture's `action_id` is fabricated; real protocol messages may lack such an ID, so settlement will require independently validated matching rules and may remain uncertain.
- Recovery procedure for ambiguous sends, game restart, capture dropout, network disconnect, and reattestation after process/window changes.
- Windows native acceptance and controlled end-to-end gameplay tests.

Passing P18 does not certify any of these capabilities. The Ledger's hash chain detects accidental corruption but is **not a cryptographic security boundary against an attacker who can rewrite the entire local database and hashes**. Full durability after sudden power loss is also not proven by normal test-process rollback.

## Next work

P19 should prioritize an executable contract/authority design and an offline fake-driver execution service with precise command sequencing and fault injection. It should *not* enable actual clicks until Windows, current-build, and live-evidence gates are satisfied. In parallel, revisit the missing current-client protocol admission tests before attempting an end-to-end live run.
