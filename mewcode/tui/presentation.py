from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mewcode.agent.events import ProgressChanged, RunStopped, UsageReported
from mewcode.agent.types import RunPhase, StopReason

DEFAULT_ERROR_SUGGESTION = (
    "Retry the request. If it fails again, check network access and provider settings."
)
INTERNAL_ERROR_SUGGESTION = (
    "Retry once. If it recurs, restart MewCode and report the error code."
)


class ActivityState(str, Enum):
    READY = "ready"
    UPLINKING = "uplinking"
    STREAMING = "streaming"
    EXECUTING = "executing"
    CONFIRMING = "confirming"
    SYNTHESIZING = "synthesizing"
    STOPPING = "stopping"
    INTERRUPTED = "interrupted"
    ERROR = "error"


@dataclass(frozen=True)
class ErrorPresentation:
    message: str
    technical_detail: str | None = None
    suggestion: str = DEFAULT_ERROR_SUGGESTION


def activity_for_progress(event: ProgressChanged) -> tuple[ActivityState, str]:
    state = {
        RunPhase.WAITING_MODEL: ActivityState.UPLINKING,
        RunPhase.STREAMING_MODEL: ActivityState.STREAMING,
        RunPhase.EXECUTING_TOOLS: ActivityState.EXECUTING,
        RunPhase.WAITING_CONFIRMATION: ActivityState.CONFIRMING,
        RunPhase.FEEDING_BACK: ActivityState.SYNTHESIZING,
        RunPhase.STOPPING: ActivityState.STOPPING,
    }[event.phase]
    return state, f"round {event.current_iteration}/{event.max_iterations}"


def activity_for_stop(event: RunStopped) -> ActivityState:
    if event.reason is StopReason.COMPLETED:
        return ActivityState.READY
    if event.reason is StopReason.CANCELLED:
        return ActivityState.INTERRUPTED
    return ActivityState.ERROR


def error_for_stop(event: RunStopped) -> ErrorPresentation | None:
    if event.reason in {StopReason.COMPLETED, StopReason.CANCELLED}:
        return None
    if event.reason is StopReason.INTERNAL_ERROR:
        return ErrorPresentation(
            "The agent stopped because of an internal error.",
            event.code,
            INTERNAL_ERROR_SUGGESTION,
        )
    if event.reason is StopReason.ITERATION_LIMIT:
        return ErrorPresentation(
            "Agent stopped after reaching the iteration limit.",
            event.code,
            "Review the partial result, then narrow the request or continue explicitly.",
        )
    if event.reason is StopReason.UNKNOWN_TOOL_LIMIT:
        return ErrorPresentation(
            "Agent stopped after repeated unknown tool calls.",
            event.code,
            "Retry with the available workspace tools or revise the request.",
        )
    return ErrorPresentation(event.message, event.code)


def stop_label(event: RunStopped) -> str:
    return event.reason.value.upper().replace("_", " ")


def usage_text(event: UsageReported) -> str:
    def value(number: int | None) -> str:
        return "n/a" if number is None else str(number)

    return (
        "tokens "
        f"in:{value(event.current.input_tokens)} "
        f"out:{value(event.current.output_tokens)} "
        f"total:{value(event.current.total_tokens)} "
        "| cumulative "
        f"in:{value(event.cumulative.input_tokens)} "
        f"out:{value(event.cumulative.output_tokens)} "
        f"total:{value(event.cumulative.total_tokens)}"
    )
