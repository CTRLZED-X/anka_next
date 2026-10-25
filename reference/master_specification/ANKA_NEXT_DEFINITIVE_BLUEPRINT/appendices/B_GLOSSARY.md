# Appendix B — Glossary

**ActionKey** — Canonical semantic fingerprint of a proposed action used for quarantine/anti-loop; not necessarily ActionId.

**ActionId** — Unique identity of one logical requested action.

**AttemptId** — Identity of one physical/admission attempt associated with an ActionId.

**Adapter** — Version-specific Protocol implementation translating wire dialect into stable candidate semantics.

**Authority** — System allowed to assert/mutate a specific category of truth or external effect.

**Canonical event** — Stable semantic observation admitted into durable ordered journal, independent of raw protocol names.

**Canonical cursor** — Monotonic durable position in the committed event journal for its authority.

**Candidate event** — Protocol output not yet committed as Canonical truth.

**Capability** — Semantic feature needed for an action/scenario, e.g. turn owner or AP/MP.

**Client generation** — Exact incarnation of a Dofus process/window binding; prevents stale PID/HWND reuse.

**Commit coordinator** — Canonical transaction path that atomically persists events/checkpoint/evidence using injected pure state projection.

**Contract** — Stable immutable data/API meaning exchanged between systems.

**DecisionFrame** — Frozen verified state and constraints presented to a planner.

**Derived evidence** — Deterministic computation from cited source evidence, not directly observed.

**Epoch** — Generation identity delimiting lifecycle context (world/fight/turn/etc.).

**Evidence gap** — Required proof absent/stale/failed to collect.

**Fail closed** — Do not perform affected risky action when required safety truth is unknown.

**FightEpoch** — One exact fight incarnation; prevents late events from previous fight being reused.

**Flight recorder** — Bounded in-memory/recent diagnostic event window pinned when incident occurs.

**Handoff** — Verified transition of turn/control from one actor/account to another.

**Idempotent** — Reprocessing the same logical input does not apply a state change twice.

**Kernel** — Pure deterministic game rules/mechanics/knowledge engine.

**Live State** — Deterministic current snapshot derived from committed Canonical history.

**MAY_HAVE_SENT / UNCERTAIN** — External physical input may have occurred; must not be blindly repeated.

**Modular monolith** — One deployable application whose source is separated into enforceable independent systems/packages.

**Observation** — Evidence collected externally; not automatically authoritative for every semantic meaning.

**Opaque traffic** — Known wire instance intentionally assigned no gameplay semantics/state mutation based on exact evidence.

**Permit** — Generation-scoped Coordination/Execution authorization input; not a permanent permission.

**Port** — Interface/protocol describing a dependency without importing concrete implementation.

**Projection** — Mapping from semantic target (e.g. cell/slot/control) to current screen interaction evidence.

**Provenance** — Evidence of where a value/event came from, including source IDs/version/scope.

**Quarantine** — Prevent reusing same action/key under unchanged semantic conditions after a known rejection/failure.

**Reducer** — Pure state transition logic: previous snapshot + committed event -> next snapshot candidate.

**Replay** — Reprocess immutable evidence/events to reproduce behavior without live game action.

**Settlement** — Verification that required authoritative consequences of an action have been reconciled.

**Snapshot** — Immutable LiveState view at an exact committed cursor/epoch.

**StateProjectorPort** — Boundary allowing Canonical commit coordinator to request pure next-state/checkpoint calculation without concrete import.

**TurnPermit** — Coordination proof that a given account/actor may act in a specific fight/turn generation.

**Unknown** — Truth not established; never a synonym for zero/false/success.

**WireEnvelope** — Capture-level ordered transport bytes plus connection/gap identity, without game semantics.

**Zero-input simulation** — Full software-path verification using a fake driver and asserting no OS physical input.

