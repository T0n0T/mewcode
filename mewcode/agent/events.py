from __future__ import annotations

from dataclasses import dataclass

from mewcode.agent.types import RunMode, RunPhase, StopReason
from mewcode.providers.base import TokenUsage
from mewcode.tools.base import (
    ConfirmationPreview,
    ToolExecutionPolicy,
    ToolStatus,
    TruncationInfo,
)


@dataclass(frozen=True)
class EventContext:
    run_id: str
    sequence: int
    iteration: int | None


@dataclass(frozen=True)
class RunStarted:
    context: EventContext
    mode: RunMode
    max_iterations: int
    source_plan_id: str | None


@dataclass(frozen=True)
class ProgressChanged:
    context: EventContext
    phase: RunPhase
    current_iteration: int
    max_iterations: int


@dataclass(frozen=True)
class TextDeltaEvent:
    context: EventContext
    text: str


@dataclass(frozen=True)
class ToolStarted:
    context: EventContext
    batch_id: str
    position: int
    call_id: str
    name: str
    execution_policy: ToolExecutionPolicy
    argument_summary: str


@dataclass(frozen=True)
class ConfirmationRequested:
    context: EventContext
    request_id: str
    call_id: str
    preview: ConfirmationPreview


@dataclass(frozen=True)
class ConfirmationResolved:
    context: EventContext
    request_id: str
    call_id: str
    approved: bool


@dataclass(frozen=True)
class ToolFinished:
    context: EventContext
    batch_id: str
    position: int
    call_id: str
    name: str
    status: ToolStatus
    duration_ms: int
    error_message: str | None
    truncation: TruncationInfo | None


@dataclass(frozen=True)
class UsageReported:
    context: EventContext
    current: TokenUsage
    cumulative: TokenUsage


@dataclass(frozen=True)
class RunStopped:
    context: EventContext
    reason: StopReason
    message: str
    code: str | None = None


AgentEvent = (
    RunStarted
    | ProgressChanged
    | TextDeltaEvent
    | ToolStarted
    | ConfirmationRequested
    | ConfirmationResolved
    | ToolFinished
    | UsageReported
    | RunStopped
)
