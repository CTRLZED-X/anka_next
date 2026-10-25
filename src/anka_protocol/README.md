# ANKA Protocol System — P6 wire + P7 research-only semantic boundary

Owns bounded length-prefixed protobuf framing, constrained Ankama `Any`
observation, exact historical-build catalog attestation, **unknown/direction-drift
classification** and evidence-quality receipts.

This system **does not** yet decode gameplay meanings (AP/MP/HP/turn ownership),
emit canonical events, attest accounts, or authorize action. Historical R5.198
`3.7.10.10` metadata are preserved as immutable reference material, **not** as
current-build certification. The full R5.198 adapter cannot be transplanted
unchanged because it imports old platform state and gameplay contracts.

## External contracts

* Input: `CapturedTcpSegment` / `CapturePoll` from `anka_contracts.capture`.
* Output: `ProtocolReceipt`/`ProtocolFinding` from `anka_contracts.protocol`.
* Implementation: `anka_protocol.api.ProtocolInspector`.
* Diagnostics: `LocalDiagnostics.record` (passive; never authority).

## Upgrade rule

A new protocol build requires a separate future semantic adapter, exact-build
attestation, current-build evidence, independent canonical scenario oracles, and
consumer replay certification. No automatic promotion on an unknown wire name.
An unknown message is non-mutating, separately recorded; missing authoritative
data will later block *affected* capabilities, not trigger an indiscriminate
runtime reset.

`protocol_demo.bat` demonstrates synthetic framed wire shape. `protocol_audit.bat`
performs observation-only analysis of a PCAPNG with configured ports and explicit
build. Both commands are offline, safe and disabled from live input.

`anka_app.protocol_offline` owns cross-system source ingestion; the Protocol package imports **only shared contract types**.

## P7 historical semantic mapping

`adapters/historical_semantic.py` ports only R5.198-verified historical *mapping
rules*, not the legacy decoder's stateful game controller. It returns immutable
`SemanticResult` DTOs. This system never imports the Canonical implementation,
never writes a game state, and never infers contemporary protocol compatibility.
See `docs/P7_SEMANTIC_CANONICAL_STAGING.md`.
