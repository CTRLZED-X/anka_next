# P7 — Historical semantic candidates and Canonical staging

## Purpose

P6 observed framed wire names but intentionally had no game semantics. P7 adds a
**strict, version-local, historical** 3.7.10.10 research decoder that produces
immutable Canonical **drafts**, plus a separate Canonical staging boundary.

The two packages remain separate. `anka_protocol` imports only
`anka_contracts.protocol`, `anka_contracts.semantic` and
`anka_contracts.canonical`, **never** `anka_canonical`. `anka_canonical` imports
shared contracts only. `anka_app.semantic_offline` is the composition root.

## Source reuse and exact scope

A narrow port of historical R5.198 `resources.py` and `adapter.py` mapping rules:

- `jtk` — absolute AP/MP/RANGE characteristic totals. Branch 1 composes fields
  1–6; field 7 duplicates bookkeeping and is ignored. Branch 3/5 use historical
  additive composition. Novel length-delimited branches are rejected.
- `jti` — cooldown snapshot (including a real empty snapshot candidate).
- `kqo` — local absolute HP/max HP, but **only** if separately supplied fight
  and local-actor context has been explicitly attested. This is still a draft.

No schema exists in P7 for authoritative turn owner, Ready, spell cast, position,
world map, movement, team join or victory. Unknown messages and unknown builds
produce **zero** candidates, not guessed values.

The original R5.198 source hashes and exact source paths are recorded in
`provenance/P7_historical_semantic_origin.json`.

## Evidence authority policy

```
Verified/observed wire frame
   -> build-specific historical research decoder
   -> SemanticResult (typed CanonicalDraft[] or reason for quarantine)
   -> CanonicalStagingGate (immutable research staging, dedup and cap)
   -> diagnostic-only counts

NO canonical journal writes; NO live-state mutation; NO decision input;
NO action execution; NO live readiness; NO certification by synthetic fixtures.
```

Only exact historical build `Dofus 3.7.10.10` can make historical candidates.
`Dofus 3.7.11.11` and any later/unknown build require a **new** semantic adapter
with independently corroborated current-build packets and expectations. The old
build's catalog/adapter must never silently stand in for a new version.

The local player cannot be inferred from a window title, PID, packet direction,
or user configuration. Without identity evidence `kqo` returns CONTEXT_MISSING.

Missing, duplicate, out-of-range and new-schema values cause whole-message
quarantine; no partial AP/MP state is emitted when a later characteristic fails.
Incomplete TCP evidence remains unacceptable for authoritative projection.

## Historical repeated-event bug prevention

P6's `extract_any` collapsed repeated identical `Any` envelopes within a frame.
That was unsafe for messages which may represent two separate server events. P7
preserves occurrences, adds `message_index` source identity, and leaves replay
idempotency to the Canonical boundary. Tests preserve both occurrences without
accidentally promoting either into state authority.

## Operator commands

- `semantic_demo.bat` — synthetic AP=9, MP=5, HP=850/1000 candidates, *not game evidence*.
- `semantic_audit.bat <path.pcapng> "Dofus 3.7.10.10"` — read-only offline audit;
  requires explicitly configured `capture.server_ports` in `config/user.json`.
- `verify.bat` — comprehensive offline tests, new negative cases included.
- `start.bat` — still **blocked**, emits a diagnostic ZIP, never clicks.

Reports omit packet bodies, endpoints, flow keys, character names and local file
paths. The audit emits counts and bounded code categories, not raw messages.

## What remains before current-build game state is possible

1. Current client-build captures/semantic schemas, *independent oracle* expected
   results, capture completeness and account-window identity verification.
2. Per-capability protocol certification, persisted adapter manifests and replay
   comparisons against historical incidents (including turn readiness and
   action settlement).
3. Transactional Canonical event journal + reducer, idempotent crash replay,
   atomic event/state consistency and generation-qualified freshness.
4. Integration into read-only Live State first, then Decision/Coordination/
   Execution and controlled host acceptance. Zero physical inputs until all
   safety gates pass.

## Verification interpretation

Offline synthetic tests demonstrate that the new code follows these contracts.
They do **not** prove any field has identical meaning on the current Dofus build.
Real Windows/Npcap capture and live gameplay remain untested on this host.
