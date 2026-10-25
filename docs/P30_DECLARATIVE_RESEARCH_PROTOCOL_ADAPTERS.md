# P30 — Hash-pinned, exact-build semantic research recipes

**Status:** implemented and verified offline only. **No current Dofus client build has been certified; no live gameplay or physical input is enabled.**

## Why this milestone matters

P29 could compare exact packet observations to independently supplied oracle values, but it knew only three historical wire families under Dofus 3.7.10.10. Any new build returned `ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD`. Implementing an entirely new Python decoder for every renamed scalar field is expensive and risks changing unrelated systems.

P30 adds a constrained, **data-only research mapping format** for *reviewed, locally installed* recipes. It supports the narrow absolute resource families AP/MP/range and HP/max-HP with integer actor IDs, nested protobuf field paths, exact wire-name and build matching. More complicated events (turn ownership, spell cast/effects, movement, repeated cooldown collections, class/identity, joins) are **not supported** by this simple recipe engine and require a separately reviewed semantic decoder.

The protocol ZIP in `protocol_updates/` is still **untrusted evidence**. Nothing in that ZIP can install a recipe, change the local registry, run Python, or activate an adapter. A developer must manually review an inferred mapping, install the JSON recipe as part of the **source release**, and update a SHA-256 entry in the local registry. Setup only audits pack evidence using those already-reviewed mappings.

## Source boundaries

- `src/anka_protocol/adapters/declarative.py`: bounded protobuf path interpreter, recipe schema and SHA-256 registry verifier. Imports stable contracts and the existing pure protobuf reader, not Capture/Decision/Execution internals.
- `reference/protocol/research_adapters/registry.json`: shipped with **zero registered new-build recipes**. This is intentional; no current protocol evidence pack was provided to certify a real mapping.
- `src/anka_app/protocol_evidence_compare.py`: chooses the historical adapter only for its exact original build/ID; otherwise loads a reviewed recipe of exactly the requested build/ID. Joins Capture/Protocol only in composition code.
- `src/anka_contracts/canonical.py`: corrects a discovered mismatch: `WireMessage` permits underscores in wire names but `EvidenceRef` previously rejected them. The contracts now agree.
- `src/anka_protocol/api.py`: labels new research-catalog wire observations `RESEARCH_WIRE_OBSERVATION_ONLY` instead of claiming a historical catalog.

## Research recipe format (illustrative, **NOT** a real 3.7.11.11 field mapping)

The following hypothetical recipe is included **only as documentation**; do not register it as live Dofus evidence.

```json
{
  "schema": 1,
  "source_role": "LOCAL_REVIEWED_RESEARCH_ONLY",
  "protocol_build": "Dofus 3.7.11.11",
  "adapter_id": "dofus_3_7_11_11_local_research",
  "rules": [
    {
      "wire_name": "hypothetical_ap_name",
      "direction": "server_to_client",
      "capability": "actor_ap",
      "actor_path": [5],
      "value_path": [9, 3]
    }
  ]
}
```

`actor_path` and `value_path` identify **unique scalar varints** within a protobuf message. Intermediate path elements must be uniquely occurring length-delimited nested messages. Repeated, missing, incompatible, out-of-range, invalid actor, wrong-direction and malformed inputs are quarantined, never defaulted to zero. A HP rule additionally requires `maximum_path`. Non-unique or overlapping mappings cannot be registered. No arbitrary expressions, script execution or imports are supported.

The local registry is another strict JSON object with `schema: 1`, `source_role: LOCAL_REVIEWED_RESEARCH_ONLY` and entries containing `{protocol_build, adapter_id, file, sha256}`. Each filename must be a simple `.json` basename within the local recipe folder, with hash integrity and symlink checks. Duplicated entries or keys are rejected.

## Safe biweekly adaptation workflow

1. Acquire the exact client version, complete relevant captures, and **independently observed** HP/AP/MP/turn/identity/action facts with timestamps and account context. A `.proto` file alone is insufficient to recover field meanings.
2. Stage a P28 evidence ZIP and run `setup.bat`. New build reports `ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD` until a mapping is reviewed. **Do not** extract or execute code from ZIP contents.
3. Manually reverse engineer applicable message layouts. Add a reviewed local recipe (for supported resource shapes) or reviewed adapter source (for complicated semantics). Pin recipe hash in the local registry.
4. Run setup again: P29 compares exact capture sources, selected wire-message provenance, transport continuity and independently provided oracle facts. `FIELD_MISMATCH`, `SEMANTIC_SCHEMA_DRIFT`, and `LOCAL_RESEARCH_RECIPE_REJECTED` distinguish different failure categories. No expected/decoded values are exported in routine GPT reports.
5. Promote **nothing** automatically. Even `RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED` remains research only. Separately qualify actor identity, complete fight/turn epochs, spell and action events, unknown-message isolation, current-build coverage, window bindings and independent live acceptance before any future authoritative state work.

## Scope limits and warnings

- A positive scalar comparison is not a guarantee the mapping is correct outside that fixture. Independently constructed witnesses and comprehensive negative tests are required.
- No executable skill, strategy, UI/dashboard or extra BAT launcher is added. The operator surface remains `setup.bat` and `start.bat`.
- This adapter has no general schema migration for unknown protobuf fields, repeated messages, oneof branches, spell semantics, resource deltas, zig-zag-signed integers, current game encryption or cross-account chronology.
- High-level research events are always `CanonicalDraft` candidates: `canonical_commits=0`, `live_semantic_certified=false`, `adapter_activated=false`, `physical_input_sent=false`.

## Verified gates

The P30 tests include synthetic renamed AP and MP, HP/max-HP, field mismatch, wrong exact build/ID, unregistered recipe, SHA mismatch, duplicate records, schema drift, later TCP gap, wrong wire/direction, ambiguous/repeated fields, bad protobuf types, invalid resource ranges, malformed recipes and code injection attempts, path traversal, symlinks and staging without authorization. See `verification/P30_offline_acceptance_receipt.json` for actual results and remaining readiness gaps.
