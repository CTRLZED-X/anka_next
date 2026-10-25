# M0 — Reference Baseline and Evidence Freeze

**Milestone:** M0  
**Target gate:** Q0 Baseline  
**Runtime/gameplay changes:** none  
**Physical input:** none

## Purpose

M0 freezes the exact evidence and reference inputs used to implement the definitive ANKA_NEXT roadmap. It prevents future work from silently changing historical facts, confusing derived reports with raw evidence, or copying legacy runtime ownership into the new architecture.

The authoritative target design is bundled read-only under:

`reference/master_specification/ANKA_NEXT_DEFINITIVE_BLUEPRINT/`

The exact source archives are bundled read-only under:

`reference/baselines/archives/`

They are reference material only and are never imported by the runtime.

## Frozen identities

- R5.198 legacy reference ZIP: `f1a50a3555cbe89f27d58ef8411cfcb002ec3cd1cd5aefe4546b4285f47f62d6`
- starting ANKA_NEXT P66 ZIP: `9c0edf863de39be9479bbd25e39c22d089af088268f9cf0afcc87e37f7765297`
- definitive master-specification ZIP: `69a3c3260a8dc20aeae2fe70e036c8bfcbfa2c275f9f370e1383419b3ff5461d`

`reference/m0/` contains complete member/file manifests so both whole-archive identity and individual file identity can be checked independently.

## Evidence policy

`reference/m0/evidence_catalog.json` uses only the master-spec classes:

- `ARCHIVED_RAW`
- `ARCHIVED_JOURNAL`
- `ARCHIVED_DIAGNOSTIC`
- `DERIVED`
- `SYNTHETIC`
- `MISSING`

A derived report never becomes raw evidence. Synthetic fixtures never become live evidence. Missing evidence remains missing until a later gate collects primary evidence.

The lean R5.198 archive does not contain the original live PCAP/PCAPNG evidence or original historical Canonical SQLite journal referenced by some historical reports. Those gaps are therefore explicitly recorded as `MISSING` rather than inferred away.

## Reuse policy

`provenance/REUSE_MANIFEST.json` is the definitive M0 reuse ledger. Every row is source-hash bound and uses one of:

- `UNCHANGED_REUSE`
- `ADAPTED_REUSE`
- `REIMPLEMENTED_FROM_BEHAVIOR`
- `HISTORICAL_FIXTURE_ONLY`
- `DISCARDED`

The full Game Kernel and carried game data remain byte-preserved where mapped. Coupled legacy services are not copied wholesale merely because they contain useful behavior.

## Historical regressions

`reference/m0/regression_catalog.json` freezes the important R5.142, R5.151, R5.195, R5.196, R5.197 and R5.198 failure families and their exact legacy test/document paths.

Recurring user-visible symptoms are also cataloged, but deliberately without assigning one root cause. A Ready stall, failed turn handoff, invalid cast target, focus loss, or no-action condition must be diagnosed by first divergent boundary rather than by an incident-specific assumption.

## Current live blockers

`reference/m0/live_pending_boundaries.json` records current-client/build, Windows identity/calibration, class/loadout, CRA/ENU lifecycle, bridge, protocol absence semantics, scaling, and physical-action acceptance as `BLOCKED_MISSING_EVIDENCE`.

M0 cannot promote any of these statuses.

## Q0 verifier

Run as a developer tool:

```text
python tools/verify_m0.py
```

To write/update the machine-readable receipt:

```text
python tools/verify_m0.py --write-receipt
```

This is intentionally **not** another user-facing BAT file.

The verifier checks:

1. exact archive SHA-256 identities;
2. every member of each bundled ZIP against its frozen file manifest;
3. the extracted master specification against its own official manifest;
4. that M0 left starting-P66 runtime/config/assets/native/operator launcher files unchanged;
5. that no legacy `anka_platform` package entered `src/`;
6. reuse-mode/hash/limitation consistency;
7. evidence provenance and explicit missing evidence;
8. historical regression references;
9. live-pending fail-closed status;
10. the two-command operator surface.

`tests/test_m0_baseline.py` additionally includes negative/mutation checks, including an independently mutated archive member that must no longer match the frozen oracle.

## What Q0 does not prove

Q0 does **not** certify:

- current Dofus protocol semantics;
- current Windows process/window identity;
- current Unity bridge compatibility;
- current calibration;
- CRA/ENU live fight behavior;
- any physical input action;
- live mission completion.

Those remain for the later gates defined by the definitive master specification.
