# P51 — Windows process / TCP owner snapshot consistency

Date: 2026-10-21. Scope: **read-only, privacy-preserving, offline-verified**, not live-ready.

## Finding: snapshot intersection could erase contradictory ownership

P26 samples candidate game windows and the Windows IPv4 TCP owner table before and after a short passive capture. The prior `stable_flow_hints` intersected rows on `(endpoints, pid, state)` before checking for ambiguous ownership. Example: before = {endpoint → PID A, endpoint → PID B}, after = {endpoint → PID A}. The intersection silently removed PID B and returned a single `PROVISIONAL` PID A, even though the **first** snapshot disagreed. This could incorrectly elevate a contaminated research flow hint. Other missing checks included process-image changes, minimized/geometry changes, stale or reversed scan clocks, and duplicate window handles.

## Implemented correction

Existing composition API is preserved: `anka_app.ingress_readiness.stable_flow_hints(before_windows, after_windows, before_tcp, after_tcp, flow_keys)`.

- Validates both raw owner tables **before** correlating them; any duplicate/contradictory owner for a selected endpoint is `AMBIGUOUS` even if the extra row disappears at the second boundary.
- Requires the same single *established* `(endpoint, pid, state=5)` at both boundaries and the same unique window `(HWND, PID, process creation FILETIME)`.
- Verifies trusted executable basename, positive stable client geometry, unchanged DPI and non-minimized status. Generation changes and unmatched processes cannot become provisional ownership hints.
- Detects duplicate HWND, window scan failures, reversed or overlong observation spans and invalid or oversized flow selectors. Every uncertainty either reports categorical `UNMATCHED`/`AMBIGUOUS` or returns `UNAVAILABLE`.
- Preserves privacy: no IP, port, HWND, PID, process path, title, character identity, account or flow token is emitted in the stable diagnostic result. The existing `_safe_attribution` further restricts the capture receipt.
- Adds 28 adversarial tests + two source-bound preflight tests. A three-case synthetic owner consistency smoke runs automatically from `check` and `setup` with no extra BAT files.

A `PROVISIONAL` result **only** supports an ephemeral process/endpoint **hint**. No name, breed, CRA/ENU identity, per-packet delivery, Windows/Npcap driver integrity, account binding, authoritative Canonical state, current-client semantic certification, or permission to click is granted. The Windows TCP API only covers **IPv4** in the existing implementation; IPv6 and OS validation remain future tests. Snapshot sampling is non-atomic and cannot prove continuous ownership. Synthetic positive smoke cases are not Windows acceptance.

## Verification

- Check + setup: 0; expected start refusal: 40 (`LIVE_RUNTIME_NOT_IMPLEMENTED`). The generated incident ZIP verifies.
- 77/77 isolated source-bound regression modules: **1,336 tests passed**, all via the checkpointed P37 verifier (source fingerprint in P51 receipt).
- 30 P51 test methods; 36 inherited P26 passive ingress methods pass.
- 13 architecture packages; 267 source modules; 165 source reference assets preserved.
- ZIP: full ANKA_NEXT source, docs/tests/receipt, both and **only** `setup.bat` / `start.bat` root operators, no runtime evidence/caches.

## Next evidence-driven milestone

Use *authentic Windows/current-client captures* to establish independent, time-scoped process↔socket↔window↔CRA/ENU witnesses. Then verify the current protocol adapter and conservative Canonical admission. Do not infer client ownership merely from window titles or transport endpoints. No physical input, production turn arbitration or victory accounting is enabled by P51.
