# System 03 — Canonical (`anka_canonical`)

## Purpose

Canonical is the durable semantic-history authority. It decides which candidate observations become ordered committed ANKA events.

## Responsibilities

- validate canonical schema/version;
- establish durable event identity/idempotence;
- validate source/actor/fight/epoch relationships;
- serialize admission through one writer;
- deduplicate exact events;
- detect invalid sequence/gaps;
- coordinate pure state projection with the transaction;
- atomically persist events/checkpoints/required terminal evidence;
- publish a committed cursor only after durable commit;
- replay by cursor and migrate explicitly versioned old journal schema.

## Atomicity

The target preserves the R5.198 strength: committed semantic history and checkpoints do not diverge due to separate uncoordinated writers.

A commit failure/ambiguity results in `CANONICAL_COMMIT_UNCERTAIN`; writer is fenced, DB reopened/inspected, and durable cursor replay determines truth. Do not simply append again.

## Candidate vs committed

A Protocol candidate is not Canonical truth. Consumers of game state may only depend on committed events/cursors.

## Public API

- `commit_candidate_batch(...) -> CommitReceipt`
- `events_after(cursor, limit) -> CommittedBatch`
- `current_cursor(account/stream)`
- `replay(...)`
- health/commit state.

## Dependencies

Imports Contracts. Receives a `StateProjectorPort` injected by App; no concrete LiveState import.

## Tests

- exact duplicate/idempotence;
- conflicting event IDs;
- actor/fight/epoch mismatch;
- out-of-order/gap behavior;
- SQLite failure before BEGIN, mid insert, checkpoint write, commit, after commit before publish;
- restart replay equality;
- decoder checkpoint rollback linkage;
- terminal fight evidence not double-applied;
- migrated old journal fixtures.

