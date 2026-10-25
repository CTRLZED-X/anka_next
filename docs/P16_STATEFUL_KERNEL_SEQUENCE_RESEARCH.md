# P16 — Stateful, kernel-backed sequential cast research (synthetic only)

## Status and scope

P16 adds **non-executable** bounded sequential hypothetical casting to the P14/P15 offline Decision foundation. It uses the preserved `SpellDecisionService.preview_cast` rather than adding a second spell-effects/range/LoS/cooldown implementation. The planner accepts 1–4 explicit cast steps after a Kernel-validated position choice. The projection of one step is fed to the next **only** when the Kernel reports deterministic, complete effects, has no missing inputs or live requirements, and its returned history/projection passes integrity checks.

The existing Flèche Glacée grade 3 example is *not* such a spell: the preserved kernel needs live AP/damage/HP results. P16 deliberately stops after step 1 and reports which server-authoritative observations are missing. It can still display provisional AP spent and updated cast-history counts but **does not** treat these as proven live effects.

## Separate packages, unchanged kernel

| Package/module | Ownership | Input and output |
|---|---|---|
| `anka_contracts.sequence_research` | Immutable sequence request, step results and report; 4-step cap and no authority flags | `SequenceResearchRequest` / `SequenceResearchReport` |
| `anka_decision.sequence_research` | Gate with P14 map/actor/evidence tests, then compose Kernel projection per step | Pure `inspect_sequence_research` |
| `anka_app.sequence_offline` | Example synthetic fixtures and passive diagnostic event | JSON-safe result with `physical_input_sent=false` |
| `anka_app.cli` / `sequence_demo.bat` | Read-only operation | `sequence-demo` |
| `tests/test_p16_sequence_research.py` | Synthetic/adversarial regression | No Windows/game dependency |

There are no new dependencies on capture/protocol internals, execution, game input or mission controllers. The Game Kernel was not modified. P16 does not introduce a dashboard or a live planner.

## Exact algorithm

1. Require validated, bounded request with an exact P12 scope and a P14 movement cell.
2. Run the complete P14 evidence, static geometry, identity, cooldown, cast-constraint, Kernel movement and cast gates.
3. Reject invalid first candidate, unreachable cell or unresolved movement-dependent effects before attempting sequence research.
4. Use immutable `FightProjectionService` to move the actor, spend MP and append an observed-*hypothetical* movement record. This is **not** server movement confirmation.
5. Evaluate step N by calling the existing Kernel `spell_decisions.preview_cast` with the latest hypothetical `FightContext`.
6. If the result is rejected, unknown, partial, live-authoritative or contradictory, **stop** and emit a step-specific reason. Do not evaluate N+1.
7. Only continue after deterministic complete projection with no external requirements, verified origin scope and exactly one matching cast added to known turn/global histories, with non-negative resources.
8. Always return `actionable=false`, `authoritative=false`, `physical_input_permitted=false`, `selected_action=null`, even if every synthetic step passes.

The Kernel itself handles AP, cast history, target identity, availability, cooldowns and ordered effect projection; P16 verifies the returned projection does not contradict its input. It does not implement a parallel combat-rules engine.

## Regressions that matter

- A first cast that needs server-confirmed damage/AP is **not** followed by an imagined second cast.
- P14 stale scope, wrong fight, inconsistent actors, absent turn history, insufficient AP or wrong geometry reject before any preview.
- Unreachable movement and MP-triggered reactive effects block continuation.
- Incorrect/spoofed complete projections (missing history, wrong target, invalid type) fail closed.
- A specifically injected *synthetic deterministic effect-free* projection verifies that the second step receives the first step's reduced AP and expanded cast history. The fixture is not a claim about the real spell's damage or legal effects.
- Negative requests and forged authority flags are rejected. No physical input is emitted.

## Limitations — not certified

The user-supplied/current client protocol is not certified. No current-client damage, target-specific cooldown correctness, cast counter completeness, spell equipment/slot binding, map-instance overrides, tackle, movement triggers, enemy state changes, server acceptance or action settlement is available. P16 therefore does not authorize **any** live action or promise a successful multi-spell strategy. End-to-end live acceptance is still pending.

## Run

```bat
sequence_demo.bat
verify.bat
```

On a development host: `PYTHONPATH=src python -m anka_app.cli sequence-demo`. `start.bat` continues to refuse physical gameplay.
