# `anka_live_state` — P8

`reducer.py` is a **pure** deterministic state transition function. It consumes only P8 `OfflineStateEvent` contract objects, not decoded packets or P7 `CanonicalDraft` candidates. Missing HP/AP/MP/position remains `None`, never an invented zero.

It tracks session/account generation, fight identity and phase, actors' HP/max HP, AP, MP, range, cell ID, cooldown snapshots, and turn ownership. Stale fight IDs, account generation changes, gaps, invalid turn transitions and unknown actors are rejected. Starting another fight after a confirmed end resets actors and turn owner, keeping the sequence monotonic for the session. The projected state is always explicitly `actionable=false`.

Live world/fight reconstruction from certified current-build Canonical events, cross-account world snapshots, freshness windows, action authorization, and recovery from unknown/partial protocol data remain **future milestones**.
