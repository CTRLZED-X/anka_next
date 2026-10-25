# M3 — Client identity, calibration and projection (observe-only)

## Scope

M3 builds the fail-closed proof model required *before* physical input exists. It does not accept the current Windows host and does not grant input authority.

## Ownership

`anka_client` owns read-only process/window discovery, configured-name to independently evidenced character/class binding, calibration evidence, Unity bridge projection evidence, loadout/slot evidence and generation invalidation. It contains no keyboard/mouse sender. `anka_execution` remains the only future physical-input authority.

## Generation fence

A client context is coherent only when the same evidence generation proves:

- HWND + PID + process creation generation;
- independently evidenced character and class (CRA=9 / Enutrof=3 for the current target scope);
- foreground/minimized/visibility observation;
- window client size and DPI compatible with a *current-certified* calibration;
- bridge map, map generation and coordinate generation;
- loadout generation bound to the same window generation;
- unique spell-to-slot association for spell projections.

Changes in window generation, dimensions, DPI, map, bridge projection generation, calibration generation or loadout generation invalidate the prior vector. Lost/unknown focus or visibility also invalidates it for physical-action prerequisites.

## Historical calibration

`assets/calibration/shared_ui_1280x649.json` remains provenance-bound to the R5.198 YAML and contains 22 slots plus phase/join/world controls. Its status is `HISTORICAL_COORDINATES_NOT_LIVE_CERTIFIED`; the loader rejects attempts to self-promote that historical file to current certification.

A stored slot coordinate proves only the pixel location of slot N. `LoadoutEvidence` must separately prove which spell currently occupies N and must be fresh and bound to the same client generation.

## Unity bridge

The carried bridge source remains read-only. A bridge report is scoped by PID/process creation, map generation, coordinate generation, client size and projection fingerprints. Source parity/health does not by itself certify the current client build. M3 therefore keeps `BRIDGE_NOT_CURRENT_CERTIFIED` explicit unless a later acceptance stage supplies such evidence.

## Offline completion evidence

The M3 regression matrix covers ambiguous/wrong PID/HWND/generation, class mismatch, size/DPI/map drift, stale/conflicting loadout, focus/minimized/occluded states, slot ambiguity, bridge-generation drift, historical identity lineage and the read-only Unity bridge. All are zero-input tests.

Windows/current-client validation remains a later Q10/Q11 concern and must not be inferred from this offline milestone.
