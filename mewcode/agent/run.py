from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from contextlib import suppress
from uuid import uuid4

from mewcode.agent.collector import ResponseCollector
from mewcode.agent.control import ConfirmationBroker, EventChannel
from mewcode.agent.events import (
    AgentEvent,
    EventContext,
    ProgressChanged,
    RunStarted,
    RunStopped,
    TextDeltaEvent,
)
from mewcode.agent.scheduler import ToolScheduler
from mewcode.agent.types import AgentRequest, RunMode, RunPhase, StopReason
from mewcode.cancellation import CancellationToken
from mewcode.messages import ConversationMessage
from mewcode.tools.base import ToolDefinition

HistoryCommit = Callable[[Sequence[ConversationMessage]], None]


def _new_id() -> str:
    return str(uuid4())


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
        event_capacity: int = 64,
    ) -> None:
        self._request = request
        self._history = tuple(history)
        self._tools = tuple(tools)
        self._collector = collector
        self._scheduler = scheduler
        self._commit = commit
        self._max_iterations = max_iterations
        self._unknown_tool_limit = unknown_tool_limit
        self._id_factory = id_factory or _new_id
        self._run_id = self._id_factory()
        self._cancellation = CancellationToken()
        self._confirmations = ConfirmationBroker(id_factory=self._id_factory)
        self._events = EventChannel(
            self._run_id,
            capacity=event_capacity,
            on_consumer_close=self.cancel,
        )
        self._task = asyncio.create_task(self._run())

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def mode(self) -> RunMode:
        return self._request.mode

    def __aiter__(self):
        return self._events.events()

    async def cancel(self) -> None:
        self._cancellation.cancel()
        self._confirmations.cancel_all()
        if not self._task.done():
            self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task

    def resolve_confirmation(self, request_id: str, approved: bool) -> bool:
        return self._confirmations.resolve(request_id, approved)

    async def wait_closed(self) -> None:
        with suppress(asyncio.CancelledError):
            await asyncio.shield(self._task)

    async def _run(self) -> None:
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
            await self._progress(RunPhase.WAITING_MODEL, iteration)
            await self._collector.collect(
                self._history,
                self._tools,
                run_id=self._run_id,
                iteration=iteration,
                instructions=self._request.instructions,
                cancellation=self._cancellation,
                on_text=lambda text: self._publish(
                    TextDeltaEvent(self._context(iteration), text)
                ),
                on_stream_started=lambda: self._progress(
                    RunPhase.STREAMING_MODEL, iteration
                ),
            )
            await self._stop(StopReason.COMPLETED, "Run completed.", iteration)
        except asyncio.CancelledError:
            self._cancellation.cancel()
            await self._stop(StopReason.CANCELLED, "Run cancelled.", iteration)
        finally:
            self._confirmations.cancel_all()

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
        return await self._events.stop(
            RunStopped(self._context(iteration), reason, message, code)
        )

    def _context(self, iteration: int | None) -> EventContext:
        return EventContext(self._run_id, 0, iteration)
