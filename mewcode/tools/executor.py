from __future__ import annotations

import time
import signal
import threading
from contextlib import contextmanager
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Protocol

from jsonschema import Draft202012Validator

from mewcode.errors import DeadlineExceeded, ToolFailure, redact_secrets
from mewcode.providers.base import ToolCall
from mewcode.tools.base import (
    ConfirmationPreview,
    Deadline,
    JSONValue,
    ToolContext,
    ToolErrorInfo,
    ToolOutputLimits,
    ToolResult,
    TruncationInfo,
)
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class ToolInteraction(Protocol):
    def tool_started(self, call: ToolCall) -> None: ...

    def confirm(self, preview: ConfirmationPreview) -> bool: ...

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None: ...

    def tool_budget_exhausted(self) -> None: ...


class NullToolInteraction:
    def tool_started(self, call: ToolCall) -> None:
        return None

    def confirm(self, preview: ConfirmationPreview) -> bool:
        return False

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        return None

    def tool_budget_exhausted(self) -> None:
        return None


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        workspace: Workspace,
        interaction: ToolInteraction | None = None,
        *,
        limits: ToolOutputLimits | None = None,
        secrets: tuple[str, ...] = (),
        clock: Callable[[], float] = time.monotonic,
        ordinary_timeout_seconds: float = 30.0,
    ):
        self.registry = registry
        self.workspace = workspace
        self.interaction = interaction or NullToolInteraction()
        self.limits = limits or ToolOutputLimits()
        self.secrets = secrets
        self._clock = clock
        self.ordinary_timeout_seconds = ordinary_timeout_seconds

    def execute(self, call: ToolCall) -> ToolResult:
        started = self._clock()
        display_call = replace(call, arguments=_redact_value(call.arguments, self.secrets))
        self.interaction.tool_started(display_call)
        try:
            tool = self.registry.get(call.name)
            manages_own_timeout = bool(
                tool is not None and getattr(tool, "manages_own_timeout", False)
            )
            with _hard_deadline(
                None if manages_own_timeout else self.ordinary_timeout_seconds
            ):
                result = self._execute(call)
        except DeadlineExceeded as exc:
            result = ToolResult(
                status="timeout",
                error=ToolErrorInfo(code="timeout", message=str(exc), retryable=True),
            )
        except Exception as exc:
            result = ToolResult(
                status="error",
                error=ToolErrorInfo(
                    code="execution_error",
                    message=redact_secrets(str(exc) or "Tool execution failed.", self.secrets),
                    retryable=False,
                ),
            )
        result = replace(
            result,
            data=_redact_value(result.data, self.secrets),
            error=_redact_error(result.error, self.secrets),
            duration_ms=max(0, round((self._clock() - started) * 1000)),
        )
        result = _limit_result(result, self.limits)
        self.interaction.tool_finished(display_call, result)
        return result

    def _execute(self, call: ToolCall) -> ToolResult:
        tool = self.registry.get(call.name)
        if tool is None:
            return _error("unknown_tool", f"Unknown tool '{call.name}'.", retryable=True)

        errors = sorted(
            Draft202012Validator(tool.definition.input_schema).iter_errors(call.arguments),
            key=lambda error: list(error.absolute_path),
        )
        if errors:
            error = errors[0]
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            return _error(
                "invalid_arguments",
                f"Invalid tool arguments at {location}: {error.message}",
                retryable=True,
            )

        context = ToolContext(
            workspace=self.workspace,
            deadline=Deadline(self.ordinary_timeout_seconds, clock=self._clock),
            limits=self.limits,
        )
        try:
            action = tool.prepare(call.arguments, context)
            context.deadline.check()
            if tool.requires_confirmation:
                if action.preview is None:
                    return _error(
                        "missing_confirmation_preview",
                        "Tool requires confirmation but did not provide a preview.",
                    )
                if not self.interaction.confirm(action.preview):
                    return ToolResult(
                        status="rejected",
                        error=ToolErrorInfo(
                            code="user_rejected",
                            message="User rejected the tool action.",
                            retryable=True,
                        ),
                    )
            result = tool.execute(action, context)
            if not getattr(tool, "manages_own_timeout", False):
                context.deadline.check()
            return result
        except DeadlineExceeded as exc:
            return ToolResult(
                status="timeout",
                error=ToolErrorInfo(code="timeout", message=str(exc), retryable=True),
            )
        except ToolFailure as exc:
            status = "timeout" if exc.code == "timeout" else "error"
            return ToolResult(
                status=status,
                error=ToolErrorInfo(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )


def _error(code: str, message: str, *, retryable: bool = False) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolErrorInfo(code=code, message=message, retryable=retryable),
    )


def _redact_value(value: JSONValue, secrets: tuple[str, ...]) -> JSONValue:
    if isinstance(value, str):
        return redact_secrets(value, secrets)
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    return value


def _redact_error(
    error: ToolErrorInfo | None, secrets: tuple[str, ...]
) -> ToolErrorInfo | None:
    if error is None:
        return None
    return replace(error, message=redact_secrets(error.message, secrets))


def _limit_result(result: ToolResult, limits: ToolOutputLimits) -> ToolResult:
    data = dict(result.data)
    truncations: list[TruncationInfo] = []

    for field in ("content", "stdout", "stderr"):
        value = data.get(field)
        if not isinstance(value, str):
            continue
        limit = (
            limits.command_characters if field in {"stdout", "stderr"} else limits.text_characters
        )
        if len(value) > limit:
            data[field] = value[:limit]
            truncations.append(
                TruncationInfo(
                    unit="characters",
                    original=len(value),
                    returned=limit,
                    hint=f"Narrow the request to reduce {field} output.",
                    field=field,
                )
            )

    for field, unit, limit in (
        ("paths", "paths", limits.paths),
        ("matches", "matches", limits.matches),
    ):
        value = data.get(field)
        if isinstance(value, list) and len(value) > limit:
            data[field] = value[:limit]
            truncations.append(
                TruncationInfo(
                    unit=unit,
                    original=len(value),
                    returned=limit,
                    hint=f"Narrow the pattern or search scope to reduce {field}.",
                    field=field,
                )
            )

    if not truncations:
        return replace(result, data=data)
    if len(truncations) == 1:
        return replace(result, data=data, truncation=truncations[0])
    data["truncations"] = [
        {
            "unit": item.unit,
            "original": item.original,
            "returned": item.returned,
            "hint": item.hint,
            "field": item.field,
        }
        for item in truncations
    ]
    return replace(result, data=data, truncation=truncations[0])


@contextmanager
def _hard_deadline(timeout_seconds: float | None):
    if (
        timeout_seconds is None
        or timeout_seconds <= 0
        or not hasattr(signal, "setitimer")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGALRM)

    def timeout_handler(signum, frame):
        raise DeadlineExceeded()

    signal.signal(signal.SIGALRM, timeout_handler)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)
