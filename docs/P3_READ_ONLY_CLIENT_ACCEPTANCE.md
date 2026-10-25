# P3 — Read-only Client Discovery / Identity Boundary

**Implemented:** 20 October 2026. **Status:** deterministic offline acceptance passed; native Win32 smoke and trusted live evidence **pending**. Never authorize physical input from these results.

## Reuse and boundary decisions

- Legacy R5.198 `client_inventory.py` inspired enumeration, process creation-time identity and read-only inventory.
- New package code is **not** a copy of legacy input driver: Windows-only read-only `EnumWindows`, process-image lookup, process creation time, client-size, minimized state and DPI observation.
- `anka_contracts.client` owns immutable DTOs and public inventory/identity ports; `anka_client.discovery` is a deterministic pure policy layer. A fake inventory and fake identity provider let tests run without Windows or Dofus.
- Character **name is a search hint**, not an authoritative proof of game identity. Class **must** come from validated current-build canonical or Unity-bridge evidence, with exact HWND/PID/process-creation time, freshness checks and matching character name.
- Duplicate windows, shared windows, expired/contradictory evidence, unknown breed, untrusted process image, process generation change, incomplete inventory and minimized windows are reported as BLOCKED. No discovery method clicks, focuses, restores, presses, or moves a cursor.
- A trusted `CharacterEvidenceProvider` has **not** yet been implemented: runtime inspection may report PENDING candidates, not matched accounts. Test fixtures can exercise identity matching only offline.
- A matched character/class still has `input_certified=false`: viewport and screen projection, DPI, current-build protocol, calibration and spell-slot binding require separate proof.

## Commands

`clients.bat` (Windows) or `PYTHONPATH=src python -m anka_app.cli clients` (offline): read-only account inventory and structured diagnostic event. The command is observational and should return `ANKA_STATUS=NOT_CERTIFIED` or `NOT_AVAILABLE`; never `LIVE_READY`.

`check.bat`, `verify.bat`, `start.bat`, and all old P0/P1 commands remain available. **`start.bat` still refuses live execution** and emits a blocked-incident ZIP.

### Windows smoke checklist (must be performed on the real host)

1. Run `check.bat`, `verify.bat`; save exit codes and startup logs. Ensure Python 3.13 is available.
2. With Dofus closed, run `clients.bat` and expect no proven accounts, no input, and diagnostics under `runtime/runs/`.
3. Open one visible CRA and one Enutrof account; use `clients.bat` again, checking that exact process generation and candidate window counts are captured. Window titles vary by client build; a title change must never turn into false certification.
4. Change window size and DPI, minimize a client, close and reopen it, and test duplicate-looking titles. Expect diagnostic mismatches, blocked/pending identity and no input.
5. Confirm the launcher and diagnostics are usable on Windows, that `start.bat` remains blocked, and that no mouse/keyboard events were sent.
6. Archive a sanitized GPT incident ZIP for any failure. Do not upload raw title/process-path dumps or other private Windows data without review.

## Why real character/class attestation is pending

A Windows title or executable name can be spoofed; even a correct-looking PID may have been reused after a process restart. The future canonical/bridge identity provider must itself be certified against the **exact current client build** and must correlate a live account and class to the same process/window generation. Without that, the Client System can discover candidates but must not claim to know whether a window represents CRA or Enutrof.

## Offline acceptance test scope

- Contract/detection: exact process generation, supported executable basename, tokenized name matching, correct distinct accounts, title-independent *attested* matching, shared-window rejection.
- Fault injection: duplicate HWND, wrong class, wrong player, stale/future identity, unsupported evidence sources, changed process creation time, inaccessible window, minimized/invalid geometry, ambiguous matching and repeated evidence.
- Geometry: different viewport, missing DPI, minimized window, exact reference viewport still marked uncertified.
- Diagnostics: identity partial-evidence matrix and checksum verified; `anka_client` static boundary forbids physical-input calls.

Tests are real Python contract/policy tests, **not** proof that Win32 discovery or game protocol succeeds on an actual Windows session. No live input, network capture or new protocol decoder is present in this release.
