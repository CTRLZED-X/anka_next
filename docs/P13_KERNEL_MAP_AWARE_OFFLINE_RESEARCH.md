# P13 — Kernel map-aware, non-executable Decision research

## Boundary and purpose

P13 extends the P12 read-only Decision System. The goal is to exercise full
static game rules (not guessed Manhattan distance): candidate spell cells are
passed to `GameKernel.spell_decisions.evaluate_cast_cell`; reachable cells and
shortest paths are passed to `GameKernel.fight_queries`. The kernel alone owns
the game rules. There is no executable plan and no input driver.

## New files

- `src/anka_contracts/map_research.py` — immutable request and report, with
  strict cell bounds (0–559), unique candidates, 16-candidate budget, scope
  binding and permanently false actuation flags.
- `src/anka_decision/map_research.py` — pure game-kernel-backed evaluation with
  conservative evidence gates, bounded candidate enumeration and explainable
  result stages.
- `src/anka_app/map_research_offline.py` — composition root and synthetic
  560-cell fixtures; game kernel loaded from existing historical assets.
- `tests/test_p13_map_research.py` — positive and adversarial regression cases.
- `map_demo.bat` — read-only synthetic demonstration.

## Evidence and safety invariants

1. Reject the wrong session, account generation, fight or revision using P12's
   existing scope gate before ever reading the map.
2. Reject absent/partial or duplicated 560-cell map geometry. Reject map-ID
   disagreement and mismatched turn actor, position, AP, MP, HP and cooldowns
   between the synthetic Live State and caller-owned kernel FightContext.
3. Reject unresolved current-fight walkability overrides. R5.195 demonstrated
   that older static walkability may contradict placement-time evidence;
   blindly ignoring overrides can produce false impossibility claims.
4. Reject movement from an actor cell that is statically non-walkable. Refuse
   occupancy when any living actor's position is unknown.
5. A missing current-turn cast count is **UNKNOWN**, never an implicit zero.
   An invalid candidate is **ILLEGAL**, rather than scored as a weak action.
6. A reachable movement destination must also have a kernel shortest path with
   matching MP cost. Tackle, collision, projection and changing live state are
   not validated; even a static yes cannot be executed.
7. All map and actor values are synthetic fixtures. A deterministic static
   cast is labeled `LEGAL_STATIC_ONLY`, not approved for gameplay.
8. Unknown packet evidence, exact client build, action permissions, character
   class, equipment slot mapping and physical input remain unverified.

## Example

Run `map_demo.bat` on Windows after `setup.bat`, or:

```sh
PYTHONPATH=src python -m anka_app.cli map-demo
```

The synthetic actor is at cell 215 with 11 AP/5 MP; a synthetic enemy occupies
229. The historical Flèche Glacée grade 3 query for cell 229 is statically
legal. Target 220 lacks range or required occupancy; movement from 215 to 201
is statically reachable in one step. Output is `RESEARCH_ONLY`, with zero
physical input and no authoritative gameplay assertions.

## Negative regression matrix

- Historical kernel rejects missing/invalid spell definitions, insufficient AP,
  illegal range and blocked static LoS.
- Full map completeness, duplicate/missing cells, wrong map/turn/actor scope,
  stale revisions and inconsistent AP/position/cooldown evidence are rejected.
- Live geometry overrides and non-walkable starting cells are rejected until
  a future authoritative geometry adapter reconciles them.
- Current-turn cast history absence yields `UNKNOWN` rather than false legal.
- Occupied movement targets, impassable destinations, bounded MP routes,
  deterministic path tie-breaking and snapshot immutability are exercised.
- CLI synthetic demo exits successfully; normal live start stays blocked.

## Not verified

Current Dofus protocol, real map geometry, LoS/cell data from this client,
current equipped spell bar, current actor class, move tackle/dodge, Windows
physical input, CRA/ENU fight results, and release acceptance in a live client.

This milestone verifies offline architecture and kernel integration only.
