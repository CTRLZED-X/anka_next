# P15 — Deterministic tactical scoring research (synthetic only)

**Implementation status:** implemented and tested offline; **NOT an executable AI or live-certified strategy**. This document describes real code added on top of the P14 reference foundation. There is no physical game input, current-build protocol certification, estimated damage engine, MP removal simulator, or confirmed tactical game-state source.

## Why this boundary exists

P14 can test possible move → first spell combinations with the preserved game kernel but does not rank them strategically. Inventing expected damage or control based on a spell's name would be a dangerous shortcut. Instead P15 accepts **explicitly synthetic scenario priorities** to exercise the scoring and explanation interface while preserving the kernel as sole source of legality.

## Packages and API

| Component | Source | Responsibility |
|---|---|---|
| Immutable contracts | `src/anka_contracts/tactical_scoring.py` | Validate every synthetic priority, cover all requested cells, forbid auth forgery |
| Research ranker | `src/anka_decision/tactical_scoring.py` | Invoke real P14/kernel research, classify and rank previews with integer arithmetic |
| Composition demo | `src/anka_app/scoring_offline.py` | Construct fixtures and connect kernel to scorer; emit passive diagnostic summary |
| Operator CLI | `src/anka_app/cli.py` | `scoring-demo` routing and error diagnostics |
| Windows launcher | `scoring_demo.bat` | Calls existing `_entry.bat` |
| Regression tests | `tests/test_p15_tactical_scoring.py` | Legality, uncertainty, deterministic scoring, no physical authority |

The ranker imports P14 Decision and shared contracts, not Capture, Protocol, Live State internals, Client or Execution.

## Synthetic scoring equation

The **only** permitted priorities are integer scenario annotations from 0 to 5:

- `damage_priority` means a tester *prefers* a given target in the synthetic scenario. It is **not** predicted damage or a kernel effect.
- `mp_control_priority` is an artificial preference value, **not** a measured or predicted number of removed MP.
- `exposure` is an artificial risk input, **not** a line-of-sight threat map or estimate of incoming damage.
- `mp_cost` comes from the Kernel's path analysis for the supplied scenario.

For a statically legal, single-cast research preview:

```
illustrative_score = damage_weight * synthetic_damage_priority
                   + control_weight * synthetic_mp_control_priority
                   - 2 * synthetic_exposure
                   - 1 * kernel_mp_cost
```

| Explicit research policy | Damage weight | Control weight |
|---|---:|---:|
| `CRA_DAMAGE_RESEARCH` | 4 | 1 |
| `ENU_CONTROL_RESEARCH` | 1 | 4 |
| `BALANCED_RESEARCH` | 2 | 2 |

These policy names **do not** detect or attest a character's class. A future class-aware strategy must use certified character identity and real spell/effect models. They are example priorities only. Scores can be negative, are deterministic, and are **not probabilities, damage values or probabilities of winning**. They contain named integer contributions so a GPT-assisted investigation can explain every ordering choice.

## Rejection and unknown-data handling

- Any P14 scope/evidence/kernel block propagates without ranked candidates.
- The Kernel's `ILLEGAL` decision becomes `REJECTED_KERNEL`; unknown or unevaluated candidates are unscored.
- A sequence costing more AP becomes `REJECTED_AP_BUDGET`.
- Any sequence with two or more spells is **unscored** even if its AP sum fits; cooldowns, counters, target validity and dynamic effects have not been simulated between casts.
- If required Kernel resources or paths cannot be reconstructed, there is no score.
- A statically legal move+cast preview can be assigned a **research scenario score** but records movement confirmation/trigger uncertainty; this is **not execution feasibility**.
- Synthetic target and position values must provide full, unique, typed coverage. Missing values cannot silently default to zero. Invalid policies are rejected with `P15_POLICY_UNSUPPORTED`.
- The returned reports always serialize `preview_only=true`, `actionable=false`, `authoritative=false`, `physical_input_permitted=false`, and `selected_action=null`. Attempts to reconstruct P14/P15 reports with forged authority flags now raise errors.

## Example

Use `scoring_demo.bat` on Windows after setup or `PYTHONPATH=src python -m anka_app.cli scoring-demo CRA_DAMAGE_RESEARCH` on a supported Python host. Optional other policy: `ENU_CONTROL_RESEARCH`, `BALANCED_RESEARCH`.

The demonstration uses the synthetic actor with 11 AP and 5 MP on cell 215; the Kernel evaluates moves 215/201/400 and targets 229/220. The synthetic CRA policy assigns the target cell 229 a larger priority, but does not infer real spell damage. Scoring may favor moving to 201 in this synthetic exercise because of lower fixture `exposure` despite the extra MP cost. The entire output remains observation-only.

## Acceptance criteria

- The previous P14 468-test suite remains green.
- Adversarial scoring regression tests pass: invalid priorities, duplicate/incomplete values, malformed profiles, illegal target, AP overspend, cast history uncertainty, dynamic movement effects, stale account generation, contradictory geometry, kernel exception, deterministic behavior, immutable records and CLI safe failure.
- No call to Execution or operating-system input libraries; the live `start` command remains blocked.
- Full archive verification passes from a clean ZIP extraction.

## Unfinished work

Do **not** use the scores to operate the game. To approach real tactical choices in later milestones ANKA still needs trustworthy current-build protocol data, authoritative state, actual spell effects and equipped spell slots, dynamic movement/cast effects, target-specific cast limits, reactive effects, enemy behavior and win/loss evidence. Only then can a separately certified Decision→Execution contract be discussed. Earlier intermittent suite-launch stalls also remain a diagnostic issue until reproducible cause is identified.
