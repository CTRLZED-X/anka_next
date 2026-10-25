# P6: Protocol Update Boundary and Anti-Regression Qualification

## Reality check

The old R5.198 protocol adapter is coupled to legacy canonical and live-state
classes. We preserved **only** its historical observed wire-name inventory and
scenario manifest. This release cannot yet generate authoritative gameplay events.

## Future two-week update process

1. Freeze the observed Dofus client build, capture evidence IDs and SHA-256 hashes.
2. Register a **new immutable build-specific semantic adapter**, not an in-place
   replacement of the previous adapter. Keep older adapters for reproducible replay.
3. Replay every existing fixture (both positive and negative cases), including
   Ready-to-first-turn, spell cast settled, AP/MP freshness, invalid target,
   multi-account join and End-Turn-to-next-owner.
4. Compare each decoded event against independently expected canonical outcomes.
   No proposed adapter can self-certify merely by producing events.
5. Exercise unknown messages, version mismatch, malformed protobuf, TCP gaps,
   reconnects, missing account binding, ambiguous class, truncated frames and
   unsupported fields. Every uncertified capability must be denied authority.
6. Validate the consumer contracts in `anka_canonical` and `anka_live_state`
   using snapshots/journal atomic-commit tests, then verify planner and execution
   policies with physical inputs disabled.
7. Promote only after exact-build and required-capability evidence is complete.
   Record rollback ID, provenance and diff. Do not hot-swap during a fight.

## Current system relationship

```
anka_capture ----> anka_contracts.capture ----> anka_protocol
      \                                        |
       \------> anka_app.protocol_offline <-----/
                          |
                    safe audit receipt
```

`anka_protocol` depends only on shared contracts and internal reference files.
`anka_app` is the only place connecting the transport parser and wire inspection.

## Limitations and intentional exclusions

Strict-order TCP inspection quarantines an out-of-order segment instead of
speculatively reordering it; a future bounded stream reassembler may safely
improve coverage without weakening state authority. No current-build semantics,
character-class truth, HP/AP/MP or physical input exist in this release.

## Acceptance evidence

Run `verify.bat`, `protocol_demo.bat` and `check.bat`; the release's JSON receipt
records test results observed on Linux with Python 3.13. Actual Windows/Npcap
and current-build wire evidence are separate outstanding acceptance gates.
