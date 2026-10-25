# P61 — Fail-closed IPv6 TCP fragment evidence completeness

**Date:** 22 October 2026  
**Scope:** saved PCAPNG evidence, Capture → research Protocol → P50/P59 replay; not live runtime.

## Root cause reproduced against P60

`anka_capture.pcapng._reject_selected_ipv6_tcp` walks IPv6 extension headers, but before P61 it advanced past a Fragment header without checking its offset/M (more fragments) bit. A **non-initial IPv6 TCP fragment has no TCP header and no ports**; the parser interpreted its opaque fragment body as TCP ports, and if those arbitrary bytes did not match the selected server port it silently returned `None`. The captured traffic disappeared from selected-flow analysis. In a mixed capture, P50 could then report `CANDIDATES_ONLY` despite an unclassifiable IPv6 TCP fragment. The first fragment with M=1 and an unrelated port could also disappear without marking evidence incomplete.

Before the fix, **five** new P61 tests failed against the P60 implementation, including mixed IPv4/fragment capture inspection, IPv6 destination-option + fragment, and P50 flow-inventory quarantine.

## Implementation

When parsing an IPv6 Fragment header, the capture path now reads and verifies the actual fragment-offset field, M bit, and reserved flags. A **non-atomic** fragment whose Next Header is TCP or another potentially TCP-bearing extension/opaque header is rejected without guessing ports or assembling a false continuous stream. Atomic fragments (offset=0, M=0) still proceed to supported Next Header classification. Explicit IPv6 fragmented UDP/ICMPv6 traffic is not mistaken for TCP. Unsupported **selected-port** IPv6 TCP remains rejected as before, since the current live capture backend supports IPv4 only.

The error is translated to the existing privacy-safe `CAPTURE_CONTENT_INVALID` / fragment diagnostic. It propagates through P50 flow inventory and P59 file-backed admission, preventing incomplete captures from silently appearing sufficient. P61 does not add IPv6 support, TCP reassembly, live driver certification, Canonical admission, or a physical input path.

`anka_app.ipv6_fragment_smoke` runs an obviously synthetic PCAPNG with normal selected IPv4 plus a non-initial IPv6 TCP fragment during **existing `check` and `setup` preflight**; acceptance requires a fail-closed capture error. This creates no extra user-facing BAT script.

## Tests and release gates

- 14 P61 tests PASS: non-initial TCP fragments, extension headers, truncated fragment payload, first fragments with M=1, P50 flow inventory, reserved bits, explicit fragmented UDP, atomic/unfragmented unrelated IPv6, and normal preflight smoke.
- Focused capture / protocol / multi-flow / provenance group: **194 tests + 22 subtests PASS**.
- Entire checkpointed module-isolated test inventory: **88/88 modules, 1,522 unittest methods PASS**.
- Source fingerprint: `c46332198e1686d8451aca987792b2a205fe544f0261355f14812a0ecc8ed6c3`.
- `check` and `setup` return 0; `start` intentionally returns 40 / `LIVE_RUNTIME_NOT_IMPLEMENTED` with a validated incident ZIP.
- Architecture stays at 13 packages; 165 retained reference assets.

## Remaining acceptance blockers

No independently verified current Dofus client protocol build, capture driver loss visibility, Windows-process-to-window-to-character/breed witness, or authoritative event settlement is available here. A file SHA is not an authenticated packet-origin attestation. Estimated roadmap scope **92% (subjective)**; complete live CRA/ENU mission acceptance **0%**. Do not reinterpret this fail-closed capture improvement as completion of live gameplay infrastructure.
