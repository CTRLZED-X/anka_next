# P48 — Actual CapturePoll → P6 framing → P47 historical replay, research only

**Date:** 21 October 2026  
**Baseline:** P47 complete project  
**Live status:** BLOCKED BY DESIGN, zero authoritative events or physical input

## Why this milestone was chosen

P47 consumed manually constructed `WireMessage` tuples and could find lifecycle/combat research inconsistencies, but its direct callers could supply a curated clean subset. The actual Capture/Transport and P6 TCP framing path had not been exercised **together** with historical semantic research. This gap matters for unknown frames, missing SYNs, incomplete length-prefixed frames, poll/drop signals, multiple account flows and decoder provenance.

P48 adds a concrete cross-system integration in `anka_app/historical_transport_bridge.py` that consumes real `CapturePoll` objects and passes their bytes through the *existing production-read-only* `ProtocolInspector` and its `FrameBuffer`/`extract_any` utilities, then calls the established P47 `replay_historical_server_stream` on the chosen one-flow messages. It **does not reimplement TCP parsing or protocol decoding** and does not replace any already working component. The `anka_app` composition package may depend on both Capture and Protocol; the separate domain packages remain independent.

The integration is strictly offline/research. `LegacyFightScope` selects a SHA-256 flow identity, generation and historical fight build, but is *caller-supplied*, **not proof of Windows process, player/class or account-to-flow ownership**. A complete uninterrupted source capture, current-build adapter, independently witnessed semantics, canonical authority, and physical action certification are still missing.

## Exact new implementation

- `src/anka_app/historical_transport_bridge.py`: immutable `HistoricalTransportResearch` receipt, bounded poll/segment/wire budgets and one-flow selected historical timeline; associated transport and protocol statuses, first issue and first hard blocker.
- `src/anka_app/historical_transport_offline.py`: tiny reproducible *synthetic* TCP SYN/framed Any/lifecycle fixture with successful, driver-unknown and truncated-frame cases; remains read-only and ephemeral.
- `src/anka_app/cli.py`: invokes P48 fixture as part of normal `setup`/`check` preflight and emits privacy-safe high-level diagnostic status; no new operator command or BAT.
- `tests/test_p48_capture_to_historical_research.py`: actual segment/byte framing, interleaving, foreign flows, loss, invalid stream/segment, unknown/missing envelope, generation and schema negative checks.
- `tests/test_p48_historical_transport_setup_smoke.py`: operator preflight contract.

### Data path

```text
CapturedTcpSegment[] / CapturePoll (selected by caller; identity NOT proven)
   ├─ TransportAuditor (SYN, sequence, visible gaps, reconnection, ordering)
   ├─ ProtocolInspector (same existing P6 length framing / protobuf Any)
   │    └─ WireMessage stream with exact packet ordinal, index, generation
   └─ source-flow selection + P47 historical one-flow lifecycle/combat replay
         └─ HistoricalTransportResearch: RESEARCH/PARTIAL/BLOCKED
                (authoritative commits = 0, physical input = false)
```

No raw payload or IP address is added to the receipt or normal diagnostics. A foreign game flow may be seen in a multi-account capture but cannot be counted as the selected actor's evidence. This is a **scope check**, not an actor identity attestation.

### Falsified defects and decisions

1. **Previously invisible structurally valid frame:** P6 correctly counted a frame without a recognizable Ankama Any envelope but did not expose it in the `WireMessage` callback. If P48 only examined the callback, the historical replay could report `RESEARCH_TRANSPORT_ONLY` for a semantically incomplete subset. A regression was written **before** the fix (red), then P48 now emits `P48_NON_GAME_OR_UNCLASSIFIED_FRAME` and `PARTIAL_EVIDENCE`. It does not invent a new message meaning.
2. **Malformed segment inside valid poll:** `CapturePoll` checks tuple size but does not enforce element type. A research client could pass `('not-a-tcp-segment',)` and previously the transport auditor would raise an unhandled `AttributeError`. A regression reproduced this (red); P48 now emits a typed `P48_SEGMENT_TYPE_INVALID` hard blocker.
3. The direct P47 replay never certified complete source capture, but had no parent transport proof. P48 now checks poll driver-drop visibility, source generation consistency, actual packet order, SYN/seq/reassembly gaps, incomplete frames and wrong build *before* giving a local clean research classification.
4. Positive/negative control: source that is split correctly across TCP packets remains decodable; an unrelated flow cannot contaminate the selected fight, and a recognized frame with unknown semantics remains a *partial gap* rather than being erased.

### What P48 deliberately does NOT establish

- A clean `TransportAuditor` status means **no detected selected gaps**, not that the full connection, both directions, or packet capture is complete. `source_completeness_verified` is permanently `false` in this historical receipt.
- `CapturePoll.exhausted` signifies a bounded observation period, not a complete Dofus session or FIN capture.
- Any/Protobuf recognition is not server-side cast/HP/AP/MP confirmation.
- An archived adapter for Dofus 3.7.10.10 does not certify a newer current client.
- A caller-supplied fight/account `scope` is not authenticated Windows PID/HWND→network ownership.
- Not safe for actionable decisions, Canonical commits, victory recognition or clicks. `start` still exits **40** with a validated diagnostic bundle.

## Verification performed

- Dedicated P48 and direct P47/Capture/Protocol suites: **84 pytest methods + 24 subtests PASS** (source bound to P48 working tree).
- Wider relevant Protocol/P28–P48/Capture regression selection, excluding P37's slow subprocess-verifier module: **557 pytest methods + 142 subtests PASS**; **1 nonfatal warning**.
- `python -m anka_app.cli check`: **PASS**, 13 packages audited, 165 reused assets intact, and P48 synthetic transport guards executed.
- `python -m anka_app.cli setup`: **PASS**, same safety gates, plus existing integration smoke.
- `python -m anka_app.cli start`: **intentionally BLOCKED**, exit **40** / `LIVE_RUNTIME_NOT_IMPLEMENTED`, generated diagnostic ZIP integrity **PASS**.
- **Complete inherited suite:** NOT fully verified; a broader 70-module one-process run exceeded the execution window. Do not claim full PASS from a partial progress bar. The previous P47 full-suite limitations remain historical.

## Next high-value work

Authentic, **current-client** PCAPNG+account/process/flow-attested witness oracles and exact-build adapter qualification. Until supplied, useful source improvements are limited to failure containment and trace completeness—not inventing gameplay damage/turn/effect evidence or flipping current live-readiness flags. Once real captures exist, this P48 bridge can be exercised with data from the actual PCAPNG intake under independent proof requirements, then assessed for production Canonical admission as a separate milestone.

**Estimated weighted development-scope coverage:** 92% (previous 91%, subjective, not measured product quality).  **Real complete CRA/ENU current-client live acceptance:** 0%.
