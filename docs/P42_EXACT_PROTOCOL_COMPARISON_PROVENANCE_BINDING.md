# P42 — Exact protocol comparison/intake binding (offline, fail closed)

**Release:** P42, 21 October 2026. **Only operator BATs:** `setup.bat`, `start.bat`. **Live accepted:** 0%. **Subjective weighted roadmap coverage:** 88% (unchanged; *not* a software-quality score).

## Why this milestone matters

The original P40/P41 protocol-evidence path already protected the evidence ZIP from being replaced *between* `inspect_evidence_pack()` and `compare_pack()` during an ordinary `setup` audit. However, `anka_protocol.capability_matrix.assess_capabilities()` accepted a comparison object solely on case indices, capabilities and success counts. It did **not** prove that its successful comparisons corresponded to the same **archive bytes, declared exact client build, and adapter** as the intake report. Reusing a successful comparison from another evidence bundle with the same case layout could falsely count `MATCHED_RESEARCH_ONLY` coverage. It did not grant live authority, but corrupted the independent research grade that should support future protocol upgrades.

**Independent pre-fix reproducer:** the P42 test suite failed in nine assertions/subtests against the unmodified P41 implementation, including mixed archive hash, mismatched build/adapter, missing provenance, and inconsistent `case_count`. The original comparator also omitted any archive-bound identity from its result.

## Implementation

1. `anka_protocol.evidence_intake.evidence_binding_id(archive_sha256, protocol_build, adapter_id)` computes one deterministic **SHA-256/Base32 opaque binding** of the three values, with unambiguous JSON tuple serialization. This is *evidence identity*, **not a signature or independent witness attestation**.
2. `anka_app.protocol_evidence_compare.compare_pack()` adds `comparison_binding` to *every* result, including fail-closed/unsupported paths. The comparison result does **not** export raw build text, adapter ID, raw packet names/values, or underlying resource observations; previous P30 privacy assertions remain intact. For the same ZIP/build/adapter the binding is stable.
3. `anka_protocol.capability_matrix.assess_capabilities()` recomputes that binding from the validated `IntakeReport`. A missing, stale, altered or mismatched comparison is **not considered valid**, and no `MATCHED_RESEARCH_ONLY` research count is credited. It also rejects an incorrect/bool `case_count` even when row indexes look valid.
4. Updated synthetic consumer-contract fixtures in `tests/test_p32_protocol_capability_assessment.py` to supply a valid binding; these tests exercise the actual validation rule rather than relying on legacy unbound mock results.
5. Added `tests/test_p42_comparison_provenance_binding.py` (**8 new unittest methods**, including subtests) covering independent positive pairing, mixed evidence ZIPs, build and adapter drift, missing bind, mismatched counts, the *real setup-time staging orchestrator*, and privacy-preserving output.

**Boundaries retained:** P42 does **not** trust an evidence ZIP as executable code, activate a protocol adapter, certify a current client, admit production Canonical events, send physical input, or infer server spell outcomes. It does not change the Game Kernel, calibration, window code, AI, coordination, workflow or action ledger. Research oracles and synthetic fixtures still need genuine current-build independent witnesses before live acceptance.

## Verification

- Focused `pytest` P28–P42 + protocol architecture: **344 passed and 17 subtests passed**.
- Complete resumed *module-isolated* `unittest` inventory: **60/60 test modules, 1,129 tests passed**, fingerprint bound to source, tests, assets and host environment. Several bounded batches hit the outer execution limit after saving checkpoints; their completed modules were preserved. Final run returned `PASS`; it was not a single uninterrupted one-process pytest run.
- `python -m anka_app.cli check`: exit **0**; architecture audit **13 packages / 248 Python files**, no import violations; calibration and **165 reused assets** validated.
- `python -m anka_app.cli setup`: exit **0**, same safety boundaries and offline smoke.
- `python -m anka_app.cli start`: **40**, expected `LIVE_RUNTIME_NOT_IMPLEMENTED`, with incident ZIP integrity **PASS**.
- Only root `setup.bat` and `start.bat` retained; no dashboard, demo launcher, secondary handoff artifact or test driver exposed to the operator.

**Important scope:** the full tests ran on Linux/Python 3.13 in an offline environment. Windows/Npcap, client/character identity, current Dofus protocol decoding, real Ready/turn handoff, input and server-confirmed fight effects remain unverified. Live acceptance = **0%**. The package metadata version stays unchanged because it is not a release certification value.

## Next concrete dependency

Collect authentic current-build PCAPNG, exact client/build/process/flow proofs, and independently witnessed AP/MP/HP/cell/cast/turn/fight outcomes for both characters. Qualify a version-pinned adapter and protect producer/consumer causality before implementing production Canonical admission. Missing evidence must remain explicitly blocked rather than being replaced with another synthetic authorization flag.
