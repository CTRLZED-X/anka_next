# P64 — Opt-in Windows passive PCAPNG evidence acquisition

**Milestone:** 2026-10-22. **Status:** offline source and fake-callback integration verified; **real Windows/Npcap capture NOT verified.** No gameplay input or authoritative state admission.

## Why this matters

P26/P27 can sample game TCP traffic on Windows and emit privacy-filtered counters, but the packet bytes previously vanished. That prevents investigators from examining unknown current-client protocol names/fields. P64 adds a **bounded raw-evidence acquisition path**, guarded by explicit JSON consent, to the existing read-only Windows capture sampler. It does not decode the current Dofus build or infer character ownership.

## Enabling it only when intended

1. Use your existing `config/user.json`. Under its existing `capture` object, **add** `"save_raw_evidence": true` and configure the **actual, observed** game-server TCP ports, capture-interface name, and duration. Example of the capture section only (the port and interface shown here are illustrative, **not claims about current Dofus traffic**):

   ```json
   "capture": {
     "server_ports": [40400],
     "interface": "YOUR_NPCAP_INTERFACE",
     "duration_seconds": 10,
     "save_raw_evidence": true
   }
   ```

2. On a Windows machine with Python 3.13, an installed working Npcap driver and the optional Scapy backend, use the **existing** `setup.bat` and `start.bat`. The passive startup sampler runs only if its existing window/port/interface/dependency checks permit it. Gameplay startup **still intentionally exits 40**. P64 adds **no additional BAT launcher or UI**.
3. Captures are written locally into `runtime/evidence/passive_<random>.pcapng`. No filename is placed in diagnostic JSON. They are **never bundled automatically** in GPT-friendly incident ZIPs or release ZIPs.
4. Set `"save_raw_evidence": false` (or remove the key) when raw packet collection is not wanted. The default is **off**; an invalid/non-boolean flag is rejected.

**Privacy warning:** These saved files contain **real packet headers, endpoint addresses, and possibly sensitive application messages**. They are not anonymized. Treat them as private, review before sharing, never publish them, and delete them when no longer needed. Local file permissions/ACLs and secure storage are the operator's responsibility; a generated `*.partial` is interrupted/unsafe evidence.

## Integrity properties and limits

- Exactly one finite Scapy capture sample, subject to P26 guards; incoming selected IPv4 TCP callback frames only. No network transmission, game API mutation or mouse/keyboard control.
- Frame store is capped at **5,000 records and 8 MiB**, bounded by a **65,535-byte maximum frame**. Packet content is not serialized into the normal diagnostic/event stream.
- A PCAPNG section (1.0, linktype Ethernet) and enhanced packet records are generated; the existing P49 capture parser can parse them. On interfaces that supply only an IP packet, a **synthetic Ethernet header** is prepended for interoperability; this must never be misrepresented as the original physical-layer capture.
- Callback/frame errors, queue overflow, unsupported fragments and recorder capacity failures **mark the file incomplete** using a positive PCAPNG interface drop count. The P62 parser rejects that marked file for research certification. A hard crash may leave a `.partial` file, never treated as finalized.
- The returned receipt includes only counts and SHA-256, plus `driver_loss_visibility: UNKNOWN`, `current_build_certified: false` and zero authoritative commits/physical input. A file with zero *observed* gaps is **not** proof of driver completeness, protocol semantics, identity, or cross-flow chronology.
- Raw bytes are opt-in and remain on disk; hashes and aggregate counts can appear in sanitized local diagnostics. Even these may be sensitive metadata and should not be treated as attestation.

## Verification and outstanding gates

The P64 developer-only test inventory passed **91/91 unittest modules, 1,573 tests** against one source-bound fingerprint. The new P64 test module contains **17 tests**; normal `check`/`setup` each run a two-case synthetic recording smoke. `check`/`setup` PASS; `start` is deliberately BLOCKED (exit 40, `LIVE_RUNTIME_NOT_IMPLEMENTED`), incident ZIP integrity PASS. Reused Kernel and 165 reference assets remain unchanged. No real Windows, Npcap, Dofus-client protocol certification, CRA/ENU binding, gameplay authority, or mission acceptance is claimed.

## Next actual acceptance

Run the existing configured passive capture on a **real Windows/Npcap host** with explicit consent and a known supported connection scope, collect and review raw evidence (privately), and independently corroborate process/window/socket/character identity. Protocol semantics still require current-build reverse engineering and independent game-state validation before any Canonical admission or gameplay execution could be considered.
