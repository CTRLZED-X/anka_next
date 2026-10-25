"""Independent QA regression for End Turn causal ordering.

A turn-owner proof that predates physical input cannot be treated as the
post-action handoff caused by that End Turn action.
"""
from __future__ import annotations

import unittest

from anka_contracts.diagnostics import DiagnosticEvent
from anka_observability.forensics import turn_handoff_report


def event(seq:int,name:str,*,account_id:str="acct-cra",turn_epoch:int=7,
          action_id:str|None="action-agent08-handoff-order",
          attempt_id:str|None=None,physical_input_state:str|None=None,
          payload:dict|None=None)->DiagnosticEvent:
    if name.startswith("workflow."):
        owner="anka_workflow"
    elif name.startswith("execution."):
        owner="anka_execution"
    else:
        owner="anka_coordination"
    return DiagnosticEvent(
        1,f"evt-agent08-handoff-order-{seq}",name,"INFO",
        "2026-10-25T16:00:00+00:00",seq,seq,
        "inv-agent08-handoff-order","run-agent08-handoff-order",
        account_id=account_id,fight_epoch=4,turn_epoch=turn_epoch,
        action_id=action_id,attempt_id=attempt_id,owner_system=owner,
        physical_input_state=physical_input_state,payload=payload or {},
    )


class TestAgent08EndTurnHandoffOrdering(unittest.TestCase):
    def test_owner_proof_before_send_cannot_complete_handoff(self):
        rows=(
            event(1,"workflow.action_requested",payload={"kind":"END_TURN"}),
            event(2,"execution.admitted"),
            # Unrelated/newer owner truth existed before this action crossed input.
            event(3,"coordination.turn_owner_proved",account_id="acct-enu",
                  turn_epoch=8,action_id=None),
            event(4,"execution.send_started",attempt_id="attempt-agent08-handoff-order",
                  physical_input_state="SEND_STARTED"),
            event(5,"execution.input_sent",attempt_id="attempt-agent08-handoff-order",
                  physical_input_state="SENT"),
            event(6,"execution.outcome_settled",attempt_id="attempt-agent08-handoff-order",
                  physical_input_state="SENT"),
        )
        report=turn_handoff_report(rows)
        self.assertNotEqual(report["status"],"COMPLETE")
        self.assertIsNone(
            report["next_owner_event_id"],
            "A next-owner proof older than execution.input_sent was borrowed as "
            "the result of this End Turn action.",
        )


if __name__=="__main__":
    unittest.main()
