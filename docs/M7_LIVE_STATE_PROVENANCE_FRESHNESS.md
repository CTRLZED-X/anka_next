# M7 — Live State Provenance and Freshness

## Status

Offline/replay/fault verification complete under Q5. Live State remains a pure reducer and owns no network, database or input authority.

## Model

Every safety-relevant field is a `FieldValueProof`: value (which may be null), `KNOWN | UNKNOWN | STALE | CONFLICTING | NOT_OBSERVED`, source Canonical event IDs, Canonical cursor, fight/turn epoch, authority class and invalidation reason.

Missing HP/AP/MP/cooldown evidence is never converted to zero. Immutable `LiveStateSnapshot` objects carry account/client identity, world/fight/turn epochs, separate world/fight geometry observations, actor proofs and a deterministic semantic fingerprint.

## Freshness rules

Freshness is event/field specific. `TURN_STARTED` does not automatically stale valid absolute AP/MP evidence from the same fight, preserving the R5.196 lesson. `TURN_ENDED` invalidates turn-scoped AP/MP/cooldown evidence until refreshed. Fight end and world re-entry invalidate or clear fight-epoch state. Ready evidence never leaks into a new fight epoch.

Static Kernel geometry remains separate from observed fight-map evidence.

## Determinism

The projector accepts committed Canonical events only, rejects duplicate/reordered cursors, rejects invalid actor/turn relationships, and produces the same semantic hash from the same committed history. Canonical independently replays history and compares the result to the stored snapshot during audit/reopen.
