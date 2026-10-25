# Capture System — P4 offline implementation

Read-only PCAPNG ingestion of Ethernet/IPv4/TCP, selected by explicit configured server ports. The project reuses the legacy R5.198 parser **as an isolated historical transport parser**, with new contracts, size bounds, transport health evaluation, diagnostics and tests. IPv6 selected-port TCP and fragmented IPv4 selected-port evidence are rejected rather than silently omitted. Payloads only exist transiently in memory and are **never included in incident ZIPs**.

`anka_capture.api.inspect_pcapng` returns a metadata-only `CaptureReceipt`. It does **not** establish an account or window identity, reconstruct a complete TCP session, decode a game event, verify a canonical state or send physical input. Even `OBSERVED_NO_DETECTED_GAPS` only means the current basic auditor found no gap; it does **not** certify protocol completeness or live-capture equivalence. The current auditor requires observed SYNs for anchoring and distinguishes unanchored vs unresolved gaps. P5 must verify actual TCP framing and replay parity.

This milestone intentionally has **no live packet sniffing**: Windows/Npcap discovery, process-flow ownership, buffering/drop metrics, and live-vs-offline parity need their own Windows evidence and acceptance. `start.bat` remains blocked.

## P5 read-only Windows capture candidate (host acceptance pending)

P5 adds `live.py` (bounded queue and persistent-loss auditing), `windows_live.py`
(optional explicit-interface Scapy/Npcap sniffer), and `windows_flows.py`
(conservative read-only TCP PID snapshots). Offline fault-injection tests run without
Scapy or Npcap. See `docs/P5_READ_ONLY_WINDOWS_CAPTURE.md`. These components
**do not certify** stream completeness, account identity, protocol compatibility,
or live game control. There is no path from this command to physical input.
