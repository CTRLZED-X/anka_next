# System 10 — Client (`anka_client`)

## Purpose

Client proves which physical Windows game client is being controlled and maps semantic UI/game targets into valid current screen interaction evidence.

## Responsibilities

- discover candidate Dofus processes/windows;
- identify PID + creation generation, HWND and window state;
- bind configured character/account to a client using authoritative evidence;
- obtain/verify live class/breed and relevant loadout where supported;
- manage Unity bridge/native projection observations;
- load/version calibration profiles;
- translate game cell/UI semantic targets to screen coordinates;
- verify focus, client size/DPI/viewport/calibration freshness;
- invalidate projections on relevant changes.

## Reused reference assets

R5.198 includes a 1280×649 profile with 22 spell slots, `PHASE_BUTTON` (Ready/End Turn), `JOIN_FIGHT` and world directions. Those are versioned reference data, not universal coordinates.

## Separation of geometry

- Kernel answers whether a semantic game-cell action is legal.
- Client answers whether a current physical window can interact with that semantic target and how.

A pixel coordinate cannot establish walkability/LoS; a game cell ID cannot establish current pixel location.

## Spell-slot proof

A stored slot coordinate proves only *where slot N is*. It does not prove *which spell is currently in slot N*. Cast admission needs appropriate loadout/slot evidence.

## Revalidation

Invalidate/recheck on PID/HWND restart, bridge generation, map/scene, window size/DPI, viewport, calibration update, loadout change or focus/foreground transition relevant to input.

## Dependencies

Contracts + OS/native libraries. No Decision/Workflow internals. It does not send physical input; Execution owns drivers.

## Tests

- identical/similar titles;
- PID/HWND reuse;
- renamed character/title hints;
- wrong breed;
- loadout/slot mismatch;
- changed window size/DPI;
- stale bridge/map projection;
- minimized/occluded/unfocused cases;
- screen coordinate out of bounds;
- zero input on ambiguous identity;
- Windows acceptance on exact target host.

