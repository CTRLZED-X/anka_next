# P62 — Reported PCAPNG packet loss must fail closed

## Reproduced defect

P61 ignored packet-loss metadata in otherwise well-formed PCAPNG captures. A packet could carry an `epb_dropcount=1`, a later Interface Statistics Block could report `isb_ifdrop=3`, or a legacy Packet Block could set `Drops Count=5`. All these captures could previously pass the TCP parser without surfacing the reported loss. Five broad sources of ambiguity are addressed: metadata from a *later* block, unrelated interface drop reports, different section endianness, malformed/duplicated loss options, and different parser entry points.

## Corrected boundary

`anka_capture.pcapng._reject_reported_packet_loss` is shared by `read_pcapng_tcp_segments` and `pcapng_packet_count`. The audit is non-optional for PCAPNG blocks with possible loss metadata:

- Enhanced Packet Block (type 6), option `epb_dropcount` code 4, unsigned 64-bit packet loss since the previous packet on that interface.
- Interface Statistics Block (type 5), cumulative interface drops (`isb_ifdrop` code 5) and operating-system drops (`isb_osdrop` code 7), unsigned 64-bit per interface.
- Obsolete Packet Block (type 2), unsigned 16-bit `Drops Count`; `0xFFFF` represents **unknown**, not zero.

Any *positive* reported count rejects the full capture. A selected TCP flow cannot prove that missing traffic belonged to some other flow merely because no TCP sequence gap was observed. The conservative policy is intentionally broader than individual flow selection. The parser validates option lengths and alignment, duplicate watched options, block identity, interface references, and section-local little/big endian counters. These checks run even for loss metadata appearing **after** otherwise valid packet records.

## Evidence limitations

No or zero-valued counters are **not proof of zero drops**: capture APIs do not necessarily publish drop counters; packets may be lost outside the counted boundary. P61's IPv4-only selected traffic and IPv6 exclusions still apply. No current-client packet-origin attestation, character binding, modern build semantics, Canonical admission, actual physical input, or end-to-end live acceptance is added. The current live startup remains deliberately blocked. Zero and `0xFFFF` unknown legacy counters are allowed as research, never as certification.

## Offline acceptance

- First reproduced against P61: 19 failed test cases including subtests; P62 fixes them.
- New P62 tests: 17 test methods with 11 subtests.
- Focused capture/protocol/PCAPNG group: 112 tests + 22 subtests PASS.
- Complete isolated source-bound suite: **89/89 modules, 1,539 methods PASS**, fingerprint in release receipt.
- `check` and `setup` both PASS and run an explicit positive-drop synthetic smoke.
- `start` remains intentionally blocked with `LIVE_RUNTIME_NOT_IMPLEMENTED` / exit 40; incident ZIP integrity PASS.
- No new BAT launchers or UI/dashboard. Runtime traces, checkpoints and caches excluded from the archive.

## Format reference

PCAPNG format draft, Enhanced Packet Block `epb_dropcount`, Interface Statistics Block `isb_ifdrop`/`isb_osdrop`, obsolete Packet Block `Drops Count` and unknown `0xFFFF` semantics: https://datatracker.ietf.org/doc/draft-ietf-opsawg-pcapng/ and https://wiki.wireshark.org/Development/PcapNG.
