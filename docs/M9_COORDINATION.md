# M9 — Coordination

## Scope

M9 makes `anka_coordination` the sole multi-account coherence authority. It owns party generation, roster bindings, same-fight proof, Join/Placement/Ready barriers, coherent turn ownership and generation-bound turn permits. It owns no physical input.

## Implemented boundary

- Explicit account/client/actor roster bindings; generic 2–8 member support.
- Required members must independently prove healthy capture, fight identity/epoch and map identity.
- Barrier causality is strict: `PLACEMENT` requires `JOIN`; `READY` requires both `JOIN` and `PLACEMENT`.
- One client's Ready observation never proves another member's Ready state.
- Turn ownership is granted only after all required member views converge on the same party actor and positive turn epoch.
- Canonical cursor/revision regression, epoch regression, capture gaps, identity changes and hard fight/map conflicts fail closed.
- Duplicate observations are idempotent; cursor-only heartbeat progress cannot manufacture semantic progress.
- Permits are bound to both `party_generation` and `permit_generation`. Restart/invalidation changes the party-generation namespace, making prior permits stale even when fight/turn numbers coincide.

## Historical failure coverage

The generated independent oracle includes the historical classes of failures: both clients clicked Ready but server evidence is incomplete; delayed first owner; CRA End Turn while ENU has not yet observed ownership; duplicate/delayed events; reconnect generation change; different fight/map; and one-account capture gap.

## Verification

Q6 uses an exhaustive truth table across Join/Placement/Ready and owner-view combinations plus health/gap fault cases. A wrong account or incoherent owner never receives an allowed permit.

## Limitations

The coordination model is verified offline against immutable observations. Current Windows/client/account identity and current protocol truth remain later acceptance evidence.
