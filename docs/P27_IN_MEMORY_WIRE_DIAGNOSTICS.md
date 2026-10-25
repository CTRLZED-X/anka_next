# P27 — Capture-to-Protocol wire observations during Windows startup

**Scope:** Implementation for passive, explicitly configured, short Windows/Npcap capture sampling. No real Windows/Npcap machine was available for validation. This is **not current-client semantic decoding** or a gameplay session.

## Problem addressed

P26 recorded transport counters but discarded the in-memory payload before `anka_protocol` could inspect whether complete protobuf frames were visible. Consequently, startup diagnostics did not distinguish "transport observed" from "recognizable protocol envelopes observed." The P27 implementation connects these already separate systems through `anka_app.ingress_readiness`, without adding package-to-package imports.

## Changes

1. `anka_capture.windows_live.capture_bounded_sample` accepts an optional `on_poll(CapturePoll)` callback. It retains existing bounded queues, cleanup on failure, and loss accounting. It does not write payload bytes.
2. `anka_app.ingress_readiness._windows_sample` constructs the existing historical, read-only `ProtocolInspector` and feeds it the captured poll batches **in memory**. The inspector is explicitly asked to observe `UNVERIFIED_CURRENT_CLIENT`, preventing a historical build from being accidentally represented as current.
3. The `start` diagnostic receipt includes an allowlisted `protocol_wire` object: number of segments, framed Any messages, historical-catalog matches, unknown message counts, direction mismatches, quarantined streams, and packet-loss visibility. Raw names, protobuf bodies, TCP addresses, ports, character identities, and flow IDs never enter the incident report.
4. If polling misses messages, there is a TCP gap, the Scapy driver loss counters are unknown, or the callback is not called, the report remains incomplete/uncertified and never enables Canonical admission or execution. Absence of protocol evidence is shown as `NOT_OBSERVED` rather than silently accepted.
5. No new `.bat` files, dashboard, configuration fields, kernel changes, or physical input.

## Important limitations

- The existing historical wire catalog is not evidence for the current Dofus build. Names and counts only identify *potential differences from an old reference*, not independently proven protocol drift or gameplay semantics.
- Scapy `AsyncSniffer` does not expose reliable Npcap driver drop accounting here. A queue with zero observed drops still does not prove packet completeness.
- A short sample can begin midstream without a TCP SYN. This must not be considered a complete stream. The protocol inspector distinguishes unanchored/quarantined streams.
- This feature **does not retain raw packet bytes**. It cannot alone reverse-engineer unknown fields or create a new fully qualified decoder. That still requires a separately supplied, deliberately captured current-client evidence pack and explicit verification.
- Tests run on Linux using injected Windows API snapshots and synthetic capture polls. Native Windows/Npcap execution remains pending.
- Live gameplay is intentionally blocked at the `start` gate.

## Verification requirements

- All prior P26 tests remain green, including `test_p26_passive_ingress.py`.
- New `test_p27_live_wire_observation.py` verifies callback integration, cleanup, framing, historical-only classification, loss, reset, source change, forensic redaction, Canonical non-admission, count-provenance checks, Windows composition, and two BAT launchers.
- Architecture import guard remains green; `anka_capture` does not import `anka_protocol` and `anka_protocol` does not import `anka_capture` implementation code.
- A fresh extraction must pass startup preflight, targeted regressions and integrity checks.
- A full combined test-suite run may still suffer the previously documented intermittent timeout; do **not** conceal or rename that issue as fixed.

## Only operator commands

`setup.bat` and `start.bat` remain the two operator-facing Windows entry points. Other tests remain developer-only Python code.
