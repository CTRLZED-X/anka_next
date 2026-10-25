# Appendix C — Illustrative Contract & Manifest Schemas

These examples communicate shape/semantics. They are **not final generated Pydantic/JSON Schema files**; implementation should create real versioned schemas and tests.

## C.1 Effective run manifest

```json
{
  "run_id": "...",
  "release_id": "...",
  "source_sha256": "...",
  "config_schema": 1,
  "effective_config_sha256": "...",
  "python": "3.13.x",
  "protocol": {
    "observed_client_build": "...",
    "adapter_release_id": "...",
    "adapter_sha256": "...",
    "canonical_schema": "1.0",
    "action_scope_status": {}
  },
  "kernel": {
    "ruleset": "...",
    "game_data_revision": "..."
  },
  "calibration": {
    "profile": "...",
    "generation": "..."
  }
}
```

## C.2 Field proof

```json
{
  "value": 11,
  "status": "KNOWN",
  "authority": "AUTHORITY_COMMITTED",
  "source_event_ids": ["evt-1"],
  "canonical_cursor": 959,
  "fight_epoch": "fight-279",
  "turn_epoch": "turn-1",
  "invalidated_by": null
}
```

## C.3 Protocol certification result

```json
{
  "adapter_release_id": "...",
  "observed_build": "...",
  "structural": "PASS",
  "semantic_replay": "PASS",
  "observe_only": "PASS",
  "actions": {
    "JOIN": "ACTION_SCOPE_ACCEPTED",
    "READY": "ACTION_SCOPE_ACCEPTED",
    "CAST": "BLOCKED_MISSING_EVIDENCE",
    "END_TURN": "BLOCKED_MISSING_EVIDENCE"
  },
  "unknown_critical": [],
  "unverified_scenarios": ["END_TURN_TO_NEXT_OWNER"]
}
```

## C.4 Incident finding

```json
{
  "finding_id": "f-1",
  "failure_code": "TURN_OWNER_UNPROVEN",
  "first_divergent_boundary": "coordination.turn_handoff",
  "owner": "anka_coordination",
  "confidence": "HIGH",
  "supporting_evidence_ids": ["evt-10", "evt-12"],
  "contradicting_evidence_ids": [],
  "missing_evidence": ["expected ENU authoritative TURN_STARTED"],
  "physical_input_state": "NOT_SENT",
  "recommended_next_test": "replay handoff with delayed owner event"
}
```

## C.5 Reuse manifest row

```json
{
  "legacy_path": "src/anka_game_kernel/api/kernel.py",
  "legacy_sha256": "...",
  "target_path": "src/anka_game_kernel/api/kernel.py",
  "target_sha256": "...",
  "reuse_mode": "UNCHANGED_REUSE",
  "semantic_change": false,
  "tests": ["kernel_range", "kernel_los"],
  "scope": "required automation subset"
}
```

