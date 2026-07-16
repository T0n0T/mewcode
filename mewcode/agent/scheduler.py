from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from mewcode.agent.collector import RawToolCall
from mewcode.cancellation import CancellationToken
from mewcode.tools.base import (
    ConfirmationPreview,
    JSONValue,
    ToolCall,
    ToolErrorInfo,
    ToolExecutionPolicy,
    ToolFeedback,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry


@dataclass(frozen=True)
class ScheduledToolCall:
    position: int
    call_id: str
    name: str
    arguments: dict[str, JSONValue] | None
    preflight_error: ToolResult | None
    execution_policy: ToolExecutionPolicy


@dataclass(frozen=True)
class ToolBatch:
    batch_id: str
    execution_policy: ToolExecutionPolicy
    calls: tuple[ScheduledToolCall, ...]


@dataclass(frozen=True)
class ToolScheduleOutcome:
    feedback: tuple[ToolFeedback, ...]
    all_unknown: bool


class ToolRunEvents(Protocol):
    async def started(self, batch: ToolBatch, call: ScheduledToolCall) -> None: ...
    async def confirm(self, call: ToolCall, preview: ConfirmationPreview) -> bool: ...
    async def finished(
        self, batch: ToolBatch, call: ScheduledToolCall, result: ToolResult
    ) -> None: ...


class ToolScheduler:
    def __init__(
        self,
        registry: ToolRegistry,
        executor: ToolExecutor,
        *,
        id_factory: Callable[[], str] | None = None,
        allowed_tool_names: Collection[str] | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self._id_factory = id_factory or _new_id
        self._allowed_tool_names = (
            None
            if allowed_tool_names is None
            else frozenset(allowed_tool_names)
        )

    def parse_calls(
        self, calls: Sequence[RawToolCall]
    ) -> tuple[ScheduledToolCall, ...]:
        parsed: list[ScheduledToolCall] = []
        for position, call in enumerate(calls):
            arguments: dict[str, JSONValue] | None = None
            error: ToolResult | None = None
            try:
                value = json.loads(call.arguments_text)
                if not isinstance(value, dict):
                    raise ValueError("arguments must be a JSON object")
                arguments = value
            except (json.JSONDecodeError, ValueError) as exc:
                error = _error("invalid_arguments", f"Invalid tool arguments: {exc}")
            allowed = (
                self._allowed_tool_names is None
                or call.name in self._allowed_tool_names
            )
            descriptor = self._registry.descriptor(call.name) if allowed else None
            if not allowed:
                arguments = None
                error = _error(
                    "unknown_tool",
                    f"Unknown tool '{call.name}'.",
                )
            policy = (
                descriptor.execution_policy
                if descriptor is not None
                else ToolExecutionPolicy.SERIAL
            )
            parsed.append(
                ScheduledToolCall(
                    position,
                    call.call_id,
                    call.name,
                    arguments,
                    error,
                    policy,
                )
            )
        return tuple(parsed)

    def build_batches(
        self, calls: Sequence[ScheduledToolCall]
    ) -> tuple[ToolBatch, ...]:
        batches: list[ToolBatch] = []
        parallel: list[ScheduledToolCall] = []

        def flush_parallel() -> None:
            if parallel:
                batches.append(
                    ToolBatch(
                        self._id_factory(),
                        ToolExecutionPolicy.PARALLEL_SAFE,
                        tuple(parallel),
                    )
                )
                parallel.clear()

        for call in calls:
            if call.execution_policy is ToolExecutionPolicy.PARALLEL_SAFE:
                parallel.append(call)
            else:
                flush_parallel()
                batches.append(
                    ToolBatch(
                        self._id_factory(),
                        ToolExecutionPolicy.SERIAL,
                        (call,),
                    )
                )
        flush_parallel()
        return tuple(batches)

    async def execute(
        self,
        calls: Sequence[RawToolCall],
        *,
        iteration: int,
        cancellation: CancellationToken,
        events: ToolRunEvents,
    ) -> ToolScheduleOutcome:
        scheduled = self.parse_calls(calls)
        results: dict[int, ToolFeedback] = {}
        for batch in self.build_batches(scheduled):
            cancellation.raise_if_cancelled()
            for call in batch.calls:
                await events.started(batch, call)
            if batch.execution_policy is ToolExecutionPolicy.PARALLEL_SAFE:
                async with asyncio.TaskGroup() as group:
                    for call in batch.calls:
                        group.create_task(
                            self._execute_call(
                                batch, call, cancellation, events, results
                            )
                        )
            else:
                await self._execute_call(
                    batch, batch.calls[0], cancellation, events, results
                )
        feedback = tuple(results[position] for position in sorted(results))
        all_unknown = bool(feedback) and all(
            item.result.error is not None and item.result.error.code == "unknown_tool"
            for item in feedback
        )
        return ToolScheduleOutcome(feedback, all_unknown)

    async def _execute_call(
        self,
        batch: ToolBatch,
        call: ScheduledToolCall,
        cancellation: CancellationToken,
        events: ToolRunEvents,
        results: dict[int, ToolFeedback],
    ) -> None:
        cancellation.raise_if_cancelled()
        if call.preflight_error is not None:
            result = call.preflight_error
        else:
            assert call.arguments is not None
            result = await self._executor.execute(
                ToolCall(call.call_id, call.name, call.arguments),
                cancellation=cancellation,
                confirm=events.confirm,
            )
        results[call.position] = ToolFeedback(call.call_id, call.name, result)
        await events.finished(batch, call, result)


def _error(code: str, message: str) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolErrorInfo(code, message, True),
    )


def _new_id() -> str:
    return str(uuid4())
