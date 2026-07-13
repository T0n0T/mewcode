from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, TypeAlias

from mewcode.errors import DeadlineExceeded

if TYPE_CHECKING:
    from mewcode.tools.workspace import Workspace

JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)
ToolStatus = Literal["success", "error", "rejected", "timeout"]
TruncationUnit = Literal["characters", "bytes", "paths", "matches"]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, JSONValue]


@dataclass(frozen=True)
class ToolErrorInfo:
    code: str
    message: str
    retryable: bool


@dataclass(frozen=True)
class TruncationInfo:
    unit: TruncationUnit
    original: int
    returned: int
    hint: str
    field: str | None = None


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    data: dict[str, JSONValue] = field(default_factory=dict)
    error: ToolErrorInfo | None = None
    truncation: TruncationInfo | None = None
    duration_ms: int = 0

    def to_model_payload(self) -> dict[str, JSONValue]:
        payload: dict[str, JSONValue] = {
            "status": self.status,
            "data": self.data,
            "duration_ms": self.duration_ms,
        }
        if self.error is not None:
            payload["error"] = {
                "code": self.error.code,
                "message": self.error.message,
                "retryable": self.error.retryable,
            }
        if self.truncation is not None:
            payload["truncation"] = {
                "unit": self.truncation.unit,
                "original": self.truncation.original,
                "returned": self.truncation.returned,
                "hint": self.truncation.hint,
            }
            if self.truncation.field is not None:
                payload["truncation"]["field"] = self.truncation.field
        return payload


@dataclass(frozen=True)
class ConfirmationPreview:
    kind: Literal["command", "write", "edit"]
    title: str
    details: str


@dataclass(frozen=True)
class PreparedToolAction:
    arguments: dict[str, JSONValue]
    preview: ConfirmationPreview | None
    state: object = field(default=None, repr=False)


@dataclass(frozen=True)
class ToolOutputLimits:
    text_characters: int = 50_000
    paths: int = 1_000
    matches: int = 500
    command_characters: int = 50_000


class Deadline:
    def __init__(
        self,
        timeout_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.timeout_seconds = timeout_seconds
        self._clock = clock
        self._expires_at = clock() + timeout_seconds

    @property
    def remaining(self) -> float:
        return max(0.0, self._expires_at - self._clock())

    def check(self) -> None:
        if self._clock() >= self._expires_at:
            raise DeadlineExceeded()


@dataclass(frozen=True)
class ToolContext:
    workspace: "Workspace"
    deadline: Deadline
    limits: ToolOutputLimits


class Tool(Protocol):
    definition: ToolDefinition
    requires_confirmation: bool

    def prepare(
        self,
        arguments: Mapping[str, JSONValue],
        context: ToolContext,
    ) -> PreparedToolAction: ...

    def execute(
        self,
        action: PreparedToolAction,
        context: ToolContext,
    ) -> ToolResult: ...
