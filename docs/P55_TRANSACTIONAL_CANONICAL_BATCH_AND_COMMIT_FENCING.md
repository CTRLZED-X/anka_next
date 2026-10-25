# P55 — Transactional Canonical fixture batches and commit-uncertainty fencing

Date: 21 October 2026

## Purpose

P55 hardens the durable Canonical/Live-State foundation without creating any live admission authority. The R5.198 reference architecture already identified a critical rule: one logical decoder batch must advance the durable event journal and projection as one transaction, and a COMMIT acknowledgement failure must never be guessed away.

ANKA_NEXT previously had strong per-event SQLite atomicity, replay auditing and hash chaining, but its synthetic `SQLiteFixtureJournal` had no logical multi-event batch API. A future protocol message may produce several state facts together; persisting them one-by-one would permit a partial logical observation if a later event failed. The old single-event path also had no explicit writer fence for the case where SQLite may have committed but acknowledgement is lost.

P55 imports the **transactional invariant**, not the old monolithic runtime. The entire path remains `SYNTHETIC_FIXTURE_ONLY`, accepts only `OfflineStateEvent`, cannot accept `CanonicalDraft`, historical protocol evidence or current-client evidence, and cannot authorize physical input.

## New transaction boundary

`anka_canonical.journal.SQLiteFixtureJournal.append_fixture_batch(...)` now provides a bounded logical batch transaction:

1. validate one session/account/process generation and contiguous sequence;
2. begin a serialized SQLite writer transaction;
3. validate exact duplicate/idempotency state and the existing hash-chain tip;
4. run the **complete batch through the pure reducer before inserting any event row**;
5. verify every reducer output keeps synthetic authority, exact account scope, fight scope and revision;
6. insert the complete event hash chain;
7. write the final projection;
8. commit once.

A reducer error in any later event therefore persists **zero** events from that batch.

The existing `append_fixture(...)` now uses the same batch transaction path with batch size one, so there is only one persistence mechanism to maintain.

## Commit uncertainty and writer fencing

P55 distinguishes safely rolled-back pre-commit failures from a persistence boundary that cannot be proven safe.

Safe pre-commit failures such as reducer rejection or injected failure after event insertion/projection are rolled back. If rollback is positively successful, the fixture writer remains reusable.

If failure occurs at the COMMIT boundary, or rollback itself cannot be confirmed, the journal instance moves to `FENCED`. Further writes raise `JOURNAL_WRITER_FENCED_REOPEN_REQUIRED`.

This matters because an exception after COMMIT may mean either:

- the transaction was not durable; or
- the transaction **was** durable and only acknowledgement was lost.

The writer never guesses. Close/reopen + replay audit establishes the durable history before writes can resume. Reads/audits may still inspect the fenced instance, but they cannot un-fence it.

P55 includes a deterministic `commit_ack_lost` fault injection which commits the batch and then simulates lost acknowledgement. Tests prove the writer fences, rejects another write, and a newly opened journal reconstructs the committed revision from durable evidence.

## Additional integrity checks

The batch boundary also rejects:

- empty or oversized batches;
- generators/unbounded iterables;
- non-`OfflineStateEvent` objects;
- duplicate event IDs inside one batch;
- account/session/process-generation mixing;
- sequence gaps/reordering;
- partial duplicate batches;
- event-ID collisions with different payloads;
- reducer projections that forge revision, session, account generation, fight identity, authority or actionability;
- failed rollback without fencing the writer.

Exact complete batch replay is idempotent and two concurrent writers attempting the same batch result in one commit plus one exact duplicate.

## Automatic preflight

`check` and `setup` now run `anka_app.state_offline.transactional_journal_smoke()` using a temporary synthetic database. The smoke:

- writes a three-event batch with simulated lost COMMIT acknowledgement;
- verifies that the writer becomes fenced;
- verifies that a second write is refused;
- closes and reopens the database;
- verifies replay recovers the exact durable three-event revision;
- verifies the reopened writer is healthy.

The smoke reports zero live Canonical commits, no action authority and no physical input.

## Verification

For source fingerprint `605f4a4af2d38ee676b47072f38384057ead72960b2e17946658b843c86503d6`:

- new P55 transactional tests: **22 passed**;
- focused Canonical/state/shadow/architecture selection: **140 passed**;
- complete module-isolated regression inventory: **82 / 82 modules, 1,433 tests passed**;
- `check`: PASS;
- `setup`: PASS;
- architecture boundaries: PASS, 13 packages / 273 Python modules;
- preserved reference assets: 165 / 165 verified;
- `start`: intentionally BLOCKED, exit 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED`;
- startup incident ZIP integrity: PASS.

One earlier large verification batch hit the outer command timeout after safely checkpointing completed modules. The final source-bound checkpoint later completed the entire 82-module inventory; only that complete result is treated as the release gate.

## Remaining gate

P55 improves the durable transaction foundation but does not implement current-build Canonical admission. The major unresolved boundary is still authentic current-client evidence: exact-build protocol semantics plus independently bound process/socket/window/character identity and server-confirmed gameplay outcomes.

When those witnesses exist, a production admission layer can use this transactional invariant rather than inventing persistence semantics during live integration. Until then, `start` remains fail-closed and the roadmap estimate is not increased merely for additional offline hardening.
