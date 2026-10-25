# 03 — System Specifications Overview

This page is the compact map. The detailed pages under `docs/systems/` are normative for each system.

## 1. Capture — `anka_capture`

**Question answered:** “What bytes did this exact client/connection produce or receive, in what order, and was continuity complete?”

**Receives:** NIC/packet source, capture scope, process/socket binding evidence.  
**Produces:** ordered `WireEnvelope`, explicit gaps/reconnects/health.  
**Must not:** know spell/AP/turn semantics; instantiate Protocol adapters.  
**Primary consumers:** Protocol, diagnostics.  
**Failure posture:** stream gap or ambiguous client binding fences dependent semantic trust.

[Detailed specification](systems/01_CAPTURE.md)

## 2. Protocol — `anka_protocol`

**Question answered:** “What does this version-specific wire data mean semantically?”

**Receives:** `WireEnvelope`, exact build/adapter selection, decoder context.  
**Produces:** `CandidateCanonicalBatch`, decoder checkpoint, capability/readiness health.  
**Must not:** mutate live state, click, choose combat strategy, hide unknown critical traffic.  
**Primary consumers:** Canonical; certification/replay tools.  
**Failure posture:** unknown/unsupported semantics remain explicit and capability-scoped.

[Detailed specification](systems/02_PROTOCOL.md)

## 3. Canonical — `anka_canonical`

**Question answered:** “Which semantic observations are committed as ordered durable truth?”

**Receives:** candidate canonical events, StateProjector port.  
**Produces:** committed batch/cursor, replay stream.  
**Owns:** journal order/idempotence/database commit.  
**Must not:** know raw obfuscated protocol names or AI policy.  
**Failure posture:** ambiguous commit fences writer and reopens/replays; no optimistic duplicate append.

[Detailed specification](systems/03_CANONICAL.md)

## 4. Live State — `anka_live_state`

**Question answered:** “Given committed events, what is currently known about world/fight state, with what provenance/freshness?”

**Receives:** committed events and previous immutable snapshot.  
**Produces:** deterministic snapshot/checkpoint, state queries and field proofs.  
**Owns:** reducer semantics, not journal writer.  
**Must not:** parse protocol packets or guess missing values.  
**Failure posture:** inconsistent/unknown fields remain unknown; stale plans rejected downstream.

[Detailed specification](systems/04_LIVE_STATE.md)

## 5. Game Kernel — `anka_game_kernel`

**Question answered:** “What actions/effects are legal under deterministic game rules?”

**Receives:** pure game context and static/versioned data.  
**Produces:** legality, geometry, LoS/range, movement/collision, spell/effect results.  
**Owns:** game rules/knowledge.  
**Must not:** own live network state or Windows input.  
**Reuse policy:** preserve R5.198 package semantics and tests unless evidence requires change.

[Detailed specification](systems/05_GAME_KERNEL.md)

## 6. Decision — `anka_decision`

**Question answered:** “Given a frozen verified state and rules, what semantic action should be proposed?”

**Receives:** `DecisionFrame`, KernelQueries, policy/profile.  
**Produces:** typed `DecisionPlan`, `WAIT`, `NO_ACTION`, or fault/reason.  
**Owns:** tactical/world/placement policy.  
**Must not:** click or assume proposed action succeeded.  
**Failure posture:** no legal action is explicit; rejected ActionKey is quarantined for unchanged frame.

[Detailed specification](systems/06_DECISION.md)

## 7. Execution — `anka_execution`

**Question answered:** “Is this semantic action still safe now, can it be physically sent exactly once as far as we can control, and what authoritative evidence settles it?”

**Receives:** semantic action command, latest state, KernelQueries, Client projection, Coordination permit.  
**Produces:** `REJECTED_NOT_SENT`, physical attempt receipts, `UNCERTAIN`, confirmed/settled outcomes.  
**Owns:** sole input authority, arbiter, durable attempt/outcome ledger.  
**Must not:** choose tactical goals or silently retry ambiguity.

[Detailed specification](systems/07_EXECUTION.md)

## 8. Coordination — `anka_coordination`

**Question answered:** “Are the required accounts in the same fight/phase, who owns the turn, and may this account act?”

**Receives:** immutable per-account snapshots/outcomes.  
**Produces:** party state, Ready/join barriers, turn permits, coherence verdict.  
**Owns:** roster/fight/turn multi-account truth.  
**Must not:** own mission progress or physical input.

[Detailed specification](systems/08_COORDINATION.md)

## 9. Workflow — `anka_workflow`

**Question answered:** “What mission phase are we in, what should the platform request next, and when should it wait/recover/stop?”

**Receives:** run plan/config, state/coordination/outcome updates.  
**Produces:** decision requests, execution requests, phase transitions, run counters/status.  
**Owns:** mission lifecycle and budgets.  
**Must not:** invent party ownership or bypass Execution.

[Detailed specification](systems/09_WORKFLOW.md)

## 10. Client — `anka_client`

**Question answered:** “Which Windows client/window/character is this, and where/how may a semantic UI target be physically addressed?”

**Receives:** Windows process/window observations, bridge/calibration data.  
**Produces:** `ClientIdentity`, focus proof, calibration/projection evidence.  
**Owns:** binding and projection generations.  
**Must not:** declare game-cell legality or send mouse input.

[Detailed specification](systems/10_CLIENT.md)

## 11. Observability — `anka_observability`

**Question answered:** “What happened, where did progress first diverge, what evidence supports the diagnosis, and what is missing?”

**Receives:** typed passive diagnostic events and read-only references.  
**Produces:** run journals, health, first-divergence findings, sanitized incident ZIPs.  
**Owns:** diagnostic evidence only.  
**Must not:** become a gameplay safety authority or automatically fix/retry actions.

[Detailed specification](systems/11_OBSERVABILITY.md)

## 12. Foundation packages

### `anka_contracts`

Contains the small, versioned public vocabulary: IDs, metadata, events, snapshots, action/outcome DTOs, error codes, and ports. It contains **no business policies, database writers, protocol adapters, planners, or input drivers**.

### `anka_app`

Contains composition, strict configuration, bootstrap diagnostics, lifecycle supervision and the process entry point. It is the only place allowed to construct multiple concrete system implementations.

