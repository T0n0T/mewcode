from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass

from textual.message import Message

from mewcode.tools.base import ConfirmationPreview, ToolStatus
from mewcode.tui.presentation import ActivityState
from mewcode.turns import TurnPhase

DEFAULT_ERROR_SUGGESTION = (
    "Retry the request. If it fails again, check network access and provider settings."
)
INTERNAL_ERROR_SUGGESTION = (
    "Retry once. If it recurs, restart MewCode and report the error type."
)
TOOL_BUDGET_SUGGESTION = (
    "Start a new turn or ask for a final answer without another tool."
)


@dataclass(frozen=True)
class TurnPhasePayload:
    generation_id: int
    phase: TurnPhase


@dataclass(frozen=True)
class TurnTextPayload:
    generation_id: int
    text: str


@dataclass(frozen=True)
class TurnLifecyclePayload:
    generation_id: int


@dataclass(frozen=True)
class TurnErrorPayload:
    generation_id: int
    message: str
    technical_detail: str | None = None
    suggestion: str = DEFAULT_ERROR_SUGGESTION


@dataclass(frozen=True)
class ToolStartedPayload:
    generation_id: int
    call_id: str
    name: str
    argument_summary: str
    started_at: float


@dataclass(frozen=True)
class TruncationPresentation:
    unit: str
    original: int
    returned: int
    hint: str
    field: str | None = None


@dataclass(frozen=True)
class ToolFinishedPayload:
    generation_id: int
    call_id: str
    name: str
    status: ToolStatus
    duration_ms: int
    error_message: str | None
    truncation: TruncationPresentation | None


@dataclass(frozen=True)
class ToolBudgetPayload:
    generation_id: int


@dataclass(frozen=True)
class ConfirmationPayload:
    generation_id: int
    preview: ConfirmationPreview
    decision: Future[bool]


class PayloadMessage(Message):
    def __init__(self, payload: object) -> None:
        super().__init__()
        self.payload = payload


class TurnPhaseMessage(PayloadMessage):
    payload: TurnPhasePayload


class TurnTextMessage(PayloadMessage):
    payload: TurnTextPayload


class TurnCompletedMessage(PayloadMessage):
    payload: TurnLifecyclePayload


class TurnInterruptedMessage(PayloadMessage):
    payload: TurnLifecyclePayload


class TurnErrorMessage(PayloadMessage):
    payload: TurnErrorPayload


class ToolStartedMessage(PayloadMessage):
    payload: ToolStartedPayload


class ToolFinishedMessage(PayloadMessage):
    payload: ToolFinishedPayload


class ToolBudgetMessage(PayloadMessage):
    payload: ToolBudgetPayload


class ConfirmationRequestedMessage(PayloadMessage):
    payload: ConfirmationPayload
