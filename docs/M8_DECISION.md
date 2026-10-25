# M8 — Decision

## Scope

M8 establishes `anka_decision` as a deterministic semantic planner. Decision proposes **what** should happen from an immutable `DecisionFrame`; it never decides whether an input may still be physically sent.

## Implemented boundary

- `DecisionFrame` binds run/account/client/fight/turn identity, state cursor/fingerprint, Kernel/data/profile identity, proof states, proven loadout candidates, semantic targets, quarantine and a bounded work budget.
- `PlannerResult` is explicitly `PLAN`, `WAIT`, `NO_ACTION`, or `FAULT`.
- `ActionPlan` contains semantic actions only. It contains no HWND, screen coordinate, mouse primitive, packet field or physical-input authority.
- `ActionKey` is a deterministic SHA-256 of the stable semantic frame/action representation.
- A quarantined ActionKey is not retried in the same semantic frame.
- The planner calls an injected Kernel port and fails to `WAIT` when required proof is unknown/stale rather than inventing resources or legality.
- Historical CRA/ENU priorities are retained as provenance-bound strategy knowledge; they can rank already-proven spell candidates but cannot prove a current loadout.

## Reuse

R5.198 tactical policy was used as behavioral/domain reference, not copied as a concrete dependency. The large legacy controller remains outside the new runtime ownership graph.

## Verification

Q6 covers deterministic same-frame output, proof-gated abstention, Kernel indeterminacy, budget exhaustion, ActionKey quarantine, codec round trips, dummy/fake consumer substitution, retained P12/P14/P15/P16 Decision regressions, and zero physical input.

## Limitations

M8 does not establish current-client state truth, current spell-slot truth, a live protocol release, or physical action authority. Those require later gates.
