from dataclasses import FrozenInstanceError, fields
from typing import get_args

import pytest

from mewcode.agent.events import (
    AgentEvent,
    ConfirmationRequested,
    ConfirmationResolved,
    EventContext,
    ProgressChanged,
    RunStarted,
    RunStopped,
    TextDeltaEvent,
    ToolFinished,
    ToolStarted,
    UsageReported,
)
from mewcode.agent.types import RunMode, RunPhase, StopReason
from mewcode.providers.base import TokenUsage
from mewcode.tools.base import (
    ConfirmationPreview,
    ToolExecutionPolicy,
    TruncationInfo,
)


def test_agent_events_are_frozen_and_cover_the_public_contract():
    context = EventContext("run-1", 1, 2)
    started = RunStarted(context, RunMode.EXECUTE, 10, None)
    progress = ProgressChanged(context, RunPhase.WAITING_MODEL, 2, 10)
    text = TextDeltaEvent(context, "hello")
    tool_started = ToolStarted(
        context,
        "batch-1",
        3,
        "call-1",
        "read_file",
        ToolExecutionPolicy.PARALLEL_SAFE,
        "path=README.md",
    )
    confirmation = ConfirmationRequested(
        context,
        "confirm-1",
        "call-1",
        ConfirmationPreview("write", "Write file", "safe diff"),
    )
    resolved = ConfirmationResolved(context, "confirm-1", "call-1", True)
    finished = ToolFinished(
        context,
        "batch-1",
        3,
        "call-1",
        "read_file",
        "success",
        4,
        None,
        TruncationInfo("characters", 20, 10, "narrow"),
    )
    usage = UsageReported(
        context,
        TokenUsage(1, 2, 3, 0, 4),
        TokenUsage(4, 5, 9, 7, None),
    )
    stopped = RunStopped(context, StopReason.COMPLETED, "Completed", "done")

    assert set(get_args(AgentEvent)) == {
        RunStarted,
        ProgressChanged,
        TextDeltaEvent,
        ToolStarted,
        ConfirmationRequested,
        ConfirmationResolved,
        ToolFinished,
        UsageReported,
        RunStopped,
    }
    assert started.max_iterations == 10
    assert progress.current_iteration == 2
    assert text.text == "hello"
    assert confirmation.preview.details == "safe diff"
    assert resolved.approved is True
    assert usage.cumulative.total_tokens == 9
    assert usage.current.cache_read_input_tokens == 0
    assert usage.current.cache_write_input_tokens == 4
    assert usage.cumulative.cache_read_input_tokens == 7
    assert usage.cumulative.cache_write_input_tokens is None
    assert stopped.code == "done"
    with pytest.raises(FrozenInstanceError):
        context.sequence = 2


def test_tool_events_have_stable_identity_and_no_complete_result_field():
    context = EventContext("run-1", 7, 2)
    started = ToolStarted(
        context,
        "batch-1",
        3,
        "call-1",
        "read_file",
        ToolExecutionPolicy.PARALLEL_SAFE,
        "path=README.md",
    )
    finished = ToolFinished(
        context,
        "batch-1",
        3,
        "call-1",
        "read_file",
        "success",
        1,
        None,
        None,
    )

    assert (started.context.run_id, started.context.iteration) == ("run-1", 2)
    assert (started.batch_id, started.position, started.call_id) == (
        finished.batch_id,
        finished.position,
        finished.call_id,
    )
    assert "result" not in {field.name for field in fields(ToolFinished)}
    assert "data" not in {field.name for field in fields(ToolFinished)}
