# anka_coordination — definitive M9 foundation

Coordination is the sole multi-account coherence authority. It consumes immutable per-account observations and proves same-fight identity, join/placement/Ready barriers, coherent turn ownership, freshness vectors and generation-bound `TurnPermit`s.

It never imports Workflow, Decision, Execution, Client, Protocol or Capture implementations and never sends physical input. Cursor-only heartbeats do not advance the semantic progress token or permit generation. Conflicts/gaps/missing evidence fail closed; a UI Ready click alone never satisfies the Ready barrier.

The older `party_lifecycle.py` remains an immutable synthetic regression fixture from P17, not the definitive authority.
