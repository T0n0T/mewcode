from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import suppress
from uuid import uuid4

from mewcode.agent.collector import ResponseCollector
from mewcode.agent.control import ConfirmationBroker, EventChannel, _EventStream
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
from mewcode.agent.scheduler import (
    ScheduledToolCall,
    ToolBatch,
    ToolScheduler,
)
from mewcode.agent.types import AgentRequest, RunMode, RunPhase, StopReason
from mewcode.cancellation import CancellationToken
from mewcode.errors import ProviderError
from mewcode.messages import (
    AssistantMessage,
    ConversationMessage,
    ToolResultsMessage,
)
from mewcode.providers.base import TokenUsage
from mewcode.tools.base import (
    ConfirmationPreview,
    JSONValue,
    ToolCall,
    ToolDefinition,
    ToolPresentation,
    ToolResult,
)

HistoryCommit = Callable[[Sequence[ConversationMessage]], None]
ToolPresenter = Callable[[str, Mapping[str, JSONValue]], ToolPresentation]
RunClosedCallback = Callable[[str, RunMode, StopReason, str | None], None]


def _new_id() -> str:
    return str(uuid4())


def _hidden_presentation(
    name: str, _arguments: Mapping[str, JSONValue]
) -> ToolPresentation:
    return ToolPresentation(name[:80], "<arguments hidden>")


async def _iterate_events(stream: _EventStream):
    try:
        async for event in stream:
            yield event
    finally:
        await stream.aclose()


class _RunEventIterator(AsyncIterator[AgentEvent]):
    def __init__(self, stream: _EventStream) -> None:
        self._stream = stream
        self._iterator = _iterate_events(stream)

    def __aiter__(self) -> _RunEventIterator:
        return self

    async def __anext__(self) -> AgentEvent:
        return await anext(self._iterator)

    async def aclose(self) -> None:
        await self._stream.aclose()
        await self._iterator.aclose()


class AgentRun:
    def __init__(
        self,
        request: AgentRequest,
        history: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        collector: ResponseCollector,
        scheduler: ToolScheduler,
        commit: HistoryCommit,
        *,
        max_iterations: int = 10,
        unknown_tool_limit: int = 3,
        id_factory: Callable[[], str] | None = None,
        tool_presenter: ToolPresenter | None = None,
        event_capacity: int = 64,
        invalid: tuple[str, str] | None = None,
        on_closed: RunClosedCallback | None = None,
    ) -> None:
        self._request = request
        self._history = list(history)
        self._tools = tuple(tools)
        self._collector = collector
        self._scheduler = scheduler
        self._commit = commit
        self._max_iterations = max_iterations
        self._unknown_tool_limit = unknown_tool_limit
        self._id_factory = id_factory or _new_id
        self._tool_presenter = tool_presenter or _hidden_presentation
        self._invalid = invalid
        self._on_closed = on_closed
        self._run_id = self._id_factory()
        self._current_iteration = 0
        self._cumulative_usage = TokenUsage(0, 0, 0)
        self._unknown_tool_streak = 0
        self._stop_reason: StopReason | None = None
        self._final_text: str | None = None
        self._cancellation = CancellationToken()
        self._confirmations = ConfirmationBroker(id_factory=self._id_factory)
        self._events = EventChannel(
            self._run_id,
            capacity=event_capacity,
            on_consumer_close=self.cancel,
        )
        self._task_started = False
        self._task = asyncio.create_task(self._run())

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def mode(self) -> RunMode:
        return self._request.mode

    def __aiter__(self):
        return _RunEventIterator(self._events.events())

    async def cancel(self) -> None:
        self._cancellation.cancel()
        self._confirmations.cancel_all()
        if not self._task.done() and self._task_started:
            self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        return self._confirmations.resolve(request_id, approved)

    async def wait_closed(self) -> None:
        with suppress(asyncio.CancelledError):
            await asyncio.shield(self._task)

    async def started(self, batch: ToolBatch, call: ScheduledToolCall) -> None:
        presentation = self._tool_presenter(call.name, call.arguments or {})
        await self._publish(
            ToolStarted(
                self._context(self._current_iteration),
                batch.batch_id,
                call.position,
                call.call_id,
                presentation.name,
                call.execution_policy,
                presentation.argument_summary,
            )
        )

    async def confirm(self, call: ToolCall, preview: ConfirmationPreview) -> bool:
        await self._progress(
            RunPhase.WAITING_CONFIRMATION, self._current_iteration
        )
        request_id, decision = self._confirmations.create()
        await self._publish(
            ConfirmationRequested(
                self._context(self._current_iteration),
                request_id,
                call.call_id,
                preview,
            )
        )
        approved = await decision
        await self._publish(
            ConfirmationResolved(
                self._context(self._current_iteration),
                request_id,
                call.call_id,
                approved,
            )
        )
        await self._progress(RunPhase.EXECUTING_TOOLS, self._current_iteration)
        return approved

    async def finished(
        self,
        batch: ToolBatch,
        call: ScheduledToolCall,
        result: ToolResult,
    ) -> None:
        presentation = self._tool_presenter(call.name, call.arguments or {})
        await self._publish(
            ToolFinished(
                self._context(self._current_iteration),
                batch.batch_id,
                call.position,
                call.call_id,
                presentation.name,
                result.status,
                result.duration_ms,
                result.error.message if result.error is not None else None,
                result.truncation,
            )
        )

    async def _run(self) -> None:
        self._task_started = True
        iteration = 1
        try:
            await self._publish(
                RunStarted(
                    self._context(None),
                    self.mode,
                    self._max_iterations,
                    self._request.source_plan_id,
                )
            )
            if self._invalid is not None:
                code, message = self._invalid
                await self._stop(
                    StopReason.INVALID_REQUEST,
                    message,
                    None,
                    code=code,
                )
                return
            if self._cancellation.is_cancelled:
                raise asyncio.CancelledError
            for iteration in range(1, self._max_iterations + 1):
                self._current_iteration = iteration
                await self._progress(RunPhase.WAITING_MODEL, iteration)
                response = await self._collector.collect(
                    self._history,
                    self._tools,
                    run_id=self._run_id,
                    iteration=iteration,
                    instructions=self._request.instructions,
                    cancellation=self._cancellation,
                    on_text=lambda text, current=iteration: self._publish(
                        TextDeltaEvent(self._context(current), text)
                    ),
                    on_stream_started=lambda current=iteration: self._progress(
                        RunPhase.STREAMING_MODEL, current
                    ),
                )
                self._cumulative_usage = _add_usage(
                    self._cumulative_usage, response.usage
                )
                await self._publish(
                    UsageReported(
                        self._context(iteration),
                        response.usage,
                        self._cumulative_usage,
                    )
                )
                assistant = AssistantMessage(response.text, response.provider_state)
                if not response.calls:
                    self._commit_messages((assistant,))
                    self._final_text = response.text
                    await self._stop(
                        StopReason.COMPLETED, "Run completed.", iteration
                    )
                    return

                await self._progress(RunPhase.EXECUTING_TOOLS, iteration)
                outcome = await self._scheduler.execute(
                    response.calls,
                    iteration=iteration,
                    cancellation=self._cancellation,
                    events=self,
                )
                self._commit_messages(
                    (assistant, ToolResultsMessage(outcome.feedback))
                )
                if outcome.all_unknown:
                    self._unknown_tool_streak += 1
                else:
                    self._unknown_tool_streak = 0
                if self._unknown_tool_streak >= self._unknown_tool_limit:
                    await self._stop(
                        StopReason.UNKNOWN_TOOL_LIMIT,
                        "Run stopped after repeated unknown tool calls.",
                        iteration,
                    )
                    return
                if iteration < self._max_iterations:
                    await self._progress(RunPhase.FEEDING_BACK, iteration)

            await self._stop(
                StopReason.ITERATION_LIMIT,
                "Run reached the iteration limit.",
                iteration,
            )
        except asyncio.CancelledError:
            self._cancellation.cancel()
            await self._stop(StopReason.CANCELLED, "Run cancelled.", iteration)
        except ProviderError:
            if self._cancellation.is_cancelled:
                await self._stop(
                    StopReason.CANCELLED, "Run cancelled.", iteration
                )
            else:
                self._cancellation.cancel()
                await self._stop(
                    StopReason.PROVIDER_ERROR,
                    "The model provider stopped because of an error.",
                    iteration,
                    code="provider_error",
                )
        except Exception:
            self._cancellation.cancel()
            await self._stop(
                StopReason.INTERNAL_ERROR,
                "The agent stopped because of an internal error.",
                iteration,
                code="internal_error",
            )
        finally:
            self._confirmations.cancel_all()
            if self._on_closed is not None and self._stop_reason is not None:
                self._on_closed(
                    self._run_id,
                    self.mode,
                    self._stop_reason,
                    self._final_text,
                )

    async def _progress(self, phase: RunPhase, iteration: int) -> bool:
        return await self._publish(
            ProgressChanged(
                self._context(iteration),
                phase,
                iteration,
                self._max_iterations,
            )
        )

    async def _publish(self, event: AgentEvent) -> bool:
        return await self._events.publish(event)

    async def _stop(
        self,
        reason: StopReason,
        message: str,
        iteration: int | None,
        *,
        code: str | None = None,
    ) -> bool:
        stopping = (
            ProgressChanged(
                self._context(iteration),
                RunPhase.STOPPING,
                iteration,
                self._max_iterations,
            )
            if iteration is not None
            else None
        )
        stopped = await self._events.stop(
            RunStopped(self._context(iteration), reason, message, code),
            before=stopping,
        )
        if stopped:
            self._stop_reason = reason
        return stopped

    def _context(self, iteration: int | None) -> EventContext:
        return EventContext(self._run_id, 0, iteration)

    def _commit_messages(self, messages: Sequence[ConversationMessage]) -> None:
        transaction = tuple(messages)
        self._commit(transaction)
        self._history.extend(transaction)


def _add_usage(cumulative: TokenUsage, current: TokenUsage) -> TokenUsage:
    def add(known: int | None, value: int | None) -> int | None:
        if known is None or value is None:
            return None
        return known + value

    return TokenUsage(
        add(cumulative.input_tokens, current.input_tokens),
        add(cumulative.output_tokens, current.output_tokens),
        add(cumulative.total_tokens, current.total_tokens),
    )
