# P56 — source-bound batch receipts and journal schema v2

## Purpose

P55 made one synthetic Canonical event batch crash-atomic, but durable state still had no first-class record of **which exact upstream logical source batch** produced a committed event range. Event IDs alone are insufficient as a future handoff boundary: after a crash/retry, a caller could accidentally relabel the same source, or try to attach a receipt to already-stored events.

P56 adds a synthetic-only source receipt contract and binds that receipt, the event hash chain, and the final projection in the **same SQLite transaction**. This remains test infrastructure. Historical/current protocol drafts cannot use this API and it grants no gameplay or input authority.

## Contract

`OfflineBatchEnvelope` contains:

- a bounded `batch_id`;
- a 64-hex `source_digest` identifying the exact upstream synthetic observation batch;
- a bounded tuple of `OfflineStateEvent` values;
- immutable authority `SYNTHETIC_FIXTURE_ONLY`.

`SQLiteFixtureJournal.append_fixture_envelope()` accepts only that type.

## Durable receipt semantics

Schema v2 adds `batch_receipts` with an immutable binding between:

`batch_id → source_digest → session/range → event payload digest → final event hash`

The receipt is inserted only after all events have been reduced, journaled, and projected, but before the transaction COMMIT. Therefore events, projection, and receipt are all-or-nothing.

The gate fails closed when:

- a `batch_id` is reused with another source or payload;
- the same `source_digest` is relabelled under another batch;
- a receipted batch overlaps an existing receipt range;
- a receipt tries to adopt already committed unreceipted events;
- receipt digest/range/final-event-hash integrity fails;
- COMMIT acknowledgement is ambiguous.

Exact receipt replay is idempotent. If COMMIT became durable but acknowledgement was lost, the writer is fenced as in P55; after close/reopen/audit, replaying the exact envelope returns `IDEMPOTENT_RECEIPT` rather than applying the facts again.

## Migration

The synthetic ledger schema moves from v1 to v2. Writable v1 databases are migrated under `BEGIN IMMEDIATE`; existing event/projection bytes are left unchanged and then replay-audited. Read-only v1 opens are **not silently migrated** and fail as unsupported until a writable migration is performed. Unknown schema versions are never repaired.

Fresh-schema creation is also serialized, preventing two concurrent writers from racing while the version table is empty.

## Verification

- New P56 tests: 16 PASS.
- Focused P8/P9/P10/P55/P56 state/Canonical group: 152 PASS.
- Full isolated source-bound regression suite: **83/83 modules, 1,449 tests PASS**.
- Architecture: 13 packages / 273 Python modules / zero violations.
- `check`: PASS.
- `setup`: PASS.
- `start`: intentionally BLOCKED, exit 40, `LIVE_RUNTIME_NOT_IMPLEMENTED`.
- Latest incident ZIP integrity: PASS.

Verification fingerprint: `673bd5450329377d0d796811f179589a6f5c085c4b63409fa8b64750951d44d2`.

## Safety boundary

P56 does **not** implement current-build certification, current-client character identity, production Canonical admission, authoritative live state, physical input, server-outcome settlement, or live CRA/ENU acceptance. It creates a stronger transaction handoff for the future admission boundary without pretending that boundary is already satisfied.
