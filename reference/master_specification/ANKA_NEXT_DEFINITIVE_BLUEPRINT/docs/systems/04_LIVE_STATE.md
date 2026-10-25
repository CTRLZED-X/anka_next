# System 04 — Live State (`anka_live_state`)

## Purpose

Live State deterministically reduces committed Canonical history into immutable world/fight snapshots and explains the provenance/freshness of every safety-critical field.

## State domains

- client/account identity projection;
- world map/position/group information;
- fight identity/epoch/phase;
- actors, teams and cells;
- HP/current/max where observed/derivable;
- AP/MP/current modifiers;
- current turn owner/round/turn epoch;
- spell/cooldown/per-turn/per-target observations;
- effects/states and relevant sources;
- fight end/world re-entry;
- field health/freshness/unknown status.

## Field semantics

A field is not merely a value. It carries evidence:

```text
FieldProof[T]:
  value: T | null
  status: KNOWN | UNKNOWN | STALE | CONFLICTING | NOT_OBSERVED
  source_event_ids[]
  canonical_cursor
  fight_epoch / turn_epoch
  authority class
  invalidation reason (optional)
```

Never map missing HP/AP/MP/cooldown to zero.

## Snapshot

`FightSnapshot` is immutable and includes identity/version tuple, canonical cursor, field proofs and a semantic fingerprint. Planning frames reference one exact snapshot/revision.

## Freshness

Freshness rules are field/action specific, not “all data after one timestamp.” Historical R5.196 demonstrated that overly strict post-`TURN_STARTED` AP/MP rules can reject valid current-turn evidence. Each action declares required causal floor and invalidators.

## Geometry overlays

Static Kernel map data is distinct from current fight-specific observed geometry. A proven fight-epoch overlay may refine current walkability/interaction evidence; it cannot permanently mutate static Kernel data.

## Dependencies

Contracts only. Reducer may use pure utilities it owns. No Protocol imports.

## Tests

- same committed history -> same snapshot hash;
- late/duplicate/reordered committed events;
- stale pre-fight vs valid current-fight resource evidence;
- false-READY and false-BLOCKED freshness variants;
- world/fight map separation;
- actor identity changes;
- fight end/world re-entry;
- incomplete field provenance;
- snapshot restore from Canonical checkpoint+journal.

