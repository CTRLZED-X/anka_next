# P26 — Read-only Windows ingress evidence on `start`

**Release scope:** P26 connects the existing experimental Npcap/Scapy read-only capture system to the *actual* `start.bat` path. It does not add an operator command or enable game input. This milestone was exercised on Linux with simulated Windows APIs; actual Windows/Npcap acceptance remains **pending**.

## Why this matters

Before P26, the P25 host probe showed only whether a window candidate, a Scapy module and configuration values existed. The previously implemented `anka_capture.windows_live` sampling backend was not called by the normal startup path. Consequently, `start.bat` could not produce even a basic bounded observation of real transport health. P26 closes that integration gap without claiming that observed packets are complete or semantically decoded.

## Operator workflow (unchanged — only two commands)

1. Set `config/user.json` capture `server_ports` and `interface` **only to actual known, authorized game traffic values**. Do not guess an interface, automatically scan all devices, or capture traffic belonging to unrelated users. Leave ports empty/interface null to disable sampling. `duration_seconds` config remains 1–60 for developer sampling; the automatic startup trial is capped to **10 seconds**.
2. Run `setup.bat`. If ports and interface are explicitly configured, it attempts to install the optional Scapy dependency from `requirements-windows-capture.txt` into the project's virtual environment. An optional installation failure is written to the setup bootstrap log; it does not disguise a successful offline foundation as a certified capture backend. **Npcap itself is an external Windows driver requiring separate installation and permission checks.**
3. Run `start.bat`. It performs the existing safety checks and passive host probe. On Windows, it attempts a read-only sample only if an account-window *candidate* exists, the capture values are explicitly configured, and Scapy is detected. Afterward it **still refuses live execution** (`LIVE_RUNTIME_NOT_IMPLEMENTED`, exit code 40) and exports the normal incident ZIP.

No raw packet bytes, local/remote addresses, interface names, window titles, HWNDs, PIDs or player names are written to the P26 sample report. Only bounded counters, categorical reasons and provisional counts are recorded. No file containing raw PCAP data is created by this feature; therefore the P26 report alone cannot reverse-engineer a new protocol build.

## Architecture

- `anka_app.ingress_readiness`: composition-only coordinator; setup/start may call it. It does not provide any game-control API.
- `anka_client.win32_inventory`: existing read-only native window observations; account identity **unattested**.
- `anka_capture.windows_live`: existing optional Npcap/Scapy bounded ingress and transport auditor. No packet send or physical input.
- `anka_capture.windows_flows`: existing TCP table metadata; cross-snapshot flow association is a **provisional process hint**, not account proof.
- `anka_observability`: passive, privacy-filtered incident events and bundles.

A stable TCP owner hint requires: complete before/after window inventories, unchanged HWND+PID+process-creation generation, no competing windows using the same PID in **either** inventory, and the same established TCP endpoint ownership in **both** before/after snapshots. A transient connection that cannot satisfy these constraints remains `UNMATCHED`, not falsely attributed to CRA/ENU.

## Failure behavior

| Condition | Outcome |
|---|---|
| Non-Windows environment | `SKIPPED: WINDOWS_ONLY` |
| Ports or interface missing | `SKIPPED: CAPTURE_NOT_EXPLICITLY_CONFIGURED` |
| No game window candidate | `SKIPPED: GAME_WINDOW_CANDIDATE_MISSING` |
| Window found, no configured account candidate | `SKIPPED: NO_CONFIGURED_ACCOUNT_WINDOW_CANDIDATE` |
| Scapy absent | `SKIPPED: OPTIONAL_CAPTURE_DEPENDENCY_MISSING` |
| Npcap/sniffer exception | `FAILED: CAPTURE_SAMPLE_FAILED`, class-only diagnostic |
| Malformed, contradictory or forged capture receipt | `FAILED`, no authority promotion |
| Capture packet gap or dropped queue item | Categorical transport/loss evidence, **never** `live_certified` |
| Missing or inconsistent process/window/TCP snapshots | Flow attribution `UNAVAILABLE` or `UNMATCHED` |

The report always sets `live_certified=false`, `account_binding_verified=false`, `physical_input_permitted=false`, `packet_payload_persisted=false`. Zero Python queue drops cannot establish zero Npcap/driver loss; the driver-loss status remains `UNKNOWN`.

## Tests and acceptance

- 36 new P26 tests, including source-to-report privacy allowlisting, contradictory loss counters, PID/window reuse and ambiguity, missing configuration/dependencies, sample exception sanitization, real `start` command boundary, fake Windows sampler composition and opt-in installer condition.
- Total suite: **775 collected automated test methods** from 42 test files. All passed on Linux, but because the intermittent combined verifier stalled, this result is assembled from three passing multi-module groups and the remaining individually bounded test modules. The combined verifier is **not certified as fixed**.
- The native Windows BAT interpreter, Scapy/Npcap and current Dofus process have **not** been exercised. The source can only be marked **offline verified, Windows acceptance pending**.

## Next required acceptance

Run setup/start on the actual Windows machine with accurate interface and ports, verify Win32 inventory and optional Scapy/Npcap behavior, collect only authorized protocol evidence for the exact Dofus client build, independently certify required live message semantics and flow identity, and then implement authoritative Canonical admission. Gameplay execution remains disabled until the larger chain passes end-to-end tests.
