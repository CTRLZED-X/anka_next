# System 08 — Coordination (`anka_coordination`)

## Purpose

Coordination is the multi-account authority. It determines whether required accounts belong to the same mission/fight generation, whether barriers are satisfied, and which account may act.

## Owned state

- configured roster/roles;
- verified account/client bindings;
- party generation;
- same-fight proof;
- per-member placement/join/Ready status;
- current coherent turn owner;
- per-account canonical cursors/freshness vector;
- barriers and permit generation;
- synchronization deadlines/recovery state.

## Inputs

Immutable per-account snapshots and relevant settled outcomes. It does not read mutable LiveState internals.

## Outputs

- `PartySnapshot`;
- `JoinBarrier`, `ReadyBarrier`, `PlacementBarrier`;
- `TurnPermit(account, fight_epoch, turn_epoch, permit_generation)`;
- coherence faults (`SAME_FIGHT_UNPROVEN`, `TURN_OWNER_CONFLICT`, `MEMBER_STALE`, etc.).

## Key rule

A UI Ready click or CRA's client view cannot prove ENU's Ready/turn state. The party model uses required evidence from each configured member.

## Handoff

CRA → ENU transition requires correct fight/turn lifecycle evidence. Missing `TURN_ENDED` or delayed new owner must not result in guessed permission. Duplicate/later events must be handled idempotently.

## Dependencies

Contracts only. Workflow requests/checks coordination through ports; Coordination does not import Workflow.

## Tests

- CRA+ENU same fight vs different fights;
- one client joins late;
- duplicate/delayed Ready;
- both clicked Ready but one server Ready absent;
- first turn owner delayed;
- CRA End Turn with missing/duplicate turn events;
- stale account after reconnect/new fight generation;
- conflicting owner views;
- one account capture gap;
- generic roster behavior for >2 simulated accounts.

