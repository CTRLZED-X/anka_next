# M6 — Canonical Durable Authority

## Status

Offline/fault verification complete under Q5. This is **not** current-client or physical-action acceptance.

## Ownership

`anka_canonical` is the single semantic-history durability authority. Protocol submits `CandidateCanonicalBatch`; consumers may trust only committed `CanonicalEventEnvelope` rows/cursors. Canonical imports stable contracts and receives the pure State projector by injection from `anka_app`.

## Durable transaction

For each admitted batch Canonical validates exact adapter/build admission, source connection/generation/ordered envelope references, batch/source idempotence, duplicate candidate identity, and candidate scope. In one SQLite transaction it writes the semantic events, projects the immutable account snapshot, stores the decoder checkpoint linkage and persists the batch receipt. The committed cursor is returned only after `COMMIT` succeeds.

`WAL` + `synchronous=FULL` are required. Pre-commit failure cuts roll back all partial rows. A lost/ambiguous commit acknowledgement raises `CANONICAL_COMMIT_UNCERTAIN`, fences that writer instance, and requires reopen/audit/replay rather than blind append.

## Decoder linkage

Only `SEMANTIC_CANDIDATES` and exact `OPAQUE_CERTIFIED_ZERO_SEMANTIC` batches can be admitted by the definitive exact-release policy. `NO_SEMANTIC_MAPPING`, incomplete transport, unknown critical data and quarantine cannot move trusted decoder state through Canonical.

The composition-root `CanonicalAdmissionAdapter` translates Canonical commit/reject/uncertain results into Protocol's stable admission contract. Protocol restores its pre-decode checkpoint for reject or uncertain outcomes.

## Replay and integrity

The public writer surface provides commit, cursor reads, ordered `events_after`, stored snapshots, `replay(account_id)`, health and audit. Audit validates the global event hash chain, batch cursor ranges, exact snapshot account set, and independent state replay equality.

The prior P55–P59 synthetic journal remains a regression fixture; it is not silently migrated into authoritative M6 truth.

## Q5 evidence

Q5 includes the definitive M6/M7 tests plus retained Canonical/state/history regressions. Physical input count is zero.
