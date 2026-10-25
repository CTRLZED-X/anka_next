# Appendix A — Historical Failure Patterns & Permanent Lessons

This appendix records failure families from the R5.198 reference history. Historical fixes may already exist in that release; the purpose is to prevent ANKA_NEXT from reintroducing the same classes of failure.

## A.1 R5.142 — Action contract/quarantine/liveness

**Evidence:** `R5_142_COMBAT_ACTION_CONTRACT_QUARANTINE_TURN_LIVENESS_HARDENING.md`.

**Observed failure family:** FightAI produced a valid typed action, but generic serialization changed nested shape before Execution, causing `ACTION_INTENT_MALFORMED`. Quarantine identity was independently rebuilt and did not equal planner fingerprint, so the same action was selected repeatedly until a parent watchdog failed.

**Lessons:**

- serialization is part of the public contract;
- one canonical ActionKey/codec across producer/consumer;
- local software failure is not live-state uncertainty;
- same-frame rejected action must not loop indefinitely;
- terminal wrapper timeouts must retain the earlier meaningful failure.

**Permanent tests:** codec round-trip, malformed nested payload, ActionKey equality, repeated rejected decision, bounded turn liveness.

---

## A.2 R5.151 — Delayed confirmation amplified into global disarm

**Evidence:** `R5_151_LATENCY_RECONCILIATION_FOUNDATION_READINESS_HARDENING.md`.

**Observed failure family:** physical/semantic action had been sent, server confirmation arrived outside a short local window, and incident handling globally disarmed ControlAuthority. The next valid action failed because the diagnostic/safety response prevented passive reconciliation.

**Lessons:**

- short settlement timeout != proof of terminal failure;
- preserve known send evidence while waiting;
- pending causality can be scoped/reconciled;
- incident export must not itself revoke authority without justified disposition;
- global disarm is reserved for shared safety invariant loss.

**Permanent tests:** delayed cast/world/placement confirmation, no duplicate send, authority remains appropriately scoped, contradictory fresh outcome still fences.

---

## A.3 R5.195 — Geometry authority conflation

**Evidence:** `R5_195_FIGHT_ENTRY_GEOMETRY_INCIDENT_REPLAY_HARDENING.md`.

**Observed failure family:** server-declared placement cells were legal for the current fight while static Mapuse marked them non-walkable; old code treated static drift as proof complete fight geometry was invalid. Additional issues included divergent placement paths, reducer skew and a pre-click TOCTOU window.

**Lessons:**

- static geometry and current fight-scoped server legality are different authorities;
- live overrides are scoped by fight/phase and must not leak into ACTIVE movement rules;
- multi-account placement uses coherent generation/barrier;
- revalidate after pointer travel immediately before DOWN;
- consolidate duplicate implementations.

**Permanent tests:** stale static vs live placement evidence, phase-scoped override, cross-account placement generations, pre-DOWN drift.

---

## A.4 R5.196 — Resource freshness/turn causal model

**Evidence:** `R5_196_TURN_HANDOFF_SYSTEMIC_SIMULATION_HARDENING.md`.

**Observed failure family:** CRA first turn was authoritative, AP/MP were valid current-fight observations just before `TURN_STARTED`, but code required resources strictly newer than `TURN_STARTED`, causing permanent stall. Historical document also hardened missing TURN_ENDED and duplicate TURN_STARTED behavior.

**Lessons:**

- freshness follows semantic causal window, not arbitrary arrival-order timestamp;
- first turn, proven handoff and uncertain handoff can have different evidence floors;
- test false accept **and** false reject;
- late duplicate events cannot reopen ended turns;
- simulations cannot prove Windows input/live server boundaries.

**Permanent tests:** first-turn pre-TURN_STARTED AP/MP accepted, stale pre-ACTIVE rejected, missing TURN_ENDED strict mode, delayed duplicate turn ignored.

---

## A.5 R5.197 — Ownership/takeover generation

**Evidence:** `R5_197_CONTROL_PLANE_TAKEOVER_HARDENING.md`.

The target product removes the browser control plane, but the general failure remains relevant: stale service/process identity was not enough to safely replace a process. The fix used process generation and correlated listener/identity evidence rather than “kill whatever owns this port.”

**Lessons:**

- PID alone is not process identity;
- recheck generation immediately before destructive action;
- foreign/ambiguous process ownership fails closed;
- concurrent starts should converge safely;
- diagnostics must distinguish not-authorized vs attempted-and-failed.

**Permanent target tests:** stale run/helper/native process takeover, PID reuse, competing starts, foreign process refusal.

---

## A.6 R5.198 — Unknown protocol traffic after successful action

**Evidence:** `R5_198_PROTOCOL_OPAQUE_DRIFT_FIGHT_CONTINUATION_HARDENING.md`.

**Observed failure family:** CRA first CAST was server-confirmed and settled. Both flows then observed previously unseen server `icw`; sticky global protocol health blocked the next otherwise-valid combat action. R5.198 admitted only exact observed `icl`/`icw` variants as nonmutating opaque traffic using direction/length/SHA evidence.

**Lessons:**

- a successful first action does not certify later protocol traffic;
- unknown criticality should be classified, not patched downstream;
- exact opaque evidence can be narrow; do not generalize message name family;
- preserve fail-closed behavior for changed variants;
- raw capture and persisted Canonical journal have different forensic authority;
- adapter identity 3.7.10.10 vs observed 3.7.11.11 remains an explicit compatibility limitation.

**Permanent tests:** exact opaque fingerprint zero-state mutation, changed byte remains unknown, downstream action not blocked by certified irrelevant opaque event, critical unknown does block affected capability.

---

## A.7 Recurring operational symptoms to encode as scenarios

The project history/user reports include recurring symptoms whose root causes can differ:

- ENU not joining;
- both click Ready but fight does not progress;
- Ready stuck;
- End Turn input occurs but next owner not proven;
- CRA attempts cast on non-walkable/incorrect cell;
- world routing clicks farther 3-PM cell despite reachable 2-PM alternative;
- focus lost at turn start/before click;
- “Aucune action à réaliser” / no action;
- action appears sent but server outcome not observed.

The diagnostic/test suite must **not encode the symptom as one assumed cause**. Each scenario exercises alternate boundary failures and verifies first-divergence classification.

---

## A.8 Meta-lessons

1. Never patch the final timeout without finding the first divergence.
2. Never treat a safety guard as automatically correct; test false blocking.
3. Never weaken unknown protocol handling globally to make progress.
4. Never add incident-specific spell/cell/fight branches when a generic contract is broken.
5. Never trust one client's view to authorize another account.
6. Never let a diagnostic subsystem become the safety/action owner.
7. Never rely on another live test for a failure already reproducible offline.
8. Preserve primary evidence class and limitations.

