# P57 — Crash-atomic synthetic Canonical journal schema and concurrent startup

**Date:** 2026-10-21  
**Scope:** `anka_canonical.journal` SQLite fixture journal, app preflight, isolated regression tests.  
**Authority:** `SYNTHETIC_FIXTURE_ONLY`; no live Canonical admission, current-client certification, or physical input.

## Verified original failure

P56 used `sqlite3.Connection.executescript()` inside an explicit `BEGIN IMMEDIATE` when creating a new database. Python's SQLite API **implicitly commits the transaction before `executescript`**, so a denied later DDL operation could leave `ledger_version` and `events` durably created, without the remaining tables or version marker. A direct SQLite authorizer fault reproduced that partial schema in unmodified P56. A second direct test found transient `database is locked` during concurrent fresh WAL negotiation. These are real durability/startup defects, not missing protocol features.

## P57 corrective boundaries

- Creates every initial v2 table and its version row with separate `execute()` calls within **one** `BEGIN IMMEDIATE` transaction. Failure in the middle rolls **everything** back; retry starts with an empty file schema.
- Rejects a non-empty, **unversioned partial** domain schema without attempting to fill missing tables or promote an unknown database. A clean empty version table is still supported.
- Verifies exact v2 columns, types, nullability, and primary key definitions, and checks mandatory uniqueness of event ID, event session/sequence, projection session, receipt batch/source, and receipt session/range.
- Inspects v1 schema layout and uniqueness **before** migration. A corrupt v1 cannot be rewritten with a v2 version marker. Valid v1 migration remains serialized and rollback-atomic.
- Sets busy timeout before WAL negotiation and uses a **bounded retry exclusively for SQLite lock contention** during WAL mode establishment. Other errors are not swallowed. A non-WAL result is rejected.
- The normal `check`/`setup` preflight runs a fresh synthetic database fault injection that denies creation of the last table, verifies that zero tables survive, and checks clean recovery. This never touches real databases.

## Test matrix

`tests/test_p57_atomic_schema_bootstrap.py` exercises:

1. Rollback on mid-creation DDL failure.
2. Rollback on final-table DDL failure.
3. No silent promotion of an abandoned partial/unversioned schema.
4. Clean initialization from an empty version table.
5. Two simultaneous fresh writers.
6. Unsupported version and read-only rejection without mutation.
7. Tampered v2 unique-index contracts and renamed columns.
8. v1 migration rollback on denied version publication and recovery.
9. Corrupt v1 structural rejection without upgrading.
10. Automatic preflight schema fault smoke.

P55 atomic event/projection behavior and P56 durable source receipts remain intact. This patch **does not** add a production event admission path; both the journal and its receipts reject historical/current-client drafts.

## Acceptance and remaining work

`verification/P57_offline_acceptance_receipt.json` reports completed test inventory and readiness explicitly. Real Windows simultaneous-process behavior, non-synthetic live Canonical admission, authoritative fight state, and CRA/ENU gameplay remain unverified. Do not infer live readiness from SQLite tests.
