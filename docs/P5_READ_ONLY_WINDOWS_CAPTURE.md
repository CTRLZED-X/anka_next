# P5 — Read-only Windows capture: design, restrictions, and qualification

**Scope:** This milestone implements a *candidate* Windows packet-capture adapter. Offline behavior was tested with simulated sniffers, synthetic packets and transport faults. It **has not been executed on a Windows/Npcap game host**. `start.bat` remains blocked; no action engine has been enabled.

## How to use later, for a read-only diagnostic capture

1. Run `setup.bat` on Windows. Optional: install Npcap from its official installer, then run `setup_capture_windows.bat` to install Scapy only into ANKA's virtual environment.
2. Edit `config/user.json` -> `capture.server_ports` and `capture.interface` (an exact local Npcap interface name, not an account name). `capture.duration_seconds` must be 1–60. Do not guess game server ports or interface names. Never capture traffic belonging to other users or machines without authorization.
3. Run `capture_live.bat` to observe a short sample. It collects no input, does not send packets, and does not start any game bot.
4. Read the `ANKA_EVIDENCE` folder or generated incident ZIP. Output is **metadata only**: queue loss counts, TCP continuity symptoms, startup errors, candidate process-flow match counts, and missing-evidence flags.

### Important distinctions

- **Queue dropped = 0** only means the bounded Python queue observed no overflow. It **does not prove** no driver loss or no missing start-of-stream packet. `driver_loss_visibility=UNKNOWN` always until a separately certified Npcap stats API is integrated.
- **A unique TCP PID match is not character identity.** Windows TCP ownership snapshots are point-in-time observations and cannot authenticate a particular account, class, Unity bridge, or process generation on their own. Candidate attribution is labeled `PROVISIONAL`; there is *no* execution authorization.
- TCP continuity is uncertain without the initial SYN in each direction or when gaps/reordering remain. Live samples are observational; they do not claim current protocol compatibility.
- Addresses, port pairs, raw payloads, credentials, and PCAP contents are not written to diagnostic bundles. A random per-capture salt prevents stable cross-run linkage of flow fingerprints.
- The memory queue bounds the retained payloads. Once a packet is polled, only transport **metadata** survives; packets are not archived for protocol replay in this milestone.

## Internal separation

| File | Responsibility |
|---|---|
| `anka_capture/live.py` | Bounded producer/consumer, cumulative loss, metadata-only online transport auditing |
| `anka_capture/windows_live.py` | Optional Scapy/Npcap adapter, explicit BPF, ephemeral endpoint tokens, no input |
| `anka_capture/windows_flows.py` | Win32 IP Helper TCP_OWNER_PID snapshot, conservatively correlated with window inventory |
| `anka_contracts/capture.py` | Stable poll boundary, driver-loss-visibility evidence separate from queue loss |
| `anka_app/cli.py` | Composition root; `capture-live` is isolated from `start` |

## Mandatory host acceptance before claims of live readiness

- Capture a synthetic TCP exchange on Windows and verify source start/stop, filter correctness, byte-exact ingest, queue overflow evidence, broken-interface failures, and clean diagnostics.
- Exercise multiple game windows in parallel and confirm PID-to-flow candidates do not become authoritative without independent player/class evidence; test PID and HWND reuse, window restarts, reconnects and dropped packets.
- Verify supported link layers, IPv4/IPv6 handling, NIC offload behavior, driver packet drop visibility, and performance under representative packet volume; if unhandled, disable affected capabilities.
- Compare live samples against independent offline PCAPNG recordings from the **same** packets, with independently prepared expected output; do not use the same parser as its own oracle.
- Validate network packet collection against applicable consent and privacy restrictions.
- Keep the separate protocol, canonical, decision and execution milestones blocked until their acceptance evidence exists.

## External API references

- Microsoft `GetExtendedTcpTable`: https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
- Npcap `pcap_stats` caveats: https://npcap.com/guide/wpcap/pcap_stats.html
- Scapy asynchronous sniffing: https://scapy.readthedocs.io/en/stable/usage.html#asynchronous-sniffing
