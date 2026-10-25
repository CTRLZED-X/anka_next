# P31 — Fight-event semantic research, deterministic chronology, and exact-source comparisons

**Status:** Offline implementation. No current-client semantic mappings are registered, no authoritative game-state admission and **no physical gameplay input**.

## Engineering objective

P30 introduced hash-pinned, exact-build JSON recipes for scalar resource values. P31 adds a **different, immutable, non-authoritative** contract for six fight-related observations. These are not proven Dofus events; they are hypotheses that must be tested against independently captured and annotated evidence before integration.

| Recipe capability | Research draft | Mandatory unique protobuf varint paths |
|---|---|---|
| `fight_start` | `FIGHT_START_OBSERVED` | `fight_id_path` |
| `fight_end` | `FIGHT_END_OBSERVED` | `fight_id_path` |
| `turn_start` | `TURN_START_OBSERVED` | `fight_id_path`, `actor_path`, `turn_index_path` |
| `turn_end` | `TURN_END_OBSERVED` | `fight_id_path`, `actor_path`, `turn_index_path` |
| `actor_cell` | `ACTOR_CELL_OBSERVED` | `fight_id_path`, `actor_path`, `cell_path` |
| `spell_cast` | `SPELL_CAST_OBSERVED` | `fight_id_path`, `actor_path`, `spell_id_path`, `target_cell_path` |

**Scope deliberately narrow:** `spell_cast` means a hypothetical spell-cast observation, not confirmed success or damage. `fight_end` is not victory. `turn_start` cannot establish server-authoritative ordering across CRA and ENU. Complex spell effects, movement paths, ready/join, identity, spell counters and action outcomes still require a more expressive reviewed adapter with independent evidence.

## Project boundaries

- `anka_contracts.fight_semantic`: `FightResearchDraft` and `FightResearchResult` are distinct from `OfflineStateEvent` and scalar `CanonicalDraft`. Their authority is permanently `RESEARCH_ONLY_NOT_CANONICAL`.
- `anka_protocol.adapters.declarative`: backwards-compatible **recipe schema 1** for existing scalar observations; **schema 2** additionally permits strict event-family rules. A reviewed local recipe must be hash-pinned in `reference/protocol/research_adapters/registry.json`. The shipped registry remains **empty**.
- `anka_app.protocol_evidence_compare`: exact-build/capture/packet/message/direction/generation/flow validation and full-capture finality must pass before an event is compared with complete expected oracle fields. Reports identify field names only, not private field values, player identities, or packet contents.
- `anka_canonical.research_timeline`: a pure, bounded, single-flow chronology validator. It can detect internal contradictions in an offline hypothesis (missing fight start, turn overlap, wrong end-turn actor, cast by non-owner, mismatched fight ID, source reuse), **not** certify a real fight or cross-account chronology.
- Existing authoritative admission and action execution receive no new input; the older research scalar staging gate quarantines these event drafts.

## Illustrative schema-2 recipe (NOT a real protocol mapping)

```json
{
  "schema": 2,
  "source_role": "LOCAL_REVIEWED_RESEARCH_ONLY",
  "protocol_build": "Dofus 3.7.11.11",
  "adapter_id": "sample_offline_research",
  "rules": [
    {
      "wire_name": "hypothetical_turn_begin_wire",
      "direction": "server_to_client",
      "capability": "turn_start",
      "fight_id_path": [2],
      "actor_path": [5],
      "turn_index_path": [9, 3]
    }
  ]
}
```

Every field path must point to exactly one varint at the leaf; ambiguous or absent paths, repeated leaves, incompatible structures, incorrect types, invalid ranges and wrong message directions produce explicit quarantine. More complex or repeated nested protobuf shapes are intentionally not guessed.

For a staged `protocol_updates/*.zip` with a matching **source-reviewed local** recipe and independent oracle, `setup.bat` automatically performs the P28 intake/P29 exact-source/P31 fight-field research comparison. The pack cannot install code or a recipe. Even **all cases matching** means only `RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED`.

## Failure prevention and negative tests

P31 tests reject malformed field layouts, duplicate fields, wrong directions, altered hashes, schema-1 misuse, invalid actor/cell/turn identifiers, conflicting fight IDs, reused source events, missing fight starts and overlapping owners. They verify field-by-field oracle comparison, mismatch privacy, partial-oracle rejection, whole-capture TCP-gap finality and the refusal of Canonical/Execution authority.

## Critical missing evidence and further development

Current Dofus protocol build and its real event meanings **are not established by this milestone**. To progress beyond research, independent real-client traffic/witnesses, exact actor/character binding, complete fight turn/effect event semantics, signed/oneof/repeated protobuf handling, authoritative Canonical acceptance criteria and Windows/client tests must be supplied and verified. None are fabricated from the historical catalog.

**Operator interface:** only `setup.bat` and `start.bat`; no dashboard or new launchers. The latter continues to fail closed for live gameplay.
