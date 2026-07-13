from pathlib import Path
import time

from mewcode.errors import DeadlineExceeded
from mewcode.providers.base import ToolCall
from mewcode.tools.base import (
    ConfirmationPreview,
    PreparedToolAction,
    ToolDefinition,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class RecordingInteraction:
    def __init__(self, approved=True):
        self.approved = approved
        self.events = []

    def tool_started(self, call):
        self.events.append(("started", call))

    def confirm(self, preview):
        self.events.append(("confirm", preview))
        return self.approved

    def tool_finished(self, call, result):
        self.events.append(("finished", result))

    def tool_budget_exhausted(self):
        self.events.append(("budget", None))


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

    def prepare(self, arguments, context):
        self.calls.append("prepare")
        if self.failure == "prepare":
            raise RuntimeError("secret-key exploded")
        return PreparedToolAction(
            dict(arguments),
            ConfirmationPreview("command", "Run command", "echo secret-key")
            if self.requires_confirmation
            else None,
        )

    def execute(self, action, context):
        self.calls.append("execute")
        if self.failure == "timeout":
            raise DeadlineExceeded()
        return ToolResult(status="success", data={"value": action.arguments["value"]})


def build_executor(tmp_path: Path, tool: FakeTool, interaction=None):
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(
        registry,
        Workspace(tmp_path),
        interaction,
        secrets=("secret-key",),
    )


def test_unknown_and_argument_errors_do_not_call_tool(tmp_path: Path):
    tool = FakeTool()
    executor = build_executor(tmp_path, tool)

    unknown = executor.execute(ToolCall("1", "missing", {}))
    invalid = executor.execute(ToolCall("2", "fake", {"extra": "x"}))

    assert unknown.error.code == "unknown_tool"
    assert invalid.error.code == "invalid_arguments"
    assert tool.calls == []


def test_confirmation_order_and_rejection(tmp_path: Path):
    tool = FakeTool(confirmation=True)
    interaction = RecordingInteraction(approved=False)
    executor = build_executor(tmp_path, tool, interaction)

    result = executor.execute(ToolCall("1", "fake", {"value": "ok"}))

    assert result.status == "rejected"
    assert tool.calls == ["prepare"]
    assert [event[0] for event in interaction.events] == ["started", "confirm", "finished"]


def test_no_confirmation_executes_and_notifies(tmp_path: Path):
    tool = FakeTool()
    interaction = RecordingInteraction()
    result = build_executor(tmp_path, tool, interaction).execute(
        ToolCall("1", "fake", {"value": "ok"})
    )

    assert result.status == "success"
    assert tool.calls == ["prepare", "execute"]
    assert [event[0] for event in interaction.events] == ["started", "finished"]


def test_timeout_and_exception_are_structured_and_redacted(tmp_path: Path):
    timeout_tool = FakeTool(failure="timeout")
    timeout = build_executor(tmp_path, timeout_tool).execute(
        ToolCall("1", "fake", {"value": "ok"})
    )
    assert timeout.status == "timeout"

    error_tool = FakeTool(failure="prepare")
    error = build_executor(tmp_path, error_tool).execute(
        ToolCall("2", "fake", {"value": "secret-key"})
    )
    assert error.status == "error"
    assert "secret-key" not in error.error.message
    assert "[redacted]" in error.error.message


def test_blocking_ordinary_tool_is_interrupted_by_deadline(tmp_path: Path):
    class BlockingTool(FakeTool):
        def execute(self, action, context):
            time.sleep(1)
            return ToolResult(status="success")

    tool = BlockingTool()
    registry = ToolRegistry()
    registry.register(tool)
    executor = ToolExecutor(
        registry,
        Workspace(tmp_path),
        ordinary_timeout_seconds=0.02,
    )

    started = time.monotonic()
    result = executor.execute(ToolCall("1", "fake", {"value": "ok"}))

    assert result.status == "timeout"
    assert time.monotonic() - started < 0.5
