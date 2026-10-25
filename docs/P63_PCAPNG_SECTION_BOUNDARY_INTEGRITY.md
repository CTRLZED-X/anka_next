# P63 — Fail-closed PCAPNG section framing

## Reproduced defects in P62

The two PCAPNG read paths independently interpreted block framing. Neither demanded a Section Header Block as the first block, validated version 1.0, nor honored Section Length declarations. Before the correction, 17 adversarial tests yielded **29 failed assertions and one error**, including packet blocks before the first SHB, unsupported section versions, overlong/underlong section declarations, and unexpected trailing blocks. Those defects permit apparently coherent research frames from structurally invalid captures.

## Implemented invariant

The new `_pcapng_blocks(raw)` iterator in `src/anka_capture/pcapng.py` is shared by `read_pcapng_tcp_segments` and `pcapng_packet_count`, eliminating divergence in section-frame interpretation. It requires the first PCAPNG block to be an SHB; each section must have correct byte-order magic, supported 1.0 major/minor format, aligned and well-bounded blocks, matching block length trailers, and either Section Length `-1` (unknown) or a nonnegative multiple-of-four exact length that excludes its SHB. Explicit sections may end only at the declared byte offset, followed by EOF or a new SHB. They cannot terminate early, overflow a block, or silently continue without a new SHB. Section-local interface indices and mixed-endian sections remain supported. Packet numbering continues across sections; the previous P60 packet-local message indexing remains unchanged.

The P62 packet-loss audit continues in both reader paths, and P61 IPv6 fragment handling remains intact. A synthetic six-case section rejection smoke runs inside normal `check`/`setup` and emits only privacy-safe status flags. Invalid source files remain research-rejected; no client data or packets are emitted to diagnostics.

## Verification

- P63 regression module: 17 tests PASS, including required, absent, malformed, zero/explicit/unknown section lengths, overlong sections, major/minor version, little/big endian and multiple section transitions.
- Focused P29/P31/P50/P59–P63/Capture/Protocol regression selection: 162 test methods PASS.
- Full source-bound isolated suite: 90/90 modules, **1,556 test methods PASS**. Verification fingerprint recorded in the P63 receipt.
- `check` and `setup` PASS; `start` intentionally refuses live operations (`LIVE_RUNTIME_NOT_IMPLEMENTED`, exit 40). Diagnostic incident ZIP PASS.
- Original P62 archive members preserved; no additional operator BAT files, UI, runtime traces or caches.

## Remaining limitations

Valid PCAPNG framing does **not** certify capture completeness, packet authenticity, correct current-client protocol semantics, Windows/account identity, game-state authority or gameplay execution. The historical decoders remain read-only. Subjective roadmap coverage 92%, verified complete live CRA/ENU acceptance 0%.

PCAPNG framing reference: https://datatracker.ietf.org/doc/draft-ietf-opsawg-pcapng/ and https://www.wireshark.org/docs/wsar_html/structpcapng__section__header__block__s.html .
