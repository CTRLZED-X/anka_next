# Appendix D — Reference Project Evidence & Provenance

## D.1 Reference archive

- File: `ANKA_R5_198_PROTOCOL_OPAQUE_DRIFT_FIGHT_CONTINUATION_HARDENED_LEAN_OFFLINE_VERIFIED_FINAL(3).zip`
- SHA-256: `f1a50a3555cbe89f27d58ef8411cfcb002ec3cd1cd5aefe4546b4285f47f62d6`
- Role: read-only reference implementation/evidence source for ANKA_NEXT design and reuse.

This blueprint does **not** claim the reference ZIP is the final target architecture. It provides proven assets, historical fixes and regression material.

## D.2 Key source areas inspected

`src/anka_game_kernel/` — independent mechanics/rules package.  
`src/anka_platform/capture/` — capture/stream logic.  
`src/anka_platform/protocol/` — adapter SDK, registry, compatibility/certification and versioned adapters.  
`src/anka_platform/live_state/` — reducer/store/SQLite state and event history.  
`src/anka_platform/core/fight/`, `fight_ai/` — fight contracts/planning/policies.  
`src/anka_platform/execution/` — Windows input, control authority, arbiter, settlement/admission.  
`src/anka_platform/party/`, `campaign/`, `scripting/` — current multi-account/workflow coupling.  
`src/anka_platform/calibration/`, `projection/`, `unity_bridge/` — UI mapping and bridge.  
`src/anka_platform/observability/`, `diagnostics/`, `simulation/` — forensic and zero-input foundations.  
`src/anka_platform/web/` — legacy operator UI, not part of target product.

## D.3 Key reference documents

- `ARCHITECTURE.md`
- `DEVELOPMENT_RULES.md`
- `PROTOCOL_UPGRADE_GUIDE.md`
- `LIVE_ACCEPTANCE.md`
- `DEBUGGING.md`
- `00_NEW_CHAT_HANDOFF_R5_198.md`
- `R5_142_COMBAT_ACTION_CONTRACT_QUARANTINE_TURN_LIVENESS_HARDENING.md`
- `R5_151_LATENCY_RECONCILIATION_FOUNDATION_READINESS_HARDENING.md`
- `R5_195_FIGHT_ENTRY_GEOMETRY_INCIDENT_REPLAY_HARDENING.md`
- `R5_196_TURN_HANDOFF_SYSTEMIC_SIMULATION_HARDENING.md`
- `R5_197_CONTROL_PLANE_TAKEOVER_HARDENING.md`
- `R5_198_PROTOCOL_OPAQUE_DRIFT_FIGHT_CONTINUATION_HARDENING.md`

## D.4 Important evidence limitations

- Historical release notes may cite runtime ZIPs/PCAP/Canonical journals not present in the lean reference archive supplied for this blueprint.
- A historical release's reported gate result is not automatically an independently rerun result in ANKA_NEXT.
- Historical calibration/data/protocol build compatibility remains scoped to the environment/build recorded at the time.
- Any future implementation status must cite **new exact receipts** rather than inheriting historical PASS labels.

## D.5 Example reference assets to preserve with manifests

- full `src/anka_game_kernel/` package;
- verified spell mechanics data;
- `gamedata/COMPATIBILITY.json` and required Static/Mapuse data;
- shared 1280×649 calibration containing 22 slots, phase/join controls;
- versioned protocol adapters and exact opaque evidence mechanisms;
- Canonical transaction/reducer semantics;
- action authority/settlement concepts;
- zero-input systemic scenario logic;
- incident/debug evidence formats.

