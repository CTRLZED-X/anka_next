# P29 — Exact-source Protocol Evidence ↔ Decoder Comparison

**Status:** Offline research implementation. **No current-client semantic certification, Canonical authority, or physical input.**

## Purpose and limits

P28 validated that a ZIP had the claimed files and internally consistent annotations. It did **not** prove that a semantic adapter agrees with independent observations. P29 adds a strict comparison to show precisely which _fields_ differ without exposing their values.

For now the only locally registered comparator is the **historical Dofus 3.7.10.10** research adapter. An evidence pack for a newer build returns `ADAPTER_UNAVAILABLE_FOR_EXACT_BUILD`; it **never** substitutes the historical decoder. No adapter code, manifest-supplied Python, or `.proto` file from a ZIP is executed.

`setup.bat` automatically inspects staged ZIPs under `protocol_updates/`, then tries research comparison where an exact, trusted locally installed adapter exists. `start.bat` remains blocked for gameplay. **No new Windows commands** were added.

## Optional v1 manifest additions

P28 packs remain backward compatible. To compare an archive, add a `server_ports` array to the manifest and a `selector` to each case. The selector must match the actual decoded message's full capture-wide packet number, inspector-wide message ordinal, direction, wire name, TCP generation and flow digest. The raw flow ID, IP addresses, payload and oracle values are never exported in the normal report.

```json
{
  "server_ports": [40400],
  "cases": [
    {
      "id": "example_ap", "capability": "actor_ap",
      "capture": "captures/evidence.pcapng", "oracle": "oracles/facts.json",
      "oracle_id": "obs01", "account_role": "leader",
      "selector": {
        "packet_number": 2,
        "message_index": 0,
        "wire_name": "jtk", "direction": "server_to_client",
        "transport_generation": 1,
        "flow_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
      }
    }
  ]
}
```

The numbers and digest above are examples, not real evidence. Use a real capture's exact, independently reviewed selectors; do **not** copy this example as an assertion about the game. The selector is metadata for linking an observation to a message, not proof that the mapping is correct.

An oracle might contain `{"id":"obs01","capability":"actor_ap","expected":{"actor_id":777,"ap":9}}` for a controlled synthetic fixture. On actual evidence, the expected values must come from independently witnessed observations, never values copied from the candidate decoder.

## Behavior and diagnostic codes

1. Revalidate the entire ZIP under P28's strict limits, reread it, and pin the digest. If the file changed between inspections, abort with `PACK_CHANGED_DURING_COMPARISON`.
2. Refuse unrecognized build/adapter pairs. This does **not** count as a decoder defect: it means the adapter is not implemented or registered.
3. Require explicit ports and exact selectors; never guess from an actor name or a nearby event.
4. Process each selected capture fully. Reject damaged PCAPNG, sequence gaps, unanchored streams, resets, incomplete framing and semantic schema drift **before reporting any matched observations**.
5. Validate every decoded fact's protocol version, adapter, wire, packet, generation, ordinal and flow digest against its original message.
6. Compare only supported scalar fields. An HP message requiring independently verified local-actor context, a cooldown array, or unknown capabilities remain `CAPABILITY_NOT_MAPPED_OR_CONTEXT_MISSING` / `ORACLE_FIELDS_NOT_COMPARABLE` rather than guessed or scored as correct.
7. Output case-indexed findings such as `FIELD_MISMATCH` with `mismatch_fields: ["ap"]`. **Never output actual expected/decoded values or raw packet data** in ordinary startup diagnostics.

A matched result is `RESEARCH_COMPARISON_MATCHED_NOT_CERTIFIED`. An unmatched case is `RESEARCH_COMPARISON_BLOCKED`. **Both** retain `certified_capabilities=[]`, `live_semantic_certified=false`, `adapter_activated=false`, `canonical_commits=0`, `physical_input_sent=false`.

## Independent verification and next milestone

Automated adversarial tests verify exact matching, wrong values, changed capture after validation, wrong flow/ordinal/name, later TCP gaps, missing selectors/ports, malformed PCAPNG, false authority and unsupported builds. Historical P28 packages without selectors still pass *intake* and receive a precise not-comparable status. The comparator never certifies an adapter simply because it agrees with synthetic data or user-provided oracles.

A future **version-local semantic adapter** must be implemented and added by reviewed project code; this is not an auto-generator for scrambled protobuf fields. Current-build packet captures and independently annotated game observations are still required. Additional gates for account identity, complete fight/turn/resource/action coverage, cross-account chronology and live Windows acceptance remain outstanding before any authoritative Canonical admission.
