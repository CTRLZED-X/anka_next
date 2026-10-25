# anka_decision

P12 provides research-only kernel-backed cast-availability probes. P13 adds
bounded target-cell evaluation and MP-limited movement queries by calling the
**existing** Game Kernel. Decision never imports Capture, Protocol, Canonical,
Live State implementations, Client, Execution or Workflow.

P14 adds bounded move+cast previews using immutable Kernel fight projections and cost-only multi-cast budgets. It never calls physical input, does not infer confirmed movement, and does not certify executable action sequences.

The `MapResearchRequest` and `MapResearchReport` contracts live in `anka_contracts`;
fixture construction and CLI orchestration live in `anka_app`.

**Not implemented:** current-build certification, authoritative map/character
identity, tactical scoring, live planning and actuation. Every report carries
`actionable=false`, `authoritative=false`, `physical_input_permitted=false`.

P14 notes: AP sums for up to four hypothetical spells are only **cost accounting**.
No cooldown/effect/target-history simulation proves sequence legality. Movement
also remains unconfirmed, including tackle and movement-triggered effects.

P15 adds independently tested, deterministic, integer-only priority **research** scoring. All target/control/exposure values are explicit synthetic fixture opinions, not measured effects or input permits; multi-cast scenarios remain unscored until kernel effect/history projection can be certified. See `docs/P15_SYNTHETIC_TACTICAL_SCORING.md`.

P16 uses the preserved Kernel's actual ordered cast projection for a **strictly synthetic**,
up-to-four-step research trace. A new cast can be considered only when the previous
projection is deterministic, complete, and evidence-consistent. Incomplete effects,
server-authoritative requirements, stale scope, contradictory cast history or
movement effects stop the sequence. Research traces carry no input authority.
