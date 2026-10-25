# P25 — Passive Windows Host Readiness Evidence

**Scope:** integrate existing read-only Windows Client and TCP process metadata into automatic `setup.bat` and `start.bat` observations. **This is not Windows acceptance or gameplay certification.**

## Why this milestone matters

Previous versions displayed hard-coded readiness blockers while collecting no per-invocation evidence about whether Dofus window candidates, configured network capture prerequisites, or historical calibration geometry were present. Failure incidents were consequently less useful on the operator's Windows host.

P25 introduces `anka_app.host_readiness.probe_host`, composed from existing independent `anka_client` and `anka_capture` APIs. No system imports another system's private source. The result is a privacy-minimized set of diagnostic **categories and aggregate counts**, not a permission to click.

## Automatic workflow

- `setup.bat`: install/check the existing offline dependencies, asset hashes and architecture boundaries; collect passive host snapshot; run the existing synthetic smoke checks. **Game windows are optional at setup time**; missing candidates do not fail a valid offline setup.
- `start.bat`: run fast preflight, architecture and readiness checks; collect the host snapshot; export the incident with its blocking reasons; **remain disabled** until real current-build evidence and physical input prerequisites are implemented and independently verified.
- No additional BAT commands or dashboard were introduced. Developer tests still run via Python in the source tree.

## What the probe can observe

| Item | Evidence it records | What it does **not** prove |
|---|---|---|
| Client inventory | Candidate window count, named-account states and categorical identity errors | That the actual character or class is known without a trusted evidence provider |
| Window geometry | Count matching the historical 1280×649 reference, mismatch/minimized/DPI-uncertain codes | That a spell bar, Ready button or world cell uses unchanged coordinates |
| Capture settings | Boolean presence of server ports and interface | That the chosen interface/ports are correct or that loss-free packet capture is possible |
| Optional Scapy | Installed/unavailable (module-presence check only) | That Npcap works or that packet drops are observable |
| Windows TCP table | Number of candidate window processes with established TCP connections | That their flows are attributable to a character or a server event |
| Diagnostics | `readiness.host_probe_completed` in setup/start evidence | That the game is ready for input |

The aggregate TCP count is **restricted to PIDs already discovered as configured game-window candidates**. It cannot accidentally count arbitrary processes as proof of game connectivity. Network endpoints, titles, raw packet data and configuration names are not copied into the report.

## Safety guarantees

- No mouse/keyboard, window focus, packet capture, packet send or protocol decoding takes place in the host probe.
- Host probe exceptions produce typed evidence gaps rather than raw paths, IPs or credentials.
- Windows acceptance remains **pending**: Linux tests use injected inventory/TCP snapshots and cannot validate actual Windows behavior.
- Both identity and calibration remain unverified; `live_certified`, `physical_input_permitted` and `account_binding_verified` remain `false` regardless of positive observations.
- The pre-existing `assess_live_readiness()` hard blockers are unchanged and cannot be bypassed by user configuration or injected diagnostics.

## Verification and next gates

- 13 new P25 tests check missing windows, duplicate/ambiguous account hints, minimized/mismatched geometry, capture dependencies, TCP attribution scope, failed probes, privacy and integration into setup/start.
- 739 tests passed across eight bounded, individually launched groups; the multi-shard verifier's occasional command-level stall is **not** claimed permanently fixed.
- Windows-native Win32 inventory, TCP table, Scapy/Npcap capture, actual DPI/calibration and current-build identity-provider acceptance are still required.
- Before allowing a live session: certify the current build and semantics, demonstrate authoritative Canonical admission, verify calibrated coordinates and account identity on Windows, integrate the physical input and outcome acknowledgements, and pass real CRA/ENU end-to-end acceptance.
