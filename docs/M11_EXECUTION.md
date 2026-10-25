# M11 — Execution Safety

## Scope

`anka_execution` is the sole owner of external physical input and action settlement. Decision proposes semantics; Execution independently decides whether an action is still admissible **now**.

## Final admission

Before durable prepare and again while holding the host-wide input lease immediately before the external boundary, Execution revalidates:

- run/input-authority generation and deadline;
- newest account/client/fight/turn state and canonical cursor;
- action-basis invalidation and required field proofs;
- executing actor/current turn owner for turn actions;
- action-specific Coordination permit and exact party/permit generation;
- process/HWND/window/projection/calibration identity;
- foreground/visibility/geometry proof;
- current spell/loadout binding for casts;
- semantic target-to-projection fingerprint;
- final Kernel legality;
- absence of unresolved prior action side effects.

A valid Decision plan is never itself input permission.

## Host-wide arbitration

`HostInputArbiter` has one active lease per process. Account lanes never imply simultaneous mouse/keyboard authority. Permit/identity/state checks are repeated under that lease.

## Durable external-boundary model

The definitive SQLite ledger uses WAL + `synchronous=FULL`, append-only hash-chained events, a unique semantic action key per run/account/fight/turn, and explicit statuses.

Key crash semantics:

- `PREPARED` after restart => provably no send; terminalized as not sent.
- `SEND_STARTED` after restart => `UNCERTAIN`; never auto-retried.
- `PENDING`/`CONFIRMED_UNSETTLED` after restart => reconciliation required; no resend.
- terminal settled/failure states remain terminal.

`SEND_STARTED` is persisted **before** the driver can cross the external boundary. A database transaction therefore never pretends to make a Windows click exactly-once.

## Outcome settlement

Authoritative outcome evidence is correlated by action scope, account/client, fight/turn causality, actor when available, newer canonical cursor, and action-specific expected proof set. Partial proof is `CONFIRMED_UNSETTLED`; a successful driver API call alone remains only `PENDING`.

Wrong fight/actor, old cursor, non-authoritative or unrelated evidence cannot settle the action. Outcome evidence may race ahead of a synchronous driver return without regressing the already-settled state.

## Drivers

- `FakePhysicalInputDriver` implements the production driver contract with zero OS input and is used by Q7/Q9.
- `WindowsPointerInputDriver` is the only Python OS-input implementation. Construction requires an explicit current-build `WindowsActionScopeEnablement(enabled=True)` and Windows; observe-only/setup/start paths do not construct it.
- The Windows driver rechecks the injected guard before pointer movement and again before click. Once pointer movement may have occurred, later ambiguity is conservatively `MAY_HAVE_SENT`.

The presence of this driver is **not** current-build action acceptance. Q12 must authorize individual action scopes with real evidence.

## Verification

Q7 includes the definitive M11 fault matrix plus retained P18/P19 regressions. It covers stale state, wrong owner/window/focus/projection/loadout, Kernel rejection, permit drift, prepare/send crash cuts, ambiguous sends, restart, duplicate ActionKey fences, concurrent accounts, outcome races, partial settlement, ledger tamper, disarm/deadline and disabled Windows action scope.

## Limitations

Q7 executes only fake input and reports zero OS physical inputs. Windows host validation is Q10; current-build observe-only is Q11; actual bounded actions are Q12.
