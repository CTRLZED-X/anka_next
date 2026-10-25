# P4 — Offline Capture System acceptance and next gates

## Implemented and verified

- Physical package is `src/anka_capture`, not inside `anka_app`. It depends only on `anka_contracts` and Python standard library. No imports of `anka_protocol`, canonical, kernel, decision, execution, or coordination.
- `CapturedTcpSegment` is a transport-only DTO. Its packet data and IP-based flow ID are in-memory and excluded from default representations. `CaptureReceipt` and diagnostic records contain **counts, hashes, statuses and loss indicators, not payload or IPs**.
- Supported offline input: max 32 MiB PCAPNG, Ethernet linktype 1, IPv4/TCP with optional 1–2 VLAN layers. Explicit selected server ports are mandatory to read real evidence. Unsupported selected IPv6 TCP, fragmented selected IPv4/TCP, snaplen truncation, invalid block trailers, unknown interfaces, wrong endian marker and unsupported linktypes are rejected rather than silently overlooked.
- Capture is a one-read immutable snapshot: the SHA-256 and parsed bytes refer to the same file contents. A bound ensures operator-provided evidence cannot be loaded without a size limit.
- Basic TCP transport audit: packet ordering, direction, SYN-anchored start, separate reconnect generations, retransmissions, out-of-order intervals, known unresolved gaps and segment-size limits. Flow identifiers/endpoints are not disclosed in receipts. The auditor does **not** claim exact TCP payload reassembly, framing or a guaranteed lossless network trace.
- Diagnostics: `capture.replay_inspected`, `capture.evidence_not_certified`, `capture.replay_rejected` with allowlisted reason codes. No raw packets/paths in an auto-exported GPT incident ZIP.
- `capture_demo.bat` only plays bundled synthetic data. `capture.bat <path>` requires explicit `capture.server_ports` in `config/user.json`. `start.bat` remains blocked by `LIVE_RUNTIME_NOT_IMPLEMENTED`.

## Explicit limits

- PCAPNG parsing is **offline**; no operating-system NIC capture or Scapy/Npcap/tshark integration is active.
- A SYN-anchored stream with no detected gaps may still be missing a packet before capture began, an unsupported transport representation or receive-side data. Therefore `OBSERVED_NO_DETECTED_GAPS` **never** proves live parity. It is particularly not proof of game-message framing, protocol decoding, character/class evidence, or legal physical action.
- Capture has **no account/character attribution** until the Client System and process/connection ownership are independently verified. Endpoints/ports are not sufficient.
- 32 MiB offline cap is intentionally conservative; larger captures require a future bounded streaming parser, not lifting limits blindly.
- pcap files (as distinct from pcapng), Linux cooked linktype, selected IPv6/TCP and IPv4 fragmentation are intentionally unsupported in this milestone.

## Windows/live acceptance requirements (NOT PASSED)

1. Verify Windows actual launch scripts, Python dependency installation, native inventory and absence of mouse/keyboard actions.
2. Prove installed Npcap/driver permissions (or chosen capture backend) and explicit ownership of each flow to a verified process generation/account.
3. Implement and test bounded live queues with drop/overflow/blocked-consumer evidence (`CapturePoll` contract), reconnect generation and interface restart handling.
4. Record a known consented test trace from the current client and independently compare live capture segmentation with its offline replay, including dropped/reordered/split packets and both directions.
5. Verify protocol adapter current-build qualification separately (P5). Only then can decoded events be treated as live state inputs.

## Automated checks

Run `verify.bat` on Windows (or `PYTHONPATH=src python -m unittest discover -s tests -q` in a compatible Python 3.13 environment). Target fixtures deliberately falsify a healthy trace by changing endian, snaplen, linktype, fragment flags, order, SYN presence, source size, unknown config ports, reconnect generation or evidence storage. All mandatory checks must pass before expanding capture functionality.
