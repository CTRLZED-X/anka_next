# anka_workflow — definitive M10 foundation

Workflow is the single owner of mission/run phase, route progression, encounter bounds, run budgets, recovery and stop policy. It consumes typed contracts/ports only; it does not import Decision, Execution or Coordination implementations.

`MissionWorkflow` uses semantic progress tokens and logical monotonic watchdog budgets. Heartbeats and unsettled action polling do not reset progress. Recovery is bounded. Fight end is not victory: an independently typed fight outcome is required before counters change, and each fight epoch is counted at most once.

`compiler.py` compiles the strict operator mission configuration against provenance-bound internal route assets. `integration.py` demonstrates ports-only Decision/Coordination/Execution composition; it does not own input and Q6 uses only a zero-input executor.

The older `mission_research.py` remains a P17 synthetic regression fixture.
