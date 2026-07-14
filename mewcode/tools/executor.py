from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace

from jsonschema import Draft202012Validator

from mewcode.cancellation import CancellationToken
from mewcode.errors import DeadlineExceeded, ToolFailure, redact_secrets
from mewcode.tools.base import (
    ConfirmationPreview,
    Deadline,
    JSONValue,
    ToolContext,
    ToolCall,
    ToolErrorInfo,
    ToolOutputLimits,
    ToolPresentation,
    ToolResult,
    TruncationInfo,
)
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


ConfirmationHandler = Callable[[ToolCall, ConfirmationPreview], Awaitable[bool]]


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        workspace: Workspace,
        *,
        limits: ToolOutputLimits | None = None,
        secrets: tuple[str, ...] = (),
        clock: Callable[[], float] = time.monotonic,
        ordinary_timeout_seconds: float = 30.0,
    ):
        self.registry = registry
        self.workspace = workspace
        self.limits = limits or ToolOutputLimits()
        self.secrets = secrets
        self._clock = clock
        self.ordinary_timeout_seconds = ordinary_timeout_seconds

    def presentation(
        self,
        name: str,
        arguments: Mapping[str, JSONValue],
    ) -> ToolPresentation:
        safe_arguments = _redact_value(dict(arguments), self.secrets)
        summary = json.dumps(safe_arguments, ensure_ascii=False, sort_keys=True)
        return ToolPresentation(name=name[:80], argument_summary=summary[:512])

    def sanitize_preview(self, preview: ConfirmationPreview) -> ConfirmationPreview:
        return replace(
            preview,
            title=redact_secrets(preview.title, self.secrets),
            details=redact_secrets(preview.details, self.secrets),
        )

    async def execute(
        self,
        call: ToolCall,
        *,
        cancellation: CancellationToken,
        confirm: ConfirmationHandler,
    ) -> ToolResult:
        cancellation.raise_if_cancelled()
        started = self._clock()
        try:
            tool = self.registry.get(call.name)
            manages_own_timeout = bool(
                tool is not None and getattr(tool, "manages_own_timeout", False)
            )
            timeout = None if manages_own_timeout else self.ordinary_timeout_seconds
            async with asyncio.timeout(timeout):
                result = await self._execute(call, cancellation, confirm)
        except (TimeoutError, DeadlineExceeded) as exc:
            message = str(exc) or "Tool execution timed out."
            result = ToolResult(
                status="timeout",
                error=ToolErrorInfo(code="timeout", message=message, retryable=True),
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
        return result

    async def _execute(
        self,
        call: ToolCall,
        cancellation: CancellationToken,
        confirm: ConfirmationHandler,
    ) -> ToolResult:
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
            cancellation=cancellation,
        )
        try:
            action = await tool.prepare(call.arguments, context)
            context.deadline.check()
            cancellation.raise_if_cancelled()
            if tool.requires_confirmation:
                if action.preview is None:
                    return _error(
                        "missing_confirmation_preview",
                        "Tool requires confirmation but did not provide a preview.",
                    )
                preview = self.sanitize_preview(action.preview)
                if not await confirm(call, preview):
                    return ToolResult(
                        status="rejected",
                        error=ToolErrorInfo(
                            code="user_rejected",
                            message="User rejected the tool action.",
                            retryable=True,
                        ),
                    )
                cancellation.raise_if_cancelled()
            result = await tool.execute(action, context)
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
