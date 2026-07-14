from dataclasses import FrozenInstanceError

import pytest

from mewcode.agent.types import (
    AgentRequest,
    PlanStatus,
    RunMode,
    RunPhase,
    StopReason,
    StoredPlan,
)


def test_agent_types_have_stable_values():
    assert [mode.value for mode in RunMode] == ["execute", "plan", "do"]
    assert [phase.value for phase in RunPhase] == [
        "waiting_model",
        "streaming_model",
        "executing_tools",
        "waiting_confirmation",
        "feeding_back",
        "stopping",
    ]
    assert [reason.value for reason in StopReason] == [
        "completed",
        "iteration_limit",
        "cancelled",
        "unknown_tool_limit",
        "provider_error",
        "invalid_request",
        "internal_error",
    ]
    assert [status.value for status in PlanStatus] == ["ready", "completed"]


def test_agent_request_distinguishes_all_modes_and_is_frozen():
    execute = AgentRequest(RunMode.EXECUTE, "task", "execute", "all")
    plan = AgentRequest(RunMode.PLAN, "task", "plan", "read_only")
    do = AgentRequest(RunMode.DO, "saved plan", "do", "all", "plan-1")

    assert (execute.mode, execute.tool_scope) == (RunMode.EXECUTE, "all")
    assert (plan.mode, plan.tool_scope) == (RunMode.PLAN, "read_only")
    assert (do.mode, do.source_plan_id) == (RunMode.DO, "plan-1")
    with pytest.raises(FrozenInstanceError):
        execute.user_content = "changed"


def test_stored_plan_is_an_immutable_snapshot():
    stored = StoredPlan("plan-1", "run-1", "Inspect then edit", PlanStatus.READY)

    assert stored.status is PlanStatus.READY
    with pytest.raises(FrozenInstanceError):
        stored.content = "changed"
