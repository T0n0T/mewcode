import asyncio

import pytest

from mewcode.agent.collector import CollectedResponse, RawToolCall
from mewcode.agent.events import (
    ConfirmationRequested,
    ConfirmationResolved,
    ProgressChanged,
    RunStarted,
    RunStopped,
    TextDeltaEvent,
    ToolFinished,
    ToolStarted,
    UsageReported,
)
from mewcode.agent.run import AgentRun
from mewcode.agent.scheduler import (
    ScheduledToolCall,
    ToolBatch,
    ToolScheduleOutcome,
)
from mewcode.agent.types import AgentRequest, RunMode, RunPhase, StopReason
from mewcode.errors import ProviderError
from mewcode.messages import AssistantMessage, ToolResultsMessage, UserMessage
from mewcode.providers.base import TokenUsage
from mewcode.tools.base import (
    ConfirmationPreview,
    ToolCall,
    ToolExecutionPolicy,
    ToolErrorInfo,
    ToolFeedback,
    ToolResult,
)


class BlockingCollector:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def collect(
        self,
        history,
        tools,
        *,
        run_id,
        iteration,
        instructions,
        cancellation,
        on_text,
        on_stream_started,
    ):
        await on_stream_started()
        await on_text("partial")
        self.started.set()
        await cancellation.wait_cancelled()
        cancellation.raise_if_cancelled()


class UnusedScheduler:
    async def execute(self, *args, **kwargs):
        raise AssertionError("scheduler must not run in the lifecycle slice")


class IdleCollector:
    async def collect(self, *args, **kwargs):
        await asyncio.Event().wait()


class WaitingCollector:
    def __init__(self) -> None:
        self.entered = asyncio.Event()

    async def collect(self, *args, **kwargs):
        self.entered.set()
        await asyncio.Event().wait()


class CompletingCollector:
    def __init__(self, response: CollectedResponse) -> None:
        self.response = response
        self.calls = 0

    async def collect(self, *args, on_text, on_stream_started, **kwargs):
        self.calls += 1
        await on_stream_started()
        await on_text(self.response.text)
        return self.response


class ScriptedCollector:
    def __init__(self, responses) -> None:
        self.responses = iter(responses)
        self.histories = []

    async def collect(
        self,
        history,
        tools,
        *,
        on_text,
        on_stream_started,
        **kwargs,
    ):
        self.histories.append(tuple(history))
        response = next(self.responses)
        await on_stream_started()
        if isinstance(response, BaseException):
            raise response
        if response.text:
            await on_text(response.text)
        return response


class ScriptedScheduler:
    def __init__(self) -> None:
        self.executed = []

    async def execute(self, calls, *, iteration, cancellation, events):
        self.executed.append((iteration, tuple(calls)))
        feedback = []
        for position, raw_call in enumerate(calls):
            call = ScheduledToolCall(
                position,
                raw_call.call_id,
                raw_call.name,
                {},
                None,
                ToolExecutionPolicy.PARALLEL_SAFE,
            )
            batch = ToolBatch(
                f"batch-{iteration}-{position}",
                ToolExecutionPolicy.PARALLEL_SAFE,
                (call,),
            )
            result = ToolResult(
                status="success",
                data={"round": iteration},
                duration_ms=iteration,
            )
            await events.started(batch, call)
            await events.finished(batch, call, result)
            feedback.append(ToolFeedback(call.call_id, call.name, result))
        return ToolScheduleOutcome(tuple(feedback), all_unknown=False)


class ConfirmingScheduler:
    async def execute(self, calls, *, iteration, cancellation, events):
        raw_call = calls[0]
        call = ScheduledToolCall(
            0,
            raw_call.call_id,
            raw_call.name,
            {},
            None,
            ToolExecutionPolicy.SERIAL,
        )
        batch = ToolBatch("batch-1", ToolExecutionPolicy.SERIAL, (call,))
        await events.started(batch, call)
        approved = await events.confirm(
            ToolCall(call.call_id, call.name, {}),
            ConfirmationPreview("write", "safe write", "safe details"),
        )
        result = ToolResult(status="success" if approved else "rejected")
        await events.finished(batch, call, result)
        return ToolScheduleOutcome(
            (ToolFeedback(call.call_id, call.name, result),),
            all_unknown=False,
        )


class FlaggedScheduler(ScriptedScheduler):
    def __init__(self, all_unknown) -> None:
        super().__init__()
        self._all_unknown = iter(all_unknown)

    async def execute(self, *args, **kwargs):
        outcome = await super().execute(*args, **kwargs)
        return ToolScheduleOutcome(outcome.feedback, next(self._all_unknown))


class FailingScheduler:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("internal sk-test-secret must stay hidden")


class ToolFailureScheduler:
    async def execute(self, calls, *, iteration, cancellation, events):
        call = calls[0]
        result = ToolResult(
            status="error",
            error=ToolErrorInfo(
                "read_failed",
                "file was not found",
                retryable=True,
            ),
        )
        return ToolScheduleOutcome(
            (ToolFeedback(call.call_id, call.name, result),),
            all_unknown=False,
        )


class BlockingToolScheduler:
    def __init__(self) -> None:
        self.cancelled = False

    async def execute(self, calls, *, iteration, cancellation, events):
        raw_call = calls[0]
        call = ScheduledToolCall(
            0,
            raw_call.call_id,
            raw_call.name,
            {},
            None,
            ToolExecutionPolicy.PARALLEL_SAFE,
        )
        batch = ToolBatch("batch-1", ToolExecutionPolicy.PARALLEL_SAFE, (call,))
        await events.started(batch, call)
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


@pytest.mark.asyncio
async def test_lifecycle_cancel_partial_text_reports_stable_identity():
    collector = BlockingCollector()
    committed = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        collector,
        UnusedScheduler(),
        committed.extend,
        id_factory=lambda: "run-1",
    )
    events = aiter(run)

    observed = [await anext(events) for _ in range(4)]
    await collector.started.wait()
    await run.cancel()
    observed.extend([await anext(events) for _ in range(2)])

    assert run.run_id == "run-1"
    assert run.mode is RunMode.EXECUTE
    assert [type(event) for event in observed] == [
        RunStarted,
        ProgressChanged,
        ProgressChanged,
        TextDeltaEvent,
        ProgressChanged,
        RunStopped,
    ]
    assert [
        event.phase for event in observed if isinstance(event, ProgressChanged)
    ] == [
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.STOPPING,
    ]
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED
    assert [event.context.sequence for event in observed] == [1, 2, 3, 4, 5, 6]
    assert {event.context.run_id for event in observed} == {"run-1"}
    assert committed == []


@pytest.mark.asyncio
async def test_cancel_model_before_first_fragment_stops_without_history_commit():
    collector = WaitingCollector()
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        collector,
        UnusedScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )
    events = aiter(run)

    first = await anext(events)
    waiting = await anext(events)
    await collector.entered.wait()
    await run.cancel()
    remaining = [event async for event in events]

    assert isinstance(first, RunStarted)
    assert isinstance(waiting, ProgressChanged)
    assert waiting.phase is RunPhase.WAITING_MODEL
    assert isinstance(remaining[-1], RunStopped)
    assert remaining[-1].reason is StopReason.CANCELLED
    assert commits == []


@pytest.mark.asyncio
async def test_public_control_immediate_cancel_is_idempotent_and_closes_run():
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        IdleCollector(),
        UnusedScheduler(),
        lambda _messages: None,
        id_factory=lambda: "run-1",
    )
    events = aiter(run)

    await asyncio.gather(run.cancel(), run.cancel())
    await run.wait_closed()
    async with asyncio.timeout(0.1):
        observed = [event async for event in events]

    assert isinstance(observed[0], RunStarted)
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED
    assert run.resolve_confirmation("missing", True) is False


@pytest.mark.asyncio
async def test_natural_completion_commits_complete_assistant_once():
    provider_state = {"response_id": "response-1"}
    collector = CompletingCollector(CollectedResponse("complete", provider_state))
    commit_calls = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        collector,
        UnusedScheduler(),
        lambda messages: commit_calls.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]
    await run.wait_closed()

    assert commit_calls == [
        (AssistantMessage("complete", provider_state),),
    ]
    assert collector.calls == 1
    assert isinstance(observed[-2], ProgressChanged)
    assert observed[-2].phase is RunPhase.STOPPING
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_react_loop_commits_each_tool_feedback_as_an_iteration_transaction():
    first_call = RawToolCall(0, "call-1", "read_file", "{}")
    second_call = RawToolCall(0, "call-2", "search_code", "{}")
    responses = [
        CollectedResponse("reading", {"round": 1}, calls=(first_call,)),
        CollectedResponse("searching", {"round": 2}, calls=(second_call,)),
        CollectedResponse("final", {"round": 3}),
    ]
    collector = ScriptedCollector(responses)
    scheduler = ScriptedScheduler()
    commits = []
    initial_history = (UserMessage("task"),)
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        initial_history,
        (),
        collector,
        scheduler,
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]

    first_feedback = ToolFeedback(
        "call-1",
        "read_file",
        ToolResult(status="success", data={"round": 1}, duration_ms=1),
    )
    second_feedback = ToolFeedback(
        "call-2",
        "search_code",
        ToolResult(status="success", data={"round": 2}, duration_ms=2),
    )
    assert commits == [
        (
            AssistantMessage("reading", {"round": 1}),
            ToolResultsMessage((first_feedback,)),
        ),
        (
            AssistantMessage("searching", {"round": 2}),
            ToolResultsMessage((second_feedback,)),
        ),
        (AssistantMessage("final", {"round": 3}),),
    ]
    assert collector.histories == [
        initial_history,
        initial_history + commits[0],
        initial_history + commits[0] + commits[1],
    ]
    assert [iteration for iteration, _calls in scheduler.executed] == [1, 2]
    assert [
        event.phase for event in observed if isinstance(event, ProgressChanged)
    ] == [
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.EXECUTING_TOOLS,
        RunPhase.FEEDING_BACK,
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.EXECUTING_TOOLS,
        RunPhase.FEEDING_BACK,
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.STOPPING,
    ]
    assert [type(event) for event in observed if isinstance(event, (ToolStarted, ToolFinished))] == [
        ToolStarted,
        ToolFinished,
        ToolStarted,
        ToolFinished,
    ]
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_tool_feedback_confirmation_is_resolved_through_run_control():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "write",
                {"round": 1},
                calls=(RawToolCall(0, "call-1", "write_file", "{}"),),
            ),
            CollectedResponse("done", {"round": 2}),
        ]
    )
    ids = iter(["run-1", "confirm-1"])
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ConfirmingScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: next(ids),
    )

    observed = []
    async for event in run:
        observed.append(event)
        if isinstance(event, ConfirmationRequested):
            assert event.request_id == "confirm-1"
            assert run.resolve_confirmation(event.request_id, True) is True
            assert run.resolve_confirmation(event.request_id, False) is False

    assert any(isinstance(event, ConfirmationResolved) for event in observed)
    assert [
        event.phase for event in observed if isinstance(event, ProgressChanged)
    ] == [
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.EXECUTING_TOOLS,
        RunPhase.WAITING_CONFIRMATION,
        RunPhase.EXECUTING_TOOLS,
        RunPhase.FEEDING_BACK,
        RunPhase.WAITING_MODEL,
        RunPhase.STREAMING_MODEL,
        RunPhase.STOPPING,
    ]
    assert commits[-1] == (AssistantMessage("done", {"round": 2}),)


@pytest.mark.asyncio
async def test_cancel_confirmation_cleans_request_and_discards_transaction():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "write",
                {},
                calls=(RawToolCall(0, "call-1", "write_file", "{}"),),
            )
        ]
    )
    ids = iter(["run-1", "confirm-1"])
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ConfirmingScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: next(ids),
    )

    observed = []
    async for event in run:
        observed.append(event)
        if isinstance(event, ConfirmationRequested):
            await run.cancel()

    assert commits == []
    assert not any(isinstance(event, ConfirmationResolved) for event in observed)
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED
    assert run.resolve_confirmation("confirm-1", True) is False


@pytest.mark.asyncio
async def test_cancel_tool_discards_current_iteration_transaction():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "working",
                {},
                calls=(RawToolCall(0, "call-1", "read_file", "{}"),),
            )
        ]
    )
    scheduler = BlockingToolScheduler()
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        scheduler,
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    observed = []
    async for event in run:
        observed.append(event)
        if isinstance(event, ToolStarted):
            await run.cancel()

    assert scheduler.cancelled is True
    assert commits == []
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED


@pytest.mark.asyncio
async def test_usage_reports_each_round_and_preserves_unknown_cumulative_dimensions():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "one",
                {},
                TokenUsage(1, 2, 3),
                (RawToolCall(0, "call-1", "read_file", "{}"),),
            ),
            CollectedResponse(
                "two",
                {},
                TokenUsage(4, None, 5),
                (RawToolCall(0, "call-2", "read_file", "{}"),),
            ),
            CollectedResponse("done", {}, TokenUsage(6, 7, None)),
        ]
    )
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ScriptedScheduler(),
        lambda _messages: None,
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]
    usage = [event for event in observed if isinstance(event, UsageReported)]

    assert [event.current for event in usage] == [
        TokenUsage(1, 2, 3),
        TokenUsage(4, None, 5),
        TokenUsage(6, 7, None),
    ]
    assert [event.cumulative for event in usage] == [
        TokenUsage(1, 2, 3),
        TokenUsage(5, None, 8),
        TokenUsage(11, None, None),
    ]


@pytest.mark.asyncio
async def test_iteration_limit_commits_last_complete_batch_without_extra_request():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                f"round-{index}",
                {"round": index},
                calls=(RawToolCall(0, f"call-{index}", "read_file", "{}"),),
            )
            for index in range(1, 12)
        ]
    )
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ScriptedScheduler(),
        lambda messages: commits.append(tuple(messages)),
        max_iterations=10,
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]

    assert len(collector.histories) == 10
    assert len(commits) == 10
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.ITERATION_LIMIT


@pytest.mark.asyncio
async def test_unknown_tool_limit_counts_rounds_resets_and_beats_iteration_limit():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                f"round-{index}",
                {"round": index},
                calls=(RawToolCall(0, f"call-{index}", "missing", "{}"),),
            )
            for index in range(1, 7)
        ]
    )
    scheduler = FlaggedScheduler([True, False, True, True, True, True])
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        scheduler,
        lambda _messages: None,
        max_iterations=5,
        unknown_tool_limit=3,
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]

    assert len(collector.histories) == 5
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.UNKNOWN_TOOL_LIMIT


@pytest.mark.asyncio
async def test_provider_error_discards_current_iteration_and_keeps_prior_commit():
    first_call = RawToolCall(0, "call-1", "read_file", "{}")
    collector = ScriptedCollector(
        [
            CollectedResponse("reading", {"round": 1}, calls=(first_call,)),
            ProviderError("provider stream failed with sk-test-secret"),
        ]
    )
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ScriptedScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    await run.wait_closed()
    observed = [event async for event in run]

    assert len(commits) == 1
    assert len(commits[0]) == 2
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.PROVIDER_ERROR
    assert observed[-1].message == (
        "The model provider stopped because of an error."
    )
    assert "sk-test-secret" not in repr(observed)


@pytest.mark.asyncio
async def test_internal_error_is_safely_converted_without_partial_commit():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "working",
                {},
                calls=(RawToolCall(0, "call-1", "read_file", "{}"),),
            )
        ]
    )
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        FailingScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    await run.wait_closed()
    observed = [event async for event in run]

    assert commits == []
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.INTERNAL_ERROR
    assert "sk-test-secret" not in observed[-1].message


@pytest.mark.asyncio
async def test_tool_failure_feedback_allows_model_recovery():
    collector = ScriptedCollector(
        [
            CollectedResponse(
                "trying a read",
                {},
                calls=(RawToolCall(0, "call-1", "read_file", "{}"),),
            ),
            CollectedResponse("recovered answer", {}),
        ]
    )
    commits = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (UserMessage("task"),),
        (),
        collector,
        ToolFailureScheduler(),
        lambda messages: commits.append(tuple(messages)),
        id_factory=lambda: "run-1",
    )

    observed = [event async for event in run]

    feedback = commits[0][1]
    assert isinstance(feedback, ToolResultsMessage)
    assert feedback.results[0].result.error is not None
    assert feedback.results[0].result.error.code == "read_failed"
    assert collector.histories[1][-1] == feedback
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.COMPLETED
