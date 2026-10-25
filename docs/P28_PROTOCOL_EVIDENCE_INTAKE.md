# P28 — Protocol evidence intake for recurring client updates

## Why this exists

Dofus wire names and field layouts may change roughly every two weeks. The
original R5.198 adapter is **historical**. An update cannot be declared compatible
from the `.proto` filename, wire-name similarity, or passing old synthetic tests.
P28 introduces a safe staging boundary **without modifying any live decoder**.

## Operator workflow: still only `setup.bat` and `start.bat`

1. Create a `protocol_updates` directory next to `setup.bat` if it does not exist.
2. Place up to three **reviewed** protocol evidence ZIPs there, one per client build.
3. Run `setup.bat` normally. It will audit ZIP members and SHA-256 hashes and
   report coverage and uncertainty in the usual diagnostic run.
4. **No package is activated**, even if all intake checks pass. ANKA_NEXT remains
   non-executable until adapter-specific contract replay, independent golden
   outcomes, current-client coverage, account/window attestation, and supervised
   live acceptance exist.
5. `start.bat` remains fail-closed. No new BAT scripts or dashboard are needed.

To evaluate a single pack during development without installing it, import
`anka_protocol.evidence_intake.inspect_evidence_pack` in Python.

## Strict ZIP layout (manifest at archive root)

The user-created ZIP must contain `manifest.json`, at least one PCAPNG file and
at least one JSON oracle (annotation), plus optional screenshot, game log,
video, and `.proto` evidence files. Every ZIP member must be listed and hashed.
The package is never extracted or executed by ANKA.

```json
{
  "schema": 1,
  "package_kind": "ANKA_PROTOCOL_EVIDENCE",
  "protocol_build": "Dofus 3.7.11.11",
  "adapter_id": "dofus_3_7_11_11_candidate",
  "sources": [
    {"path": "captures/sample.pcapng", "sha256": "<64 lowercase hex digits>", "kind": "pcapng"},
    {"path": "oracles/facts.json", "sha256": "<64 lowercase hex digits>", "kind": "oracle"},
    {"path": "witness/hp.png", "sha256": "<64 lowercase hex digits>", "kind": "screenshot"}
  ],
  "cases": [
    {"id": "cra_hp_after_spell", "capability": "actor_hp", "capture": "captures/sample.pcapng",
     "oracle": "oracles/facts.json", "oracle_id": "observed_hp_01",
     "witness": "witness/hp.png", "account_role": "leader"}
  ]
}
```

`oracles/facts.json` example (expected values come from independent user
observations, **not** from the decoder being tested):

```json
{
  "schema": 1,
  "observations": [
    {"id": "observed_hp_01", "capability": "actor_hp",
     "expected": {"actor_id": 123, "hp": 2800}}
  ]
}
```

These numbers are EXAMPLES only and not real evidence. A successful intake
checks file integrity and reference consistency, not screenshot contents,
packet semantic correctness, or whether an annotation was honestly obtained.
Captured traffic is private and must be inspected before sharing it.

## Required current-build gameplay coverage

- Character identity
- Fight start; Turn start; Turn end
- Actor cell, HP, AP, MP
- Spell cast; Action outcome

Additional useful cases include Ready, Join, Fight End, result, movement and
cooldown. Missing required capabilities are reported explicitly, not filled
from historic fields or assumed to be zero.

## Security and architectural invariants

- Strict member allowlist, hashes, member-count and decompression-size caps;
  reject absolute/traversal/Windows paths, duplicate names and ZIP symlinks.
- Never execute `.proto`, scripts or adapter code from untrusted evidence.
- Never export raw capture, private filenames, expected values or screenshots
  in a normal diagnostic report. Export only safe counts, build label, digests,
  capability presence and stable error codes.
- All evidence is classified **research / unverified**. Not a bypass to
  Canonical authoritative state, FightAI, physical input, or new adapter use.
- Old adapter/fixture suites remain intact; a future update must be tested
  against both new-build observations and permanent historical regressions.
- Live packet drops, encrypted/unobservable traffic, and missing independent
  oracles cannot be solved by assuming optimistic values.

## Next certification stage — NOT yet implemented

1. Independently review evidence quality; correlate each oracle with exact
   packet and actor/turn provenance.
2. Implement a **new version-local adapter**; no edits to Kernel/Decision/Execution.
3. Replay real labeled observations against exact expected Canonical facts.
4. Perform negative/contradictory/unknown-field tests and capability gates.
5. Certify Windows account identity, capture continuity and current-build
   semantics on the actual host before enabling authoritative admission.
6. Activate only at a clean session boundary, with reversible version pinning.

P28 is deliberately **intake**, not a claim that all six steps are complete.
