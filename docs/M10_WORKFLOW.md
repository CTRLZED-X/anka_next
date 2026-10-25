# M10 — Workflow

## Scope

M10 makes `anka_workflow` the single owner of mission/run lifecycle, counters, semantic watchdogs, bounded recovery and stop policy. Decision, Coordination and Execution are consumed only through contracts/ports.

## Implemented lifecycle

`CREATED -> PREFLIGHT -> WORLD -> ENCOUNTER_SELECTED -> FIGHT_ENTRY -> PARTY_JOIN -> PLACEMENT -> READY -> FIGHT_ACTIVE -> FIGHT_END_RECONCILIATION -> WORLD_REENTRY -> WORLD`, with bounded `RECOVERING` and terminal `COMPLETED`, `STOPPED`, or `BLOCKED` states.

- One validated JSON configuration is compiled with an internal provenance-bound route asset.
- Encounter selection honors min/max monster bounds deterministically.
- `FIGHT_ENDED` never means `VICTORY`; a separate typed fight outcome is required.
- Each fight epoch is counted at most once and `attempts == wins + losses + unknowns + aborted` for reconciled attempts.
- Repeated heartbeats/log traffic do not reset semantic watchdogs.
- Recovery budgets are finite. A timeout cannot create an infinite Ready/turn loop.
- Late authoritative fight-end evidence may supersede an in-progress Ready/Fight watchdog recovery.
- An uncertain/terminal-unresolved action side effect blocks the workflow instead of causing a blind retry or fallback End Turn.
- Resume preserves durable mission counters/state but refuses to resume through an unresolved pending action.
- Route progression and fight world-reentry are distinct semantic transitions.

## Integration

`WorkflowTurnController` obtains a fresh Coordination permit, checks fight/turn epochs, requests a semantic plan and submits it through an injected `ActionExecutor`. The Q6 implementation uses only a fake executor and proves physical-input count remains zero.

## Reuse

The Sufokia route is carried as a hash/provenance-bound historical reference. Legacy campaign/party orchestration is not imported as runtime ownership.

## Limitations

Real input, current Windows acceptance, current-client semantic evidence and live mission acceptance remain outside M10/Q6.
