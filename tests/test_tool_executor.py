import asyncio
from pathlib import Path

import pytest

from mewcode.cancellation import CancellationToken
from mewcode.errors import DeadlineExceeded, ToolFailure
from mewcode.tools.base import (
    ConfirmationPreview,
    PreparedToolAction,
    ToolCall,
    ToolDefinition,
    ToolOutputLimits,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class FakeTool:
    def __init__(self, *, confirmation=False, failure=None):
        self.definition = ToolDefinition(
            "fake",
            "Fake",
            {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        )
        self.requires_confirmation = confirmation
        self.failure = failure
        self.calls = []

    async def prepare(self, arguments, context):
        self.calls.append("prepare")
        if self.failure == "prepare":
            raise RuntimeError("secret-key exploded")
        return PreparedToolAction(
            dict(arguments),
            ConfirmationPreview("command", "Run command", "echo secret-key")
            if self.requires_confirmation
            else None,
        )

    async def execute(self, action, context):
        self.calls.append("execute")
        if self.failure == "timeout":
            raise DeadlineExceeded()
        if self.failure == "tool_failure":
            raise ToolFailure("known_failure", "secret-key failed", retryable=True)
        return ToolResult(status="success", data={"value": action.arguments["value"]})


def build_executor(tmp_path: Path, tool: FakeTool):
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(
        registry,
        Workspace(tmp_path),
        secrets=("secret-key",),
    )


def test_presentation_is_bounded_and_recursively_redacted(tmp_path: Path):
    executor = ToolExecutor(
        ToolRegistry(),
        Workspace(tmp_path),
        secrets=("secret-key",),
    )

    presentation = executor.presentation(
        "x" * 200,
        {
            "command": "echo secret-key " + "a" * 1000,
            "nested": {"token": "secret-key"},
        },
    )

    assert len(presentation.name) <= 80
    assert len(presentation.argument_summary) <= 512
    assert "secret-key" not in presentation.argument_summary
    assert "[redacted]" in presentation.argument_summary


def test_sanitize_preview_redacts_title_and_details_without_changing_kind(
    tmp_path: Path,
):
    executor = ToolExecutor(
        ToolRegistry(),
        Workspace(tmp_path),
        secrets=("secret-key",),
    )

    preview = executor.sanitize_preview(
        ConfirmationPreview(
            "write",
            "Write secret-key",
            '{"nested": "secret-key"}',
        )
    )

    assert preview.kind == "write"
    assert "secret-key" not in preview.title
    assert "secret-key" not in preview.details
    assert "[redacted]" in preview.details


async def approve(*_args):
    return True


@pytest.mark.asyncio
async def test_unknown_and_argument_errors_do_not_call_tool(tmp_path: Path):
    tool = FakeTool()
    executor = build_executor(tmp_path, tool)
    cancellation = CancellationToken()

    unknown = await executor.execute(
        ToolCall("1", "missing", {}),
        cancellation=cancellation,
        confirm=approve,
    )
    invalid_calls = [
        ToolCall("2", "fake", {}),
        ToolCall("3", "fake", {"value": 3}),
        ToolCall("4", "fake", {"value": "ok", "extra": "x"}),
    ]
    invalid = [
        await executor.execute(call, cancellation=cancellation, confirm=approve)
        for call in invalid_calls
    ]

    assert unknown.error.code == "unknown_tool"
    assert [result.error.code for result in invalid] == [
        "invalid_arguments",
        "invalid_arguments",
        "invalid_arguments",
    ]
    assert tool.calls == []


@pytest.mark.asyncio
async def test_confirmation_order_and_rejection(tmp_path: Path):
    tool = FakeTool(confirmation=True)
    executor = build_executor(tmp_path, tool)
    confirmations = []

    async def reject(call, preview):
        confirmations.append((call.call_id, preview))
        return False

    result = await executor.execute(
        ToolCall("1", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=reject,
    )

    assert result.status == "rejected"
    assert result.error.code == "user_rejected"
    assert tool.calls == ["prepare"]
    assert confirmations[0][0] == "1"
    assert "secret-key" not in confirmations[0][1].details


@pytest.mark.asyncio
async def test_no_confirmation_executes_without_calling_confirm(tmp_path: Path):
    tool = FakeTool()
    confirm_calls = []

    async def unexpected_confirm(call, preview):
        confirm_calls.append((call, preview))
        return True

    result = await build_executor(tmp_path, tool).execute(
        ToolCall("1", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=unexpected_confirm,
    )

    assert result.status == "success"
    assert tool.calls == ["prepare", "execute"]
    assert confirm_calls == []


@pytest.mark.asyncio
async def test_timeout_and_exception_are_structured_and_redacted(tmp_path: Path):
    timeout_tool = FakeTool(failure="timeout")
    timeout = await build_executor(tmp_path, timeout_tool).execute(
        ToolCall("1", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=approve,
    )
    assert timeout.status == "timeout"

    error_tool = FakeTool(failure="prepare")
    error = await build_executor(tmp_path, error_tool).execute(
        ToolCall("2", "fake", {"value": "secret-key"}),
        cancellation=CancellationToken(),
        confirm=approve,
    )
    assert error.status == "error"
    assert "secret-key" not in error.error.message
    assert "[redacted]" in error.error.message

    known_tool = FakeTool(failure="tool_failure")
    known = await build_executor(tmp_path, known_tool).execute(
        ToolCall("3", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=approve,
    )
    assert (known.error.code, known.error.retryable) == ("known_failure", True)
    assert "secret-key" not in known.error.message


@pytest.mark.asyncio
async def test_blocking_ordinary_tool_is_interrupted_by_timeout(tmp_path: Path):
    class BlockingTool(FakeTool):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def execute(self, action, context):
            self.started.set()
            await self.release.wait()
            return ToolResult(status="success")

    tool = BlockingTool()
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(
        registry,
        Workspace(tmp_path),
        clock=lambda: 0.0,
        ordinary_timeout_seconds=0.01,
    )

    result = await executor.execute(
        ToolCall("1", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=approve,
    )

    assert result.status == "timeout"
    assert tool.started.is_set()


@pytest.mark.asyncio
async def test_cancellation_propagates_without_conversion_or_execution(tmp_path: Path):
    class BlockingPrepareTool(FakeTool):
        def __init__(self):
            super().__init__()
            self.started = asyncio.Event()

        async def prepare(self, arguments, context):
            self.calls.append("prepare")
            self.started.set()
            await asyncio.Event().wait()

    tool = BlockingPrepareTool()
    token = CancellationToken()
    task = asyncio.create_task(
        build_executor(tmp_path, tool).execute(
            ToolCall("1", "fake", {"value": "ok"}),
            cancellation=token,
            confirm=approve,
        )
    )
    await tool.started.wait()
    token.cancel()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert tool.calls == ["prepare"]

    pre_cancelled = CancellationToken()
    pre_cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await build_executor(tmp_path, FakeTool()).execute(
            ToolCall("2", "fake", {"value": "ok"}),
            cancellation=pre_cancelled,
            confirm=approve,
        )


@pytest.mark.asyncio
async def test_timing_and_truncation_preserve_structured_model_feedback(
    tmp_path: Path,
):
    class LargeResultTool(FakeTool):
        async def execute(self, action, context):
            self.calls.append("execute")
            return ToolResult(
                status="success",
                data={
                    "content": "abcdefgh",
                    "stdout": "123456",
                    "paths": ["a", "b", "c"],
                    "matches": [1, 2, 3],
                },
            )

    tool = LargeResultTool()
    registry = ToolRegistry()
    registry.register(tool)
    ticks = iter([10.0, 10.0, 10.0, 10.0, 10.125])
    executor = ToolExecutor(
        registry,
        Workspace(tmp_path),
        limits=ToolOutputLimits(
            text_characters=5,
            command_characters=4,
            paths=2,
            matches=2,
        ),
        clock=lambda: next(ticks),
    )

    result = await executor.execute(
        ToolCall("1", "fake", {"value": "ok"}),
        cancellation=CancellationToken(),
        confirm=approve,
    )

    assert result.duration_ms == 125
    assert result.data["content"] == "abcde"
    assert result.data["stdout"] == "1234"
    assert result.data["paths"] == ["a", "b"]
    assert result.data["matches"] == [1, 2]
    assert len(result.data["truncations"]) == 4
    assert result.to_model_payload()["status"] == "success"
