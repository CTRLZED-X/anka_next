# Appendix E — Minimum Scenario / Fault Test Catalog

This is the minimum scenario inventory. Implementation may add more, but removing one requires an ADR proving it is obsolete.

## E.1 World / capture / protocol

| ID | Scenario | Required result |
|---|---|---|
| S-W01 | client world bootstrap | correct account/map/cell known or explicit unknown; no input |
| S-W02 | capture TCP fragmentation/retransmit | exact stream reconstruction |
| S-W03 | capture gap | explicit health/gap; affected semantics not trusted |
| S-W04 | reconnect | new connection generation/context |
| S-P01 | known adapter fixture | expected Canonical candidates |
| S-P02 | unknown message | capability-scoped unknown/fence |
| S-P03 | exact certified opaque | zero canonical mutation |
| S-P04 | one-byte opaque mutation | no silent acceptance |
| S-P05 | current-build negative absence unproven | absence not treated authoritative |

## E.2 Canonical / State

| ID | Scenario | Required result |
|---|---|---|
| S-C01 | duplicate event | idempotent/no double state |
| S-C02 | conflicting ID | reject/fence |
| S-C03 | commit ambiguity | reopen/replay one truth |
| S-C04 | crash after commit before publish | restore snapshot from durable cursor |
| S-S01 | first-turn AP/MP before TURN_STARTED but after ACTIVE | ready where causal rule allows |
| S-S02 | AP/MP stale before ACTIVE | rejected/stale |
| S-S03 | duplicate late TURN_STARTED | ended turn not reopened |
| S-S04 | world/fight map separation | correct scoped geometry |

## E.3 Client / identity / projection

| ID | Scenario | Required result |
|---|---|---|
| S-I01 | two windows with similar titles | authoritative identity distinguishes or blocks |
| S-I02 | PID/HWND reuse | old proof invalid |
| S-I03 | wrong class/loadout | action blocked |
| S-I04 | DPI/resize after calibration | projection invalidated |
| S-I05 | focus changes before DOWN | NOT_SENT, no click |
| S-I06 | stale bridge generation | projection rejected |

## E.4 Placement / Ready / coordination

| ID | Scenario | Required result |
|---|---|---|
| S-Q01 | both accounts same fight | coherent fight epoch |
| S-Q02 | one account different fight | barrier blocked |
| S-Q03 | server legal placement vs stale static walkability | fight-scoped placement evidence allowed only in placement phase |
| S-Q04 | both UI Ready clicked, one authoritative Ready absent | barrier remains pending, root evidence clear |
| S-Q05 | Ready both confirmed, first owner delayed | no planner/input until owner proof |
| S-Q06 | CRA ends turn, ENU owner delayed | no ENU input; bounded wait |
| S-Q07 | missing TURN_ENDED | strict handoff evidence policy |
| S-Q08 | delayed duplicate old turn | no owner rollback/reopen |

## E.5 Decision / Kernel

| ID | Scenario | Required result |
|---|---|---|
| S-D01 | valid CRA cast | deterministic semantic plan |
| S-D02 | all casts illegal | explicit WAIT/NO_ACTION, no click |
| S-D03 | malformed ActionPlan codec | contract failure, no live-state wait |
| S-D04 | same rejected ActionKey repeated | quarantined; alternative/wait/end-turn request |
| S-D05 | target non-walkable/out of range/LoS | Kernel rejects |
| S-D06 | route chooses reachable 2-PM vs invalid farther move | policy/kernel/path tests prevent illegal/needless selection according to defined scoring |

## E.6 Execution / outcomes

| ID | Scenario | Required result |
|---|---|---|
| S-E01 | plan stale before input | REJECTED_NOT_SENT |
| S-E02 | prepared then canceled before send | NOT_SENT terminal |
| S-E03 | crash during OS send | UNCERTAIN, no blind retry |
| S-E04 | driver accepted, server confirmation late | pending reconciliation; no duplicate |
| S-E05 | wrong action/fight/actor consequence | does not settle current action |
| S-E06 | cast confirmed but AP/cooldown obligation missing | CONFIRMED_UNSETTLED |
| S-E07 | End Turn click with no owner transition | not settled; no next account permit |
| S-E08 | two accounts request physical input concurrently | one arbiter lease, serialized |

## E.7 Workflow / mission

| ID | Scenario | Required result |
|---|---|---|
| S-F01 | full world→fight→world zero-input | deterministic complete phase flow |
| S-F02 | victory duplicate event | win counted once |
| S-F03 | loss/unknown policy | configured bounded disposition |
| S-F04 | fight end before/after timeout | authoritative result wins over wrapper timeout correctly |
| S-F05 | Ctrl+C in each major phase | safe disarm/shutdown |
| S-F06 | previous unclean run | reconcile unresolved action before arming |

## E.8 Protocol upgrade

| ID | Scenario | Required result |
|---|---|---|
| S-U01 | add new wire-equivalent adapter | downstream semantic oracle unchanged |
| S-U02 | old adapters after new addition | historical regressions pass |
| S-U03 | candidate staged only | active adapter unchanged |
| S-U04 | activate during unresolved action | promotion refused |
| S-U05 | rollback adapter incompatible with current build | remain disarmed |
| S-U06 | mixed client builds across accounts | per-account qualification; no blanket party permit |

## E.9 Diagnostics / packaging

| ID | Scenario | Required result |
|---|---|---|
| S-O01 | Python missing during setup | bootstrap evidence exists |
| S-O02 | dependency install failure | first failing stage identified |
| S-O03 | observer queue overflow | loss counters; gameplay authority unaffected |
| S-O04 | disk full during export | partial bundle marked, original failure preserved |
| S-O05 | multiple plausible causes | honest uncertainty |
| S-O06 | secrets nested in diagnostic payload | share bundle sanitized/excluded |
| S-O07 | checksum corruption | bundle verifier fails precisely |
| S-R01 | clean release ZIP setup/start | resources located; exact manifest coherence |

