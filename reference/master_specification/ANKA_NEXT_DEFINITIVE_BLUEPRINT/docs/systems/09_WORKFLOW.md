# System 09 — Workflow (`anka_workflow`)

## Purpose

Workflow owns mission/run lifecycle: what phase the automation is in, what goal is next, how attempts/wins are counted, when to request planning/execution, and when to wait/recover/stop.

## State machine

Representative high-level phases:

```text
CREATED
 -> PREFLIGHT
 -> WORLD
 -> ENCOUNTER_SELECTED
 -> FIGHT_ENTRY
 -> PARTY_JOIN
 -> PLACEMENT
 -> READY
 -> FIGHT_ACTIVE
 -> FIGHT_END_RECONCILIATION
 -> WORLD_REENTRY
 -> WORLD ...
 -> COMPLETED | STOPPED | BLOCKED
```

Sub-state machines may exist for fight entry/placement/ready/combat/reentry, but Workflow remains the single mission-phase owner.

## Responsibilities

- compile effective mission plan from validated config/internal assets;
- route/patrol progression;
- encounter group selection and monster bounds;
- run budgets (`target_wins`, `max_attempts`, stop policies);
- request Decision when appropriate;
- submit semantic actions to Execution;
- interpret typed outcomes/Coordination status;
- bounded recovery and resume;
- verified win/loss/attempt counting once;
- safe stop/shutdown status.

## Progress model

Every wait has:

- expected evidence/event;
- owner;
- monotonic deadline/budget;
- semantic progress token;
- allowed recovery transition;
- terminal failure code.

Repeated logs/heartbeats do not reset progress.

## End-turn fallback

A fallback End Turn is **not** a special bypass. If Workflow requests it, normal Coordination/Execution admission rules still apply, and an unsettled prior action may block it.

## Dependencies

Contracts/ports only. Decision, Execution, Coordination implementations are injected.

## Tests

- world→fight→world complete lifecycle;
- target wins/attempt budgets and exact counting;
- loss/unknown policies;
- Ready stall and bounded recovery;
- first-turn stall;
- action pending/late confirmation;
- fight end before/after watchdog boundary;
- duplicate terminal events;
- reconnect and new fight generation;
- stop/Ctrl+C during each phase;
- no silent infinite loop.

