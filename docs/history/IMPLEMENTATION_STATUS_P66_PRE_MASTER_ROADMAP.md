# P66 — Complete buffered-drain sealing for passive PCAPNG evidence (22 October 2026)

P66 fixes a reproduced P65 finalization bug: the recorder was closed after sniffer shutdown **but before draining queued TCP segments and processing the protocol consumer**. A failure during that final drain could not be represented as lost evidence. P66 introduces a two-phase shutdown: `quiesce()` stops the sniffer and closes the queue without finalizing the PCAPNG; `capture_bounded_sample()` drains and audits the remaining polls, then `stop()` finalizes. Failure during final drain is now written as positive PCAPNG loss metadata; the existing parser rejects such a capture. Direct `stop()` compatibility and idempotency are preserved. Normal `check`/`setup` exercise four recording smoke scenarios. **93/93 isolated regression modules and 1,586 tests PASS**; focused **78 tests + 29 subtests PASS**; `check`/`setup` PASS; `start` intentionally BLOCKED (40) with verified incident ZIP. No current-client/Windows proof, Canonical admission or physical input. Optional raw recording stays OFF by default and remains private, with zero runtime capture files packaged. Details: `docs/P66_POST_STOP_DRAIN_EVIDENCE_SEALING.md` and `verification/P66_offline_acceptance_receipt.json`. Roadmap scope remains **92% subjective**, verified full live mission **0%**; only root operator BATs are `setup.bat` and `start.bat`.

---

# P65 — Fail-closed interrupted passive capture evidence (22 October 2026)

P65 fixes a reproduced P64 lifecycle bug: polling, wire-consumer or sniffer-stop exceptions could finalize an opted-in PCAPNG without representing the interrupted observation window. P65 marks those windows incomplete and writes positive PCAPNG loss metadata before finalizing; the existing research parser rejects such evidence. Premature stop before start is also incomplete. Normal complete samples remain `RECORDED_UNCERTIFIED`, never a proof of driver completeness. Automatic `check`/`setup` now exercise three recording cases. **92/92 isolated regression modules, 1,580 tests PASS**; `check`/`setup` PASS, `start` intentionally BLOCKED (40), incident ZIP verified. Raw capture remains OFF by default, private, and excluded from incident/release ZIPs; current-client/Windows acceptance still unverified. Details: `docs/P65_CAPTURE_INTERRUPTION_LOSS_SEALING.md` and `verification/P65_offline_acceptance_receipt.json`. Roadmap estimate stays **92% subjective**, full live CRA/ENU acceptance **0%**. Only root operator commands: `setup.bat`, `start.bat`.

---

# P64 — Consent-gated Windows passive PCAPNG evidence acquisition (22 October 2026)

P64 adds the previously missing **read-only Windows sample → saved actual packet bytes** path needed for future current-client protocol research. Raw packet retention is **OFF by default**, enabled only by adding `"save_raw_evidence": true` under `capture` in `config/user.json`; it also requires the existing explicit server-ports/interface/Windows-window/Npcap/Scapy checks. A bounded `.pcapng` is written only into ignored `runtime/evidence/` (never into a debug or release ZIP), with a synthetic Ethernet header when source frames have only L3; explicit callback/queue/recorder gaps write positive PCAPNG loss metadata so incomplete samples fail the P62 parser. Because these bytes contain IP endpoints and potentially sensitive app traffic, inspect privately before sharing. **Real Windows capture remains unverified; saved packet evidence does not prove driver completeness, current-client semantics, identity, or gameplay authority.** P64's full regression inventory is **91/91 modules, 1,573 tests passed**. `check`/`setup` PASS; `start` intentionally BLOCKED (40) with verified incident ZIP. See `docs/P64_OPT_IN_WINDOWS_PASSIVE_PCAPNG_EVIDENCE_ACQUISITION.md` and `verification/P64_offline_acceptance_receipt.json`. Subjective roadmap coverage **92%** (unchanged), verified live CRA/ENU mission acceptance **0%**. Operator BATs remain `setup.bat` and `start.bat` only.

---

# P63 — Crash-safe PCAPNG section boundaries (22 October 2026)

P63 closes a structural integrity gap in the P62 PCAPNG research parser. Previously both the packet decoder and packet-count reader could accept orphan blocks without a Section Header, unsupported SHB versions, and blocks beyond/short of an explicitly declared Section Length. A capture might therefore look coherent even though its section framing was corrupt. Both readers now use a single bounded `_pcapng_blocks` iterator that validates required SHB presence, section-local byte order, version 1.0, declared section length (excluding the header), block trailer/size, exact block boundaries, and mixed-endian multi-section transition. Unknown length (-1) stays supported. Automatic fail-closed P63 smoke runs in normal `check`/`setup`. **90/90 source-bound isolated modules, 1,556 tests PASS**; focused **162 tests PASS**. `check`/`setup` PASS, `start` BLOCKED intentionally (40), incident ZIP verified. Historical research only; no current-client/character authority, Canonical admission or physical input. Details: `docs/P63_PCAPNG_SECTION_BOUNDARY_INTEGRITY.md` and `verification/P63_offline_acceptance_receipt.json`. Subjective roadmap coverage remains **92%**; live CRA/ENU full acceptance **0%**. Only root operator commands: `setup.bat` and `start.bat`.

---

# P62 — PCAPNG recorded packet-loss evidence integrity (22 October 2026)

P62 fixes a reproduced silent-loss failure in the saved-capture research pipeline: P61 parsed enhanced packets, legacy packet blocks, and interface statistics blocks, but ignored packet-loss metadata. A coherent-looking selected TCP trace could therefore coexist with an explicit positive capture-drop count. P62 now rejects nonzero `epb_dropcount` (EPB option 4), `isb_ifdrop`/`isb_osdrop` (ISB options 5/7), and legacy packet block `Drops Count`, including delayed interface statistics and other capture interfaces. It validates bounded option lengths, duplicate counters, interface references, per-section endianness and rejects malformed statistics. Packet-count research cannot bypass the same metadata audit. Unknown counts remain unknown; missing/zero loss counters do **not** prove driver completeness. A synthetic fail-closed P62 smoke runs during normal `check`/`setup`. **89/89 source-bound isolated test modules, 1,539 methods PASS**; focused **112 tests and 22 subtests PASS**. `check`/`setup` PASS; `start` intentionally BLOCKED exit 40 with validated incident ZIP. No current-client certification, Canonical commits, or physical input. See `docs/P62_REPORTED_PCAPNG_PACKET_LOSS_INTEGRITY.md` and `verification/P62_offline_acceptance_receipt.json`. Subjective roadmap coverage remains **92%**; complete live CRA/ENU mission acceptance **0%**. Only `setup.bat` and `start.bat` are operator launchers.

# P61 — IPv6 fragmented-TCP capture completeness (22 October 2026)

P61 fixes a reproduced PCAPNG parsing defect: non-initial IPv6 TCP fragments lack TCP ports, but the existing parser could misread fragment payload as port bytes and silently omit traffic. Fragment offsets/M flags and reserved bits now prevent unclassifiable TCP-bearing fragments from being represented as absent; ordinary unrelated IPv6 traffic remains out of selected TCP scope. P50 flow inventory and P59 file-backed evidence checks fail closed, with an automatic synthetic fragment check during `check`/`setup`. **88/88 isolated modules and 1,522 methods PASS**; focused **194 tests +22 subtests PASS**; `check`/`setup` PASS; `start` intentionally BLOCKED exit 40 with valid incident ZIP. Historical research only; no IPv6 live support, current-client authority, Canonical writes or physical input. See `docs/P61_IPV6_FRAGMENT_TRANSPORT_EVIDENCE_INTEGRITY.md` and `verification/P61_offline_acceptance_receipt.json`. Roadmap estimate stays **92% subjective**; verified live mission **0%**. Only `setup.bat` and `start.bat` remain operator launchers.

---

# P60 — Correct packet-local wire provenance in multi-flow PCAPNG (22 October 2026)

P60 fixes a reproduced provenance bug in P6: `WireMessage.message_index` was derived from the **global** message counter, so unrelated TCP flow traffic could change the source index for a packet on a different account socket. It is now the **packet-local ordinal**; total counts remain global. Two interleaved flows can be independently corroborated against the same PCAPNG through P59. Automatic `check`/`setup` smoke added. **87/87 isolated modules, 1,508 tests PASS**; `check`/`setup` PASS; `start` correctly refuses live operation (exit 40). Old global-index research selectors must be regenerated from capture, not silently migrated. Historical protocol research remains non-authoritative; full live CRA/ENU acceptance **0%**, subjective roadmap estimate **92%**. See `docs/P60_PACKET_LOCAL_MESSAGE_PROVENANCE_INTEGRITY.md` and `verification/P60_offline_acceptance_receipt.json`. Only root operator BAT files: `setup.bat`, `start.bat`.

---

# P59 — Capture-backed wire cross-check (22 October 2026)

P59 cross-checks P58 untrusted admission claims against a **real saved PCAPNG** using the existing capture parser and historical P6 wire framing. The selected flow's message bytes, TCP generation, packet ordinal, message index, protocol build and capture file SHA must agree; missing/extra wire messages and changed file content are explicitly quarantined. This is a file-correspondence proof only, **not** driver-origin attestation, modern-client certification, character ownership, semantic authority, or gameplay input. **86/86 isolated modules, 1,504 tests PASS**; check/setup PASS; start correctly blocked (40). Full details: `docs/P59_CAPTURE_BACKED_WIRE_PROVENANCE_CROSSCHECK.md`. Roadmap estimate 92% subjective; complete live CRA/ENU acceptance 0%. Only `setup.bat` and `start.bat` remain operator launchers.

---

# P57 — SQLite synthetic schema initialization integrity

**Implementation:** P56 `executescript` transaction escape reproduced; P57 atomic DDL and version publication, structural v1/v2 checks, bounded startup WAL lock retries, fail-closed abandoned partial schemas, and automatic synthetic fault-injection preflight implemented. **Scope:** synthetic journal only; current-client and Windows/live acceptance remain open. Roadmap estimate: 92% subjective; full live CRA/ENU mission acceptance 0%.

See `docs/P57_SQLITE_SCHEMA_CRASH_ATOMIC_BOOTSTRAP.md` and `verification/P57_offline_acceptance_receipt.json` for the final results.

---

# ANKA_NEXT — P56 source-bound Canonical batch receipts

P56 extends P55's synthetic transactional journal with a durable **source-bound batch receipt**: one upstream logical batch is now atomically tied to its exact event range, event payload digest, final hash-chain tip and projection. Exact retries are idempotent even after lost COMMIT acknowledgement; batch/source relabelling, receipt tampering and adoption of unreceipted events fail closed. The synthetic ledger migrates v1→v2 under a serialized writer lock. Historical/current protocol drafts still cannot enter this path. **83/83 isolated modules, 1,449 tests PASS**; `check`/`setup` PASS; `start` remains intentionally blocked (exit 40). Roadmap estimate remains 92%; verified live CRA/ENU acceptance remains 0%. See `docs/P56_SOURCE_BOUND_BATCH_RECEIPTS_AND_SCHEMA_V2.md` and `verification/P56_offline_acceptance_receipt.json`.

---

# ANKA_NEXT — P55 transactional Canonical batch/fencing foundation

P55 ports the strongest transactional-live-truth invariant from the old R5.198 design into ANKA_NEXT's cleaner **synthetic-only** Canonical journal: one logical event batch is fully reduced before durable insertion, journal + projection commit together, and any ambiguous COMMIT acknowledgement or failed rollback **fences the writer until close/reopen + replay**. `append_fixture` now uses the same batch path. Historical/current protocol drafts still cannot enter this store and no input authority exists. **82/82 isolated modules, 1,433 tests PASS**; `check`/`setup` PASS; `start` remains intentionally blocked (exit 40). See `docs/P55_TRANSACTIONAL_CANONICAL_BATCH_AND_COMMIT_FENCING.md`. Roadmap estimate remains 92%; verified live CRA/ENU acceptance remains 0%.

---

# ANKA_NEXT — P54 historical process/flow/character/fight-actor continuity

P54 extends the P53 historical identity chain through P45/P46 fight observations: a historical `jnj` character/actor witness must match the same exact flow, transport generation, build and ordered fight actor evidence before the chain is reported as research-consistent. A new two-account aggregate composes stable Windows process/socket candidates → historical character → historical fight actor without exposing private identifiers or inventing cross-flow ordering. **81/81 isolated modules, 1,411 tests PASS**; `check`/`setup` PASS; `start` remains intentionally blocked (exit 40). This is historical research only, not current-client identity or gameplay authority. See `docs/P54_HISTORICAL_PROCESS_FLOW_CHARACTER_ACTOR_CONTINUITY.md`.

---

# P53 — historical character → flow → process research identity (offline)

- Recovered hash-pinned R5.198 world identity source and a narrow historical `jnj` character-name → actor/cell/map decoder.
- Preserved an old-source inconsistency: `jns` contains name-matching code but its handler registry does not declare `LOCAL_ACTOR`; P53 never uses `jns` as an identity witness.
- Added privacy-safe composition of historical identity witnesses with P51/P52 stable Windows process/socket candidates. Duplicate character claims, shared processes, forged flow digests, unstable owners and incomplete witnesses fail closed or remain partial.
- No `CharacterEvidenceProvider`, current-client identity, breed proof, Canonical authority or physical input is created.
- Verification: **80/80 modules, 1,387 tests PASS** on the exact P53 source fingerprint; check/setup PASS; start intentionally blocked with exit 40; incident ZIP PASS.
- Details: `docs/P53_HISTORICAL_CHARACTER_FLOW_PROCESS_IDENTITY.md`; receipt: `verification/P53_offline_acceptance_receipt.json`. Roadmap estimate remains 92%; live CRA/ENU acceptance 0%.

---

# ANKA_NEXT — P52 MULTI-CLIENT PROCESS/SOCKET TOPOLOGY (21 October 2026)

P52 connects the existing two-boundary Windows process/flow evidence into a privacy-safe **multi-account candidate topology** audit: duplicate TCP selectors cannot masquerade as two accounts, a process with two sockets counts as one process, and mismatched/ambiguous owners stay explicit. Uses existing P51 validation, preserving its output contract. A 3-case P52 smoke runs in existing `check`/`setup` (no extra BAT). **78/78 isolated modules, 1,356 tests passed**; `check`/`setup` PASS; `start` intentionally blocks (exit 40), incident ZIP integrity PASS. No authentic Windows/CRA/ENU identity, verified modern protocol, Canonical commits or input authority. Roadmap scope estimate 92% (subjective), complete live CRA/ENU acceptance 0%. Read `docs/P52_MULTI_ACCOUNT_SOCKET_PROCESS_TOPOLOGY.md` and `verification/P52_offline_acceptance_receipt.json`. Only `setup.bat` and `start.bat` remain root operators.

---

# ANKA_NEXT — P51 WINDOWS FLOW OWNERSHIP STABILITY (21 October 2026)

P51 fixes a real passive-ingress attribution issue: the before/after TCP-table intersection could hide a contradictory owner that disappeared between snapshots and incorrectly report a unique provisional flow/process hint. The now lossless two-boundary join rejects duplicated or conflicting endpoint owners, PID/HWND/process-generation changes, unexpected executable images, geometry or minimization changes, stale scan intervals, and incomplete inventories. It emits only privacy-safe counts, **never** verified CRA/ENU identity or gameplay permission. Normal `check`/`setup` exercise three offline consistency cases. **77/77 modules and 1,336 tests passed**, check/setup PASS, `start` intentionally blocked (exit 40), incident ZIP verified. Read `docs/P51_WINDOWS_TCP_OWNER_SNAPSHOT_STABILITY.md` and `verification/P51_offline_acceptance_receipt.json`. Subjective historical roadmap 92%, real live CRA/ENU acceptance 0%. Only root operator BAT files remain `setup.bat` and `start.bat`.

---

# ANKA_NEXT — P49 CURRENT RELEASE (21 October 2026)

P49 adds a **real saved-PCAPNG → P4 Capture → P6 Protocol → P47 historical replay** research entry point. It keeps missing driver-drop accounting and account/window identity **explicitly unverified**: even if coherent historical messages decode, the file-level report is `BLOCKED_EVIDENCE`, with zero Canonical commits and zero physical input. `check`/`setup` now verify this safety behavior automatically. No protocol build is certified as current. **Only root BAT files: `setup.bat` and `start.bat`.**

Verification: selected capture/protocol tests **342 PASS + 119 subtests**; separate architecture/diagnostics/integration selection **128 PASS + 32 subtests** (overlapping); `check`/`setup` PASS; `start` deliberately exits 40 and its incident bundle verifies. The broad combined suite is **incomplete** due to execution limits. Subjective roadmap coverage remains **92%**; full live-fight acceptance remains **0%**. Details: `docs/P49_SAVED_PCAPNG_HISTORICAL_REPLAY_UNCERTAINTY.md` and `verification/P49_offline_acceptance_receipt.json`.

---

# ANKA_NEXT — P48 CURRENT RELEASE (21 October 2026)

P48 connects **real CapturePoll/TCP segment bytes → existing P6 ProtocolInspector framing → P47 historical lifecycle/combat replay**, all in an `anka_app` *research-only* composition adapter. It detects transport gaps, unknown driver-loss visibility, source-generation changes, incomplete frames, unmapped messages, foreign flows and two independently reproduced silent/exception failure cases. The new P48 smoke is included in normal `check`/`setup`. See `docs/P48_CAPTURE_TRANSPORT_TO_HISTORICAL_RESEARCH.md` and `verification/P48_offline_acceptance_receipt.json`.

**Offline evidence:** 84 focused tests +24 subtests and a wider 557-test/142-subtest selection pass, `check`/`setup` PASS; broader full suite not verified. `start` is still intentionally blocked (exit 40) and diagnostic ZIP verifies. No current-client adapter, Canonical authority, or physical input. Exactly `setup.bat` and `start.bat` remain operator BAT commands. Estimated development-scope coverage 92% (subjective); live full-fight acceptance 0%.

---

# ANKA_NEXT — P47 CURRENT RELEASE (21 October 2026)

P47 integrates P45 lifecycle and P46 combat research decoding into **one bounded, single-flow historical server-wire replay**. Unknown obfuscated messages and unsupported combat actions now remain visible as explicit evidence gaps; duplicated/reordered source cursors, wrong flows/generations and corrupted fields block the research receipt. A clean subset of decoded events can no longer hide missing wire observations in this integrated API. P47's tiny independent smoke runs automatically in `check` and `setup`.

**All outcomes remain research-only.** Historical build 3.7.10.10 is not a certified current-client adapter; no synthetic observation authorizes Canonical commits, spell success, victory, or physical input. `start` remains intentionally blocked (exit 40). The new 28-test P47 suite and 101-test P45–P47 decoder group pass; the full 69-module regression inventory was **not completed** due to timeouts. See `docs/P47_HISTORICAL_WIRE_STREAM_REPLAY_AND_EVIDENCE_GAP_AUDIT.md` and `verification/P47_offline_acceptance_receipt.json`. Subjective development scope **91%**, real complete live-fight acceptance **0%**. Only root BATs: `setup.bat` and `start.bat`.

---

# ANKA_NEXT — P46 CURRENT RELEASE (21 October 2026)

P46 adds **research-only historical Dofus 3.7.10.10 combat wire observations** for `jsq/300` spell records, `jsq/5` push, `jsq/4` teleport and `jwp` result boundaries, plus P45↔P46 same-flow turn/cast causal audit. **No damage, AP/MP settlement, spell success or victory is inferred.** The Kernel, original reference assets, game input and live safety gates remain untouched.

**Verification:** 67/67 modules and 1,231 unittest methods independently passed (66 modules/1,220 in a resumable independent module inventory; the slow P37 verifier module separately passed 11). `check`/`setup` PASS; architecture and 165 assets PASS; `start` intentionally exit 40, incident ZIP validated. **Current-client live fight acceptance 0%.** Estimated engineering scope 91% (subjective, not quality). Root user BATs: `setup.bat`, `start.bat` only.

Read `docs/P46_HISTORICAL_COMBAT_OBSERVATIONS_AND_CROSS_FAMILY_CAUSAL_AUDIT.md` and `verification/P46_offline_acceptance_receipt.json` for exact evidence, limitations, and next gate. The underlying historical source code never executes, and no current-client adapter is certified.

---

# Current milestone: P45 (2026-10-21) — historical protocol decoder research recovery

Recovered seven hash-pinned R5.198 archived protocol source assets, a 39-handler/five-group inert reference inventory, a strictly historical 3.7.10.10 research-only round/turn/Ready decoder, and a one-flow chronology audit. Preflight verifies all historical source checksums. **65/65 isolated modules, 1,190 tests PASSED;** P45-only 32 tests/12 subtests; focused 237/71. Check/setup PASS; start remains deliberately blocked exit 40 with a verified incident ZIP. Only setup.bat/start.bat. Development-scope estimate **90% subjective**; complete live-fight acceptance **0%**. See `docs/P45_HISTORICAL_FIGHT_LIFECYCLE_AND_PROVENANCE.md` and `verification/P45_offline_acceptance_receipt.json`.

---

# Current milestone: P44 (2026-10-21) — native bridge recovered, read-only projection research integration

Recovered 14 R5.198 Unity bridge source/provenance files under `native/unity_bridge/`, added strict localhost-only GET `/health` and `/coordinates` Client evidence validation, process generation/port/map/camera/projection and full 560-cell consistency checks, source integrity on automatic preflight, and 2 regression modules. Historical native build/install and current Windows/client validation remain unverified; live start stays blocked (exit 40), no input authority. Targeted 211 cross-system tests +127 subtests passed (overlapping P44 group: 20 tests +42 subtests); 7/63 full isolated modules/135 tests checkpointed before outer timeout. See `docs/P44_READ_ONLY_NATIVE_UNITY_BRIDGE_INTEGRATION.md` and `verification/P44_offline_acceptance_receipt.json`. Two root operator BAT launchers remain: `setup.bat`, `start.bat`. Weighted roadmap development estimate **89% subjective**, live CRA/ENU fight acceptance **0%**.

---

# Current milestone: P43 (2026-10-21) — source-linked research comparison rows

Protocol comparisons are now bound to individual intake case records, not only an archive/build/adapter tuple. Status, explanatory mismatched-field names and reported finding counts must agree with case results. Nine new P43 tests; 353 focused tests +17 subtests; 61-module full isolated inventory /1,138 tests; check/setup PASS, start intentionally blocked 40 with a valid incident bundle. See `docs/P43_CASE_LEVEL_COMPARISON_LINEAGE_AND_RESULT_CONSISTENCY.md` and `verification/P43_offline_acceptance_receipt.json`. Estimated roadmap coverage unchanged 88%, current-client live-fight acceptance 0%. Research only; no physical input.

---

# ANKA_NEXT P42 — Protocol comparison evidence binding (offline)

Confirmed P41 cross-system integrity defect: P32 could combine a successful P29 comparison with another P28 intake pack that had identical case indexes and capabilities but different source ZIP/build/adapter. P42 introduces a privacy-safe opaque source binding, makes the capability matrix enforce it, and rejects inconsistent case counts. Eight new tests, 344 focused + 17 subtests PASS, all 60 isolated modules / 1,129 tests PASS. `check`/`setup` PASS; `start` safely blocked (exit 40) with verified incident ZIP. 13 package boundaries, 165 assets, only two BAT launchers, current-client live acceptance 0%, subjective roadmap coverage 88%. See docs and receipt. No separate handoff file.

---

# ANKA_NEXT P41 — cell-transition and source/capability integrity (offline)

P41 fixes two independently reproduced research-only errors: same-cell position
refreshes were overclassified as movement; and one wire packet could be counted
repeatedly for the same role/capability by changing oracle IDs. The new P41
regressions preserve genuine movement ambiguity, cross-role source independence,
and legitimate multi-field messages. **All 59 module-isolated test files / 1,121
test methods passed**, and the P28–P41 focused gate passed 336 tests plus
12 subtests. `check` and `setup` PASS; `start` still refuses live execution
with exit 40 and a verified incident bundle. Modern-client acceptance remains
0%, and estimated roadmap coverage 88% (not a quality score). No separate
handoff or extra operator BAT was introduced. Full details:
`docs/P41_CELL_TRANSITION_AND_PROTOCOL_CLAIM_INTEGRITY.md` and
`verification/P41_offline_acceptance_receipt.json`.

---

# ANKA_NEXT P40 — Protocol evidence source independence (offline)

- Fixed a reproduced cross-account research coverage inflation: one exact server message or one oracle assertion can no longer be counted as separate CRA/ENU evidence just by relabeling the case role. The P28 intake now rejects reused oracle observations and cross-role selector aliases by content SHA-256, before P29/P32 compare coverage.
- 11 new negative/positive tests; focused P28–P40 test gate 305 tests + 12 subtests PASS. Setup/check PASS; `start` remains deliberately blocked (exit 40). Complete all-module pytest run NOT VERIFIED (execution limit).
- No current-build adapter/certification, live input, authoritative Canonical admissions, or changes to preserved Kernel/game-data/calibration. The project remains research only.
- Exactly `setup.bat` and `start.bat` for operators; no separate continuation handoff. See `docs/P40_CROSS_ACCOUNT_EVIDENCE_SOURCE_INDEPENDENCE.md` and `verification/P40_offline_acceptance_receipt.json`.
- Estimated development scope **88%** unchanged; integrated CRA+ENU live-fight acceptance **0%**.

---

# P39 — target witness and MP before-cast context integrity (offline)

- Fixed two research-result false-clarity cases: old-turn cell witnesses are stale even if no newer cell packet was observed; distinct target-cell transitions before a cast confound target MP deltas. Repeated same-cell updates and unrelated-actor movement do not trigger the new MP caveat.
- Extended setup's existing P36 smoke with two P39 negative assertions. Both stay research-only, with no server-effect or action authority.
- Added `tests/test_p39_target_context_integrity.py` and detailed `docs/P39_TARGET_CONTEXT_INTEGRITY.md`; exact release test counts and limitations are in `verification/P39_offline_acceptance_receipt.json`.
- Complete current-client/live CRA+ENU fight acceptance **0%**; roadmap implementation estimate **88%**, unchanged. Only root operator `setup.bat`, `start.bat`.

---

# P38 — Causal research observation windows hardened (offline)

- Fixed P35 false-clarity classification when an intermediate same-actor/same-metric observation already accounts for a resource, HP, cooldown or cell change; added MP/movement confounder checks.
- Fixed P35/P36 baseline crossing a previous completed turn while protecting the valid current-turn AP/MP-before-TURN_START case. No damage/heal/cast effect or server outcome is claimed.
- New 12-case P38 regression suite; original P35/P36 APIs, immutable research contracts, preserved kernel and current protocol data remain unchanged.
- `setup`/`check` remain offline-only; `start` is intentionally blocked. Only `setup.bat`/`start.bat` for operators.
- Full verification details in `verification/P38_offline_acceptance_receipt.json`; no complete live-fight acceptance. Development roadmap estimate **88%**; integrated live-fight acceptance **0%**.
- No separate continuation handoff attachment is generated for this release; the full ZIP includes this status and `docs/P38_CAUSAL_OBSERVATION_WINDOW_HARDENING.md`.

---

# P36 — target-resource confounder evidence and per-module verification (offline)

- Added source-scoped target HP/AP/MP before/cast/after research, with optional target-cell witnesses. Exposes intervening target snapshots, competing casts and observed target movement as **causal confounders**; data is **not** game-server spell settlement.
- P36 contracts and reports are immutable, privacy-minimized and research-only; no physical input, authoritative Canonical commit or game-state mutation.
- Added module-by-module subprocess isolation mode to internal `verify`, preserving the AST inventory and exact test-count requirements, with module-specific timeout diagnostics.
- 29 new P36 tests. **137 focused P24/P33/P34/P35/P36 regression tests passed**. The full 53-module gate remains **NOT COMPLETED** in this environment after two bounded attempts; no assertion failure was recorded before the timeout. No complete new all-suite pass is claimed.
- `check`/`setup` PASS and include P36 smoke; `start` remains deliberately blocked with `LIVE_RUNTIME_NOT_IMPLEMENTED` (exit 40); 165 reference assets verify; architecture audit 13 packages, 247 modules.
- Exactly two root operator BAT files. No dashboard. Current-client live acceptance: **0%**. Estimated weighted roadmap coverage: **87%** (subjective, not quality or capability percentage).
- See `docs/P36_TARGET_EFFECT_CONFOUNDER_AUDIT_AND_MODULE_ISOLATION.md`, `verification/P36_offline_acceptance_receipt.json` and root `00_READ_FIRST_NEXT_CHAT.md`.

---

# P35 — source-linked research snapshot / spell effect reconciliation (offline)

- Explicit before/cast/after evidence windows now check correct actor, scoped fight/transport generation, strict packet+message ordering, matching absolute resource kinds, and turn-boundary containment. The preexisting P34 provenance and shadow checks remain authoritative for **rejecting malformed research**; P35 does not bypass them.
- AP/MP/RANGE/HP/cell/cooldown differences are diagnostic observations **only**. They never prove server acceptance, resource spending, spell effects, or a confirmed victory. Multiple casts and snapshot reuse are flagged; outputs are sanitized, without numeric values.
- `setup` runs fast positive/negative research checks; `start` remains blocked. Exactly `setup.bat` and `start.bat` are operator BAT commands.
- See `docs/P35_CAUSAL_SNAPSHOT_RECONCILIATION_RESEARCH.md` and `verification/P35_offline_acceptance_receipt.json`.
- Estimated roadmap coverage: **86%**; complete current-client/live CRA/ENU fight acceptance: **0%**. Neither is a production-quality measurement.

# P34 — reconstruction coverage and unsimulated spell-effect reporting (offline)

- Added immutable research-only coverage contracts and app-only orchestration over the real P33 pure reducer. Casts remain un-applied, but are counted and tested for correct actor/turn/fight/flow provenance; explicit gaps identify missing AP/cooldown/limits/damage and server outcomes. Movement snapshots never prove paths or MP costs.
- Existing setup synthetic check now includes P34 positive and negative scenarios automatically. No additional operator BAT launchers; root has only `setup.bat` and `start.bat`.
- **33 new P34 tests passed.** An additional **493 distinct inherited tests** across selected protocol, state, coordination and execution modules passed, for **526 focused tests**; an attempted full inherited per-module run exceeded its execution limit. Do not report a fresh full-suite pass.
- Setup: PASS, including 165 reused assets and the 13-package architecture check. Live input disabled and current-build adapter uncertified.
- Roadmap development estimate: **85%** (not a measured quality rating). Complete live CRA/ENU fight acceptance: **0%**.
- See `docs/P34_RECONSTRUCTION_COVERAGE_AND_UNSUPPORTED_EFFECTS.md` and `verification/P34_offline_acceptance_receipt.json`.

# P33 — research-to-Canonical shadow compatibility (offline)

- Added a pure bridge for P31 fight/resource research observations to P8 synthetic reducer specifications, with a separate application composition layer. Sources, fight scope, actor fixture roster, ordering, duplicates, turn handoff and unsupported spell casting fail closed.
- `setup` automatically runs one fast positive/negative shadow contract check; no new BAT commands, no SQLite commits and no physical input.
- 30 new tests; **966 tests across 49 independent Python modules passed**. The combined verifier's intermittent stall remains open.
- `setup`: PASS; `start`: intentionally blocked (exit 40); 165 assets verified; 13-package dependency audit PASS.
- Estimated implementation roadmap progress: **84%**; integrated live CRA/ENU acceptance: **0%**. These are not quality-certification percentages.
- See `docs/P33_RESEARCH_SHADOW_REPLAY_CANONICAL_COMPATIBILITY.md` and `verification/P33_offline_acceptance_receipt.json`.

# P32 — research protocol capability review matrix (offline)

- Added a per-capability acceptance report to the existing staged-protocol `setup` workflow. Checks mismatched/missing source evidence, exact selectors, witness presence and claimed CRA/ENU account-role coverage.
- Detects forged or inconsistent comparator case counts/ordinals. Never treats declared roles, matched research oracles or a successful archive intake as live certification.
- No new operator commands, decoder activation, journal commits or physical input. The current-build research recipe registry is unchanged (empty).
- See `docs/P32_PROTOCOL_CAPABILITY_ACCEPTANCE_MATRIX.md` and `verification/P32_offline_acceptance_receipt.json`.
- Estimated development roadmap coverage: **83%** (not software-quality reliability); integrated live CRA/ENU fight acceptance: **0% completed**.

# P31 — fight-event research adapter and deterministic chronology (offline)

- Extended locally reviewed schema-2 declarative recipes with six isolated research-only fight-event types: fight start/end, turn start/end, actor cell and spell cast; P30 schema-1 resource recipes remain compatible.
- Created immutable event research contracts and pure single-flow chronology consistency checks; **no journal commits or live state projection**.
- Updated exact-source evidence comparison for fight event oracles after full capture continuity checks; strict provenance, no private values in reports.
- Registered current-build recipes: **zero**. `setup.bat` / `start.bat` only; no physical input.
- Evidence: `docs/P31_FIGHT_EVENT_RESEARCH_AND_ORACLE_COMPARISON.md` and `verification/P31_offline_acceptance_receipt.json`.
- Scope estimate: **82%** (not a measured quality score); integrated live CRA/ENU acceptance: **0% completed**.

# P30 — version-local declarative semantic research (offline)

- Added a bounded, source-reviewed and SHA-256-pinned local JSON recipe facility for new exact-build wire names / protobuf field paths, with AP/MP/range and HP/max-HP research-only semantics. Zero new-build recipes ship enabled.
- Preserved old historical adapter and exact packet/oracle comparison. The P30 composition root can compare a *reviewed* new-build mapping without editing the Kernel, Decision, Execution or Canonical journal packages.
- Corrected the cross-contract underscore mismatch between allowed protocol wire names and Canonical `EvidenceRef` names.
- No automatic adapter activation, Canonical admission, current-build certification, physical input or new operator commands. `setup.bat` / `start.bat` only.
- See `docs/P30_DECLARATIVE_RESEARCH_PROTOCOL_ADAPTERS.md` and `verification/P30_offline_acceptance_receipt.json`.
- Estimated roadmap coverage: **81%**. This is not measured production quality. Integrated live CRA/ENU acceptance: **0% completed**.

# P29 — Protocol oracle/decoder comparison foundation

- Added a research-only exact-source decoder comparison pipeline for P28-staged evidence archives. Historical Dofus 3.7.10.10 is the only locally registered semantic mapping; newer build packs are explicitly blocked, not silently interpreted with old names.
- Comparison requires explicit server ports and packet/ordinal/flow/generation selectors; pinning, whole-capture continuity, schema drift, privacy and field-level mismatch tests are covered. No protocol pack is allowed to install code, activate an adapter, write authoritative state or send input.
- Operator commands remain only `setup.bat` and `start.bat`. Original R5.198 assets and standalone Kernel remain unchanged.
- Current-build real witness/packet evidence, semantic adapter implementation, Windows acceptance and full live CRA/ENU gameplay remain **pending**.
- Development roadmap estimate: **80%** (approximate coverage, not measured software quality). Integrated live fight acceptance: **0% completed**.
- See `docs/P29_PROTOCOL_ORACLE_COMPARISON.md` and `verification/P29_offline_acceptance_receipt.json` for measured verification results.

# P26 — Passive Windows startup ingress diagnostics

- `start.bat` integrates the previously independent Windows/Npcap read-only sampling backend when ports/interface and a plausible configured account window are present. It is capped to 10 seconds and never enables physical input or authoritative gameplay events.
- Privacy allowlist rejects forged or malformed sample receipts; errors are categorical; HWND/PID/process generation and TCP endpoint must remain stable across two snapshots for **provisional process hints**.
- `setup.bat` optionally installs Scapy when capture is explicitly configured; Npcap/Windows acceptance is pending.
- Operator surface remains exactly `setup.bat` and `start.bat`. Historical calibration, kernel and R5.198 source remain unchanged.
- P26 added 36 tests. All 775 collected tests passed using bounded verification, but the combined all-in-one verifier continues to intermittently stall; do not treat it as resolved.
- Full autonomous live-fight acceptance: **0% completed**; roadmap implementation estimate: **77%** (not a quality/reliability measurement).
- See `docs/P26_PASSIVE_STARTUP_CAPTURE_EVIDENCE.md` and `verification/P26_offline_acceptance_receipt.json`.

# P25 — passive Windows host evidence at setup/start

- Added a privacy-minimized, read-only Windows host diagnostic probe in `anka_app.host_readiness`.
- `setup.bat` and `start.bat` now record game-window candidate states, calibration compatibility signals, capture configuration/dependency hints and provisional TCP owner-table evidence, when available.
- All host observations remain **uncertified** and can never enable physical input.
- No extra operator commands or dashboard; the reused game kernel and prior runtime systems are unchanged.
- P25 offline verification: 739/739 test methods passed across eight independently invoked groups. The combined verifier can still intermittently stall; Windows-native acceptance remains outstanding.
- See `docs/P25_PASSIVE_WINDOWS_HOST_READINESS.md` and `verification/P25_offline_acceptance_receipt.json`.

# P24 — isolated regression release gate and diagnostic improvements

- Built a discoverable, eight-shard developer verifier with subprocess isolation and bounded per-shard timeouts.
- Fail-closed test inventory and count checks, precise shard-start/failure evidence, no new BAT commands.
- Reused all P23 runtime code and unchanged game kernel. `setup.bat` and `start.bat` remain the only operator commands.
- Current-build protocol, live game state, Windows host and physical gameplay remain unverified/disabled.
- Verification receipt: `verification/P24_offline_acceptance_receipt.json`.

# P23 — research-stage transport finality and provenance

- Eliminated eager staging of semantic candidates before whole-capture inspection finalizes.
- Requires both capture/protocol continuity and exact wire-message provenance before any historical research staging.
- Preserves harmless unknown wire names, rejects semantic drift and late corruptions without partial accepted research facts.
- 18 new tests; 714 total collected tests pass in eight bounded groups. Monolithic runner remains intermittently stalled.
- Only `setup.bat` and `start.bat`; original kernel and R5.198 source untouched. No live authority introduced.
- See `docs/P23_CAPTURE_FINALITY_AND_SEMANTIC_PROVENANCE.md` and P23 verification receipt.

# P22 — exact causal provenance in offline CRA/ENU handoffs

- Integrated an explicit typed party-event → audited Canonical journal source-link audit.
- New immutable contract and composition layer; no new independent runtime system.
- Fight start requires evidence from both accounts; every Turn Start/End must match a single journal event with exact account, generation, actor, fight and type.
- Three new end-to-end negative scenarios, plus direct adversarial coverage for mismatched, duplicated, missing and forged source links.
- Failures block Decision and fake Execution with P22-specific diagnostic reasons. Synthetic evidence remains non-authoritative, and no global cross-account ordering is claimed.
- Operator commands remain exactly `setup.bat` and `start.bat`.
- Current-client and live action prerequisites are still missing and must not be inferred from P22.

# P21 — architecture and live-readiness evidence gates

- Automatic AST import-contract guard integrated into setup and start.
- Explicit production-readiness blockers recorded before live-start refusal.
- Full nine-scenario historical failure matrix in internal regression tests; operator launchers stay at setup/start only.
- No physical input, current-build semantic promotion, or executable FightAI.
- Verification must be reported separately from live-readiness; read the P21 receipt.

# P20 implementation status

- **Scope:** synthetic cross-system replay and automatic integration smoke; no live game input.
- **Operator surface:** exactly setup.bat and start.bat; 32 nonessential Windows BAT wrappers removed.
- **Safety:** no Decision research-to-execution authority conversion. Exact failures are evidence-linked; uncertain fake actions never blindly retry.
- **Diagnostics:** setup validates a positive and negative synthetic handoff without exporting incidents for deliberately injected failures; start emits an incident explaining that live runtime is unavailable.
- **Acceptance:** synthetic-only tests and release checks; no Windows/current-client/live battle certification.

## Historical context (P19)

# Implementation status — 20 October 2026

## Implemented in this package

| Scope | Implemented | Evidence |
|---|---|---|
| P0: archive provenance | Source SHA-256, 165 copied items tracked | `provenance/reuse_manifest.json`, validated in `check` |
| P1: isolated interfaces | Immutable diagnostic envelope and passive sink port | `src/anka_contracts` and tests |
| P1: JSON configuration | Strict one-source config; duplicate keys/unknown fields/unsafe defaults rejected | `tests/test_configuration.py` |
| P1: early Windows bootstrap | Before-Python CMD stage markers and stdlib early failure ZIP where Python exists | `_entry.bat`, `tools/bootstrap_failure.py`; Windows runtime **not tested here** |
| P1: passive diagnostics | Bounded event journal, sanitization, incident ZIP, checksum validation | `src/anka_observability/` and tests |
| P1: synthetic failure case | `Ready -> no verified turn owner` example; no input ever sent | `replay.bat`, example bundle and tests |
| P2 seed: kernel reuse | Kernel copied without changes, working offline smoke with source static data | `src/anka_game_kernel`, `tests/test_kernel_reuse.py` |
| P3 seed: calibration reuse | 22 historical spell-slot points and phase/join controls, validated bounds/hash; explicitly NOT live certified | `assets/calibration` and `tests/test_reference_assets.py` |

| P3 initial: window discovery | Read-only Win32 process-generation inventory, trusted-image filtering, identity evidence policy, fake-provider tests | `src/anka_client/{api,discovery,win32_inventory,geometry}.py`, `tests/test_client_*.py` |
| P3 CLI: `clients.bat` | Observational command; never enables input, reports blocked/pending identities | `src/anka_app/cli.py`, `clients.bat` |

## Not implemented / remaining gates

- Native Windows window/process inventory implemented but NOT host-smoke-tested. No live character/class identity evidence provider, current-build DPI calibration, Unity projection or spell-slot-to-spell binding.
- No network capture, protocol-version adapter, canonical SQLite writer, live state reducer, FightAI, account coordination, world mission controller or physical execution.
- No live-client acceptance, no server-backed action confirmation, and no claim that protocol version 3.7.10.10 covers current Dofus builds.
- Windows `.bat` startup/installer cannot be executed on this Linux verification host; bootstrap log fallback behavior needs real Windows tests.
- Full P1 mature features (disk fault injection, process crash reconciliation and causal cross-subsystem diagnosis) still require future milestones.

## Explicit acceptance status

**P0 evidence inventory + basic reused-asset integrity:** PASS in current environment.

**P1 first implementation slice:** PASS for 38 automated tests and the synthetic bundles. **Full P1 milestone:** PARTIAL / remaining Windows and fault-injection evidence.

**P3 read-only discovery:** Pure offline checks pass; real Windows/client acceptance and authoritative class mapping are **PENDING**.

**P2 reuse seed:** Core package copied unchanged and kernel static smoke tests pass. **Complete P2 contract parity:** NOT YET CERTIFIED.

**Live runtime:** BLOCKED BY DESIGN.

Do not interpret the archived R5.198 historical test results as successful tests of the new runtime.

## P3 read-only milestone — evidence (20 October 2026)

Expanded new-project Python suite: **71 tests pass** on Linux with Python 3.13.5; a normal `check` passes with 165 reference assets; `verify` passes; `clients` returns `NOT_AVAILABLE` on Linux with `physical_input_permitted=false`; `start` returns **40 / LIVE_RUNTIME_NOT_IMPLEMENTED**, and synthetic `replay` returns `physical_input_sent=false`. The existing diagnostics auto-create incident ZIPs. See `verification/P3_offline_acceptance_receipt.json`.

**Interpretation:** This proves pure matching/policy contracts, package import boundaries and offline safe failure. The Win32 inventory is **not Windows-host tested**, class cannot yet be live-attested, and calibration remains historical. P3 is **PARTIAL**, not accepted for live use.

## P4 offline transport milestone — 20 October 2026

- Implemented `src/anka_capture/{api,pcapng,transport}.py` and contracts `src/anka_contracts/capture.py` using a carefully isolated R5.198 PCAPNG parser (transport-only; no legacy protocol imports).
- Strict 32 MiB single-snapshot PCAPNG cap, explicit server-port selection via optional `config/user.json` `capture.server_ports`, malformed record/length/linktype/fragment/selected-IPv6 rejection, metadata-only receipt, no packet-body logging.
- Audits stream sequence gaps, missing SYN anchoring, reconnect generations and retransmission/reorder observations. A newer clean connection never conceals an older unresolved gap. Observed no-gap status is **not** proof of capture completeness.
- `capture_demo.bat` inspects the bundled synthetic fixture. `capture.bat` reads a user-supplied offline PCAPNG only after ports are configured. No automatic port guessing, no raw packet export, no physical input.
- Offline suite passes **113 tests** (71 inherited and 42 new/expanded tests). Unix/Linux verification only. Exact Windows/Npcap live capture, process/flow identity binding, queue-drop instrumentation and true live-vs-offline parity remain unimplemented and must not be claimed accepted.
- Future live-source public contract is a bounded `CapturePoll` with explicit lost/overflow metadata; it has **no concrete live implementation**. `start.bat` remains BLOCKED BY DESIGN.

## P5 Windows capture candidate — 20 October 2026

- Added a read-only Windows/Npcap/Scapy adapter, enabled only through explicit `capture_live.bat` (not `start.bat`). Requires a configured interface and game server ports; optional dependencies are installed separately.
- Implemented bounded in-memory payload buffering (default 1,024 segments / 4 MiB), monotonic capture generation, cumulative drop counters, deterministic polling, and live metadata-only transport audit across poll boundaries.
- Added Windows `GetExtendedTcpTable` TCP_OWNER_PID snapshot bridge and conservative PID/process-generation candidate matching. Unique matches remain `PROVISIONAL`, never account attestation.
- Driver packet loss is **UNKNOWN** without a driver statistics API; even zero Python-queue drops cannot certify complete capture. TCP gaps, old generations, and malformed frames remain visible across polls. Captured packet contents are not included in debug bundles.
- Read-only `capture-live` is never a live gameplay activation path; `start` is still blocked.
- New injected-failure tests added in `tests/test_capture_live.py`; Linux/offline test suite passes (see P5 acceptance receipt).
- **Not tested:** Windows/Npcap host, Scapy version on the user host, exact interface ownership, driver loss counters, loss-free capture parity, authoritative multi-account character identity, live gameplay, actual network flow mapping.


## P6 Protocol wire-observation milestone — 20 October 2026

- Added `anka_protocol` with bounded protobuf wire parsing, length-prefixed frame
  assembly, TCP sequence-generation quarantine and exact-build historical catalog.
- Added stable observation-only DTOs in `anka_contracts.protocol`. All cross-system
  orchestration lives in `anka_app.protocol_offline`; `anka_protocol` does **not**
  import `anka_capture` implementation, game kernel or legacy `anka_platform`.
- Imported R5.198 `3.7.10.10` **wire-name catalog and scenario metadata only**, with
  SHA-256 manifest and explicit `HISTORICAL_REFERENCE_ONLY` status. No real semantic
  adapter or Canonical event producer is enabled.
- Failure tests preserve missing TCP SYN, sequence gaps, duplicate/retransmission,
  capture-source restarts, malformed/incomplete frames, catalog tampering, unknown
  messages, direction mismatch, missing build, private payload exclusion and
  startup fail-closed behavior.
- New `protocol_demo.bat` and `protocol_audit.bat` are **read-only**; the audit takes
  explicitly configured ports and a target client build string. The status of
  any inspected wire messages remains observational, not authoritative.
- **Still missing:** end-to-end exact-build semantic decoder, current-client PCAP
  corpus, current-build protocol adapter certification, Canonical emitter,
  verified HP/AP/MP/turn ownership, Windows live packet/source coverage and gameplay
  actuation. No live readiness is claimed. See `verification/P6_offline_acceptance_receipt.json`.

## P7 historical semantic / Canonical research staging — 20 October 2026

- Historical `jtk` AP/MP/RANGE, `jti` cooldown snapshot and `kqo` HP/max-HP
  decoding moved into an independent version-local **research adapter**;
  only `Dofus 3.7.10.10` is supported and NO new/current build is certified.
- Canonical v1 immutable typed `CanonicalDraft`/`EvidenceRef` and separate
  bounded, idempotent-in-memory `CanonicalStagingGate` are implemented; **zero
  Canonical journal commits, zero Live State writes and zero physical inputs**.
- P6 duplicate-Any-envelope defect corrected by preserving multiple occurrences
  and distinguishing source message ordinals; regressions added.
- Strict negative coverage: unsupported/malformed/new branches, duplicate
  characteristics, out-of-range resources, missing local-actor context, wrong
  direction/build, unknown wire names and staging capacity.
- Added synthetic `semantic_demo.bat` and safe `semantic_audit.bat`; no raw
  payloads are written to diagnostic bundles. See P7 independent acceptance.
- **Still not completed:** current-build semantic certification, authoritative
  account identity, persistent Canonical journal and atomic state reducer,
  actionable game state, execution, Windows host acceptance, full incident replay.

## P8 offline Canonical journal and Live State foundation — 20 October 2026

- Added `anka_contracts.state.OfflineStateEvent` (immutable, `SYNTHETIC_FIXTURE_ONLY`), a pure `anka_live_state.reducer` and `anka_canonical.journal.SQLiteFixtureJournal`.
- The journal uses SQLite WAL + FULL sync and atomic event+projection commits; integrity is checked by hash-linked event replay against projected state. Cross-system wiring lives in `anka_app.state_offline`.
- New `state_demo.bat` and `state_audit.bat` are synthetic/read-only only. No live Canonical authority, no game input, no promotion of historical candidates.
- 37 new P8 checks cover reducer contracts, mutation refusal, account/fight epochs, missing facts, ordering, exact duplicate idempotency, rollback at two commit stages, tamper detection, parallel writers, CLI demo and blocked live start.
- **Total new-project suite: 255 tests passed offline** (Linux/Python 3.13). P8 is verified as an **offline synthetic foundation**; Windows, protocol certification, power-cut acceptance and live state authority remain pending.
- See `docs/P8_DURABLE_CANONICAL_LIVE_STATE.md` and `verification/P8_offline_acceptance_receipt.json`.

## P9 research evidence + state quality — 20 October 2026

- Added `anka_canonical.qualification` and `anka_live_state.quality` as dependency-isolated offline diagnostics: build/adapter provenance, conflicting repeated observations, transport/identity caveats and missing/stale simulated actor state are now explicit.
- Added `SQLiteFixtureJournal.audited_snapshot` to hold one read transaction while verifying and retrieving state, preventing cross-revision quality reports during concurrent writes.
- Added `quality-demo` and `quality-audit` commands and Windows wrappers; demonstrations do not promote historical protocol research values or send physical input.
- The full new-project suite passed **304 tests** on Linux/Python 3.13 (P8: 255, P9: +49). Full CLI `verify` passed after one overlong attempt; precise elapsed time and run status are described in `verification/P9_offline_acceptance_receipt.json`.
- Historical source data, game kernel and reference calibrations are untouched. `start` still refuses with `LIVE_RUNTIME_NOT_IMPLEMENTED`.
- Exact current client identity, on-host Npcap integration and current-build semantic certification remain outstanding. **P9 passes offline foundation acceptance only.**


## P10 synthetic protocol qualification — 20 October 2026

- Implemented a bounded fixture-based protocol-adapter contract evaluator that compares exact candidate types and values, explicit build and evidence coordinates, failures, and duplicate-message ordinals.
- Added 14 historical 3.7.10.10 synthetic scenarios and adversarial tests that detect wrong golden values, missing cases, schema tampering, fake authority, unexpected adapter success, and decoder crashes.
- Added headless `protocol_qualify.bat` and diagnostics receipts with SHA-256 of adapter implementation and fixture; no packet bodies are exported.
- A different requested protocol build is explicitly **incompatible** even if old fixture tests pass; no current-build promotion, no authority and zero physical input.
- Current-build semantic certification, full consumer replay, Windows host and live fight acceptance remain **PENDING**.
- See `docs/P10_SYNTHETIC_PROTOCOL_ADAPTER_QUALIFICATION.md` and `verification/P10_offline_acceptance_receipt.json`.

## P11 synthetic fight/turn evidence and Coordination audit — 20 October 2026

- Added one auditable SQLite read-transaction API for bounded, all-or-nothing multi-session synthetic evidence. Reuses P8 hash-chain replay; no existing projection schema changes.
- Added independent turn-history analysis that distinguishes in-fight resource observations preceding TURN_STARTED from those seen after; never asserts that either is fresh live truth.
- Added read-only independent `anka_coordination` evidence comparison with explicit expected account identities and process generations, fight/turn disagreement diagnosis, and no assumption of simultaneous server observation.
- `fight_demo.bat` demonstrates aligned observations versus intentional CRA/ENU owner divergence, and emits a checksum-verifiable synthetic incident ZIP if diagnostics is available. `fight_audit.bat` examines only a user-specified synthetic P8 journal read-only.
- The `anka_game_kernel`, historical decoder and P8 journal projection schema are preserved unchanged. Current-client semantic evidence, live cross-account event causality, active decision/coordination and execution remain unsupported.
- See `docs/P11_FIGHT_TURN_EVIDENCE_RECONCILIATION.md` and `verification/P11_offline_acceptance_receipt.json`.

### P11 adversarial verification hardening

- Cross-account comparisons no longer throw on malformed actor maps and untyped account views: they produce stable failure reasons.
- Per-account `missing_decision_fields` report absent HP/max HP/AP/MP/cell/cooldown facts separately from turn-owner agreement; partial observations are never actionable.
- Read-only `fight-audit` returns exit 10 on a diagnosed contradictory owner/fight/evidence view, with GPT-friendly incident evidence. The `fight-demo` intentionally injects disagreement and remains a successful demonstration.
- Added tests for malformed account inputs, malformed actor maps, incomplete field coverage, CLI exit semantics, and forbidden package dependencies.
- **No live admission and no physical input.**

## P12 Kernel-backed research-only Decision preview — 20 October 2026

- Added `anka_contracts.decision` with immutable, validated, non-executable cast probes and reports.
- Added pure `anka_decision.probe` enforcing session, account generation, fight, revision, turn ownership and actor evidence checks.
- Consults the **unchanged real Game Kernel** for grade static definition and cast-availability rejection (AP, cooldown); no duplicate spell rules.
- Explicitly reports unknown turn counters, map geometry/LoS, equipment and current-build proof. A plausible synthetic cast remains `RESEARCH_ONLY`, never legal/executable.
- `anka_app.decision_offline` wires the preserved kernel to synthetic in-memory events and existing integrity-audited P8 journal snapshots; added `decision_demo.bat` and `decision_audit.bat`.
- Deliberately excludes tactical scoring, action execution and current-client truth. Physical input remains disabled.
- Tests include account/fight/generation scope collisions, forged bool identifiers, stale revisions, invalid actors, cooldown ambiguity, fake authority, database corruption and CLI semantics.
- See `docs/P12_KERNEL_BACKED_READ_ONLY_DECISION_PROBES.md` and `verification/P12_offline_acceptance_receipt.json`.

## P13 map-aware, research-only Decision extension — 20 October 2026

- Added bounded immutable map-research contracts and a kernel-backed geometry/cast and movement evaluator.
- Uses the existing `GameKernel.spell_decisions.evaluate_cast_cell` and `GameKernel.fight_queries` APIs without duplicating game rules. Synthetic full-map fixtures exercise LoS, occupied target cells, AP, per-turn/target uncertainty, MP paths and obstacles.
- Preserves P12 scope/evidence gate; refuses incomplete geometry, stale/cross-account state, actor resource mismatch, unknown occupancy, unreconciled live walkability overrides and statically impossible origins.
- New `map_demo.bat` and independent adversarial tests; all results are preview-only and cannot reach Execution.
- No current-client protocol decoding, real geometry attestation, tactical scoring, Windows acceptance, or live input is added.
- See `docs/P13_KERNEL_MAP_AWARE_OFFLINE_RESEARCH.md` and `verification/P13_offline_acceptance_receipt.json`.

## P14 bounded movement-plus-cast tactical research — 20 October 2026

- Added `anka_contracts.tactical_research` with immutable research-only contracts and strict bounded candidate/sequence validation.
- Added `anka_decision.tactical_research`: calls unchanged Kernel movement/reachability, hypothetical projection and cast-legality APIs; no duplicate rule engine, no executable plans.
- Candidate enumeration covers standing still / reachable movement and up to 12 targets; tests include blocked cells, MP budgets, AP budgets, malformed inputs, reactive movement effects, stale scope, missing history, and kernel exceptions.
- Sequence-of-spells AP budget is **cost-only**. Full sequence legality, dynamic spell effects, current-client equipment, true turn history, and action outcomes remain unknown and are never assumed successful.
- Added `tactical_demo.bat` with synthetic data, integrated passive diagnostic record and a strict no-physical-input invariant.
- End-to-end live gameplay, Windows bridge, current-build adapter certification, active FightAI and execution are **not** implemented; `start` remains blocked by design.
- See `docs/P14_BOUNDED_KERNEL_TACTICAL_RESEARCH.md` and `verification/P14_offline_acceptance_receipt.json`.

## P15 deterministic synthetic tactical scoring — 20 October 2026

- Added independent immutable `anka_contracts.tactical_scoring` fixture-priority contracts and `anka_decision.tactical_scoring` research ranker; app-only composition at `anka_app.scoring_offline`.
- Preserves P14 kernel-only legality and path judgments. Example CRA damage-leaning, ENU control-leaning and balanced weights use **synthetic** target priorities, not real damage, MP removal or danger predictions.
- Illegal, unknown, AP-over-budget and multi-cast candidates do not receive strategic scores; repeated casts remain budget-only, not a simulated or certifiable sequence.
- Full named score contributions, bounded candidates, deterministic ordering, explicit scenario caveats and passive diagnostic event.
- Hardened P14 and P15 immutable reports against construction or dataclass replacement with forged executable/authoritative flags.
- Added `scoring_demo.bat` and `scoring-demo` CLI; live input, current-client semantics and autonomous gameplay remain unavailable by design.
- See `docs/P15_SYNTHETIC_TACTICAL_SCORING.md` and `verification/P15_offline_acceptance_receipt.json` for release checks. **Do not interpret passing research tests as live readiness.**

## P16 offline stateful sequence research — 20 October 2026

- New independent immutable sequence contracts and `anka_decision.sequence_research` call the **unchanged Game Kernel's** exact cast projection, rather than declaring multi-cast AP totals executable.
- Bounded explicit 1–4 casts and one already-gated P14 movement choice. Each hypothetical step consumes the previous projection *only* if complete, deterministic, free of live requirements/missing inputs, and structurally consistent with cast histories and actor resources.
- Historically known Flèche Glacée example reports live-required AP/damage/HP observations and stops after one cast. Separate explicit effect-free synthetic test shim exercises sequential AP and cast-history progression; this does not certify the real spell.
- Malformed/forged projection results, incomplete evidence, uncertain movement effects, stale account state and forged authorization flags fail closed with stable diagnostic reason codes.
- New `sequence_demo.bat` and tests; fully offline, non-actionable, no state journal writes and no physical input.
- Outstanding: current-client semantic/live authority, server outcomes, complete real spell effect simulation, current Windows acceptance, executed coordination/workflow/fight AI. `start.bat` remains blocked.

## P17 deterministic Coordination/Workflow research — 20 October 2026

- Added immutable *synthetic-only* `PartyMember`, `PartyFixtureEvent`, `PartyTimelineReport`, `SyntheticFightOutcome`, and `MissionResearchReport` contracts.
- Implemented pure `anka_coordination.party_lifecycle.replay_party` with Ready → fight start → turn owner → End-Turn intention → confirmed Turn End → next owner handoff. On incorrect ordering, wrong account generation/fight epoch, overlap, disconnect, or expired logical-tick deadline, it quarantines the first contradiction and never emits an executable action.
- Added `anka_workflow.mission_research.evaluate_mission`; fight-end does not imply victory and separate outcomes are required. The Workflow implementation depends only on contract DTOs.
- Added `coordination_demo.bat` for bounded synthetic happy/conflict scenarios and passive GPT-friendly diagnostics. The CLI returns 10 for coordination conflicts, 40 for failing commands and 0 for completed read-only audits without coordination contradiction.
- P17 source verification and fresh extraction result: see `verification/P17_offline_acceptance_receipt.json`. **Live start remains blocked, no actor/window/process/protocol certification is claimed.**
- Historical status sections above are snapshots from earlier releases; where they disagree with later milestones, newer dated milestones take precedence. Missing live acceptance remains an outstanding gate.

## P18 durable offline Execution/Outcome journal — 20 October 2026

- New `anka_execution` owns the fixture-only state machine and transaction-backed SQLite action ledger; no input backend or live observer is introduced.
- Distinguishes `PREPARED`, `DISPATCH_UNCERTAIN`, `CONFIRMED`, `REJECTED`, `CANCELLED`. An action whose dispatch boundary was committed cannot be sent twice or cancelled merely because a caller timed out.
- `action_id`, semantic action key, window process generation, account/actor, fight/turn, revision and synthetic evidence are checked before any transition. One uncertain dispatch exists globally at a time.
- Hash-chain, projection, and evidence-table audits detect corruption; injected failures between writes roll back atomically; SQLite read-only audit works on a single snapshot.
- `execution_demo.bat` creates synthetic action histories with passive incident reports; `execution_audit.bat` audits saved fixture journals and returns 10 when dispatch is unresolved. Both are observation-only.
- CLI `verify` timeout now captures the stalled test tail and produces a named failure, rather than a generic subprocess error.
- See `docs/P18_DURABLE_ACTION_SETTLEMENT_OFFLINE.md` and `verification/P18_offline_acceptance_receipt.json` for exact coverage and remaining gates.
- **No current-build protocol certification, real output driver, authoritative outcome matching, or live gameplay is enabled.**

## P19 offline fake-driver integration — 20 October 2026

- Added strict non-authoritative simulation contracts in `anka_contracts`; no synthetic observation can be forged into a live action grant.
- Added an input-free `OfflineFakeInputDriver` with deterministic simulated outcomes and fault injection: no send, throw before/after possible attempt, crash after durable dispatch and crash after fixture attempt.
- Added `OfflineDispatchCoordinator` using the P18 SQLite ledger. Durable pre-dispatch boundary must commit before any fake attempt, and no uncertain result may be retried automatically. Window/account/generation, character, focus and calibration are checked twice with two **distinct** fixture observations; missing re-attestation fails closed.
- Global CRA/ENU uncertain dispatch contention cancels only the new PREPARED action and preserves the existing uncertain one. A fake driver receipt alone cannot settle an action; only independently provided, correctly scoped synthetic outcome evidence can.
- Added `execution_sim_demo.bat`, passive incident export and P19 adversarial tests. All inherited systems and the 165 R5.198 reusable asset files are preserved.
- This is an **offline simulation only**. No physical input, Windows acceptance, current-build protocol/Canonical certification, authoritative state, or live gameplay. `start.bat` remains intentionally blocked.
- See `docs/P19_OFFLINE_FAKE_DRIVER_EXECUTION_INTEGRATION.md` and `verification/P19_offline_acceptance_receipt.json`.

## P27 — passive Capture → Protocol startup integration (20 October 2026)

- Optional in-memory `CapturePoll` forwarding from the Windows capture trial to the existing read-only Protocol inspector via composition, without cross-package implementation imports.
- Allows bounded wire-envelopes, historical-catalog difference counts, quarantines and packet-loss limitations in privacy-sanitized incident reports. No raw packet contents, endpoints, accounts, wire names or flows are serialized.
- Exact current-client build, authoritative semantics and physical input are **not** certified; the historical reference is used only for comparing observed wire formats.
- Only `setup.bat` and `start.bat` are operator commands.
- The isolated new test coverage is in `tests/test_p27_live_wire_observation.py`; an earlier full-suite run stalled, so grouped/targeted outcomes must be reported independently. See `verification/P27_offline_acceptance_receipt.json`.

# P28 — Strict protocol-evidence intake (offline, no automatic activation)

- Independently versioned, hashed ZIP evidence packages can be staged in
  `protocol_updates/` and audited during the ordinary `setup.bat` flow.
- New isolated `anka_protocol.evidence_intake` validates member/path/hash safety,
  exact build, case/oracle references and minimum gameplay-capability coverage.
  `anka_app.protocol_updates` owns the integration and sanitizes observability.
- **No protocol adapter changes, new authoritative Canonical events, mouse/keyboard
  inputs, or live readiness claims.** Staging is read-only; `start.bat` remains blocked.
- See `docs/P28_PROTOCOL_EVIDENCE_INTAKE.md` for the exact format and limitations.


## P37 — resumable offline verification and process-tree timeout fences (2026-10-21)

- Added checkpointed module-isolated developer verification with a source/test/config/fixture/environment fingerprint. Completed modules survive interrupted runs, but changed inputs invalidate old PASS entries.
- Added bounded module batches that report `INCOMPLETE` until the exact test inventory completes.
- Added POSIX process group / best-effort Windows process-tree timeout handling for tests that spawn nested CLI children.
- New P37 test module: 11 tests. Selected P24/P33–P37 plus protocol-architecture: 153 PASS. Check/setup PASS, start intentionally exit 40.
- Full 54-module isolated verification is **incomplete**, NOT full PASS; an attempt recorded 10 passed modules before outer timeout. Current-client protocol and Windows live acceptance are still missing.
- **Roadmap scope estimate 88%** (subjective); complete live CRA+ENU acceptance **0%**. See `docs/P37_CHECKPOINTED_RECOVERABLE_VERIFICATION.md`.


## P50 — Source-bound PCAPNG flow inventory (2026-10-21)
- Added bounded research-only multi-flow inventory, opaque flow candidates and exact-capture replay selection; forged candidate lists and stale snapshots are refused.
- Added normal setup/check synthetic preflight and two regression modules.
- Full checkpointed module-isolated suite: 75/75 modules, 1,306 tests PASS on Python 3.13.5. `check`/`setup` PASS; `start` safely blocked (40).
- Roadmap coverage remains an unmeasured historical estimate (92%); zero current-client CRA/ENU end-to-end acceptance. No Windows bridge compilation or real input acceptance claimed.
- Details: `docs/P50_PCAPNG_MULTIFLOW_DISCOVERY_AND_EXACT_SNAPSHOT_SELECTION.md`; receipt: `verification/P50_offline_acceptance_receipt.json`.

## P58 (offline admission quarantine)

* Implemented: scoped untrusted packet/character/semantic rehearsal; per-message SHA-256, capture-hash consistency, source identity/ordering, distinct claim checks, and privacy-safe aggregate review.
* Safety: `STRUCTURALLY_CONSISTENT_UNTRUSTED` is non-authoritative. All review results carry mandatory trusted capture/build/identity/writer blockers; zero durable Canonical commits and zero physical input.
* Verification: 85/85 isolated modules, 1,491 test methods PASS (fingerprint `02712e6027b60bef6c83e7fa1a8832e2584437e55e639b798f9c769ee5a7fc75`); focused 249 tests + 40 subtests.
* Remaining: actual current-client witnesses, independent authoritative protocol/build certification, Windows host and identity attestation, production state integration, and end-to-end live acceptance. Estimated roadmap coverage 92% (subjective), live missions 0%.
