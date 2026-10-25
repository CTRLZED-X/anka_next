# `anka_canonical` — P8

The P7 `CanonicalStagingGate` still quarantines all historical protocol semantic candidates. It commits **zero** Canonical events.

P8 adds `SQLiteFixtureJournal` in `journal.py` for the **synthetic fixture contract only** (`anka_contracts.state.OfflineStateEvent`). It atomically commits immutable source events and matching state projections inside one SQLite transaction (`WAL`, `synchronous=FULL`, `BEGIN IMMEDIATE`). The injected reducer is owned by the Live State System; wiring happens in `anka_app.state_offline`, not through cross-system imports.

- Sequence and event identity are strictly checked; exact duplicate delivery is idempotent, conflicting duplicates and ordering gaps fail closed.
- Event history is chained with SHA-256 hashes, and stored projections are verified by deterministic replay on reopen and on demand. These checks detect accidental tampering/corruption; **unkeyed hashes are not cryptographic authentication against an attacker able to rewrite the entire DB**.
- Event/projection updates either both commit or both roll back. Fault-injection tests cover both intermediate stages.
- All views remain `SYNTHETIC_FIXTURE_ONLY`, `actionable=false`. **No route exists from P7 historical candidates to the P8 fixture writer.**
- Journal schema upgrades, current-build attestation, real canonical admission, and live authorized state commits are NOT implemented. Crash-recovery behavior is verified by reopen and injected errors, not a physical power-loss test.

This journal is a testable blueprint for the later certified authoritative Canonical journal, not yet that production facility.
