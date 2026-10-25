# M11 — Execution Safety and Physical-Input Authority

## Scope

M11 makes `anka_execution` the sole owner of final action admission, host-wide input arbitration, physical-send uncertainty, durable action lifecycle and authoritative outcome settlement. It does **not** make physical input live-ready: the production Win32 driver remains disabled unless an explicit exact-build action scope is enabled on Windows.

## Final admission

Immediately before a possible send, Execution independently rechecks latest state health/epochs/cursor invalidation, actor/turn ownership, Coordination permit generation, Client process/window/build/projection/calibration/loadout generation, exact semantic-to-pixel fingerprint and Kernel legality. A durable prepare is followed by another full recheck, and the driver receives a guard that repeats this proof around the external boundary.

The final context comparison binds observed client build, PID/process creation, HWND/window generation, projection/calibration/loadout generation, exact projected pixel, party/permit generations and fight/turn epochs. Decision cannot weaken settlement requirements: Execution owns minimum outcome proof sets per action kind.

## Durable action lifecycle

The SQLite action ledger uses WAL + `synchronous=FULL`, an append-only hash chain and a projection audit. Immutable prepared-command hash, run generation, authority generation and prepared reference are committed into the first event so direct projection tampering is detected.

Key states are:

`PREPARED -> SEND_STARTED -> PENDING/UNCERTAIN -> CONFIRMED_UNSETTLED -> SETTLED_SUCCESS/PROVEN_FAILURE`, with definitely pre-send rejection kept distinct from any `MAY_HAVE_SENT` state.

The unresolved-action fence is checked atomically inside the same `BEGIN IMMEDIATE` transaction as prepare, so concurrent accounts cannot both durably prepare conflicting attempts.

## Crash/restart semantics

- crash before prepare: no durable action;
- durable `PREPARED` with no possible send: restart proves `REJECTED_NOT_SENT`;
- `SEND_STARTED`: restart becomes `UNCERTAIN/MAY_HAVE_SENT`;
- `PENDING` or `CONFIRMED_UNSETTLED`: restart does not resend and blocks re-arm until reconciled;
- settled outcome survives restart and permits later re-arm;
- outcome may race ahead of synchronous driver return without status regression.

No database transaction claims exactly-once Windows input.

## Outcome settlement

Settlement is monotonic and cumulative. Separate authoritative observations may satisfy separate obligations over time; a weaker or irrelevant later observation cannot downgrade `CONFIRMED_UNSETTLED`, `UNCERTAIN`, or a terminal result. Wrong account/client/fight/actor/cursor evidence does not settle the action.

Execution-owned minimum obligations currently include:

- `CAST`: cast confirmation + resource/turn progress;
- `MOVE`: actor-cell change;
- `READY`: authoritative Ready/phase confirmation;
- `END_TURN`: authoritative owner change;
- `JOIN_FIGHT`: authoritative fight join;
- `WORLD_MOVE`: authoritative map/cell change.

## Win32 boundary

`WindowsPointerInputDriver` requires an explicit enabled action-scope object bound to the observed client build and accepted action kinds, and can only construct on Windows. The split pointer transaction performs guard checks before pointer movement, before mouse-down and after mouse-down. If context changes after down, it always attempts mouse-up and returns `MAY_HAVE_SENT`; it is never downgraded to `NOT_SENT`.

The low-level transaction is independently fake-testable, so Q7 performs no OS input.

## Reuse

R5.198 control authority, input transaction, settlement and latency-reconciliation behavior were used as regression knowledge. The large legacy Execution service and cross-system imports were not copied as runtime ownership.

## Verification

Q7 covers stale/latest-state admission, wrong focus/window/build/projection/loadout, Kernel/Coordination rejection, atomic prepare concurrency, split pointer transaction, restart crash cuts, delayed/partial outcomes, action-result/driver races, ledger tamper detection, host-wide arbitration, no blind retry and explicit safety mutants.

## Limitations

Q7 is offline/fake-only. It does not prove current Windows process identity, current calibration, current-build protocol semantics, or any accepted live action scope. Those remain Q10–Q13 work/evidence.
