import json
import inspect
from dataclasses import FrozenInstanceError
from typing import get_args

import pytest

from mewcode.cancellation import CancellationToken
from mewcode.errors import DeadlineExceeded
from mewcode.tools.base import (
    ConfirmationPreview,
    Deadline,
    PreparedToolAction,
    Tool,
    ToolAccess,
    ToolCall,
    ToolContext,
    ToolDefinition,
    ToolDescriptor,
    ToolErrorInfo,
    ToolExecutionPolicy,
    ToolFeedback,
    ToolOutputLimits,
    ToolPresentation,
    ToolResult,
    ToolScope,
    TruncationInfo,
)
from mewcode.tools.registry import ToolRegistry


class FakeTool:
    requires_confirmation = False

    def __init__(self, name: str = "fake", schema=None):
        self.definition = ToolDefinition(
            name=name,
            description="A fake tool.",
            input_schema=schema
            or {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        )


def test_result_payload_is_json_serializable():
    result = ToolResult(
        status="error",
        data={"path": "a.txt"},
        error=ToolErrorInfo("bad", "Nope", True),
        truncation=TruncationInfo("characters", 20, 10, "Narrow the request."),
        duration_ms=4,
    )

    payload = result.to_model_payload()

    assert json.loads(json.dumps(payload)) == payload
    assert payload["status"] == "error"
    assert payload["error"]["code"] == "bad"
    assert payload["truncation"]["original"] == 20


def test_base_types_are_frozen():
    preview = ConfirmationPreview("write", "Write file", "diff")
    action = PreparedToolAction({}, preview, object())
    limits = ToolOutputLimits()

    with pytest.raises(FrozenInstanceError):
        preview.title = "changed"  # type: ignore[misc]
    assert action.preview is preview
    assert limits.paths == 1000


def test_agent_tool_base_types_policy_and_scope_are_stable():
    definition = ToolDefinition("read_file", "Read a file", {"type": "object"})
    result = ToolResult(status="success", data={"content": "hello"})
    call = ToolCall("call-1", "read_file", {"path": "README.md"})
    feedback = ToolFeedback("call-1", "read_file", result)
    descriptor = ToolDescriptor(
        definition,
        ToolAccess.READ_ONLY,
        ToolExecutionPolicy.PARALLEL_SAFE,
        False,
    )
    presentation = ToolPresentation("read_file", "path=README.md")
    cancellation = CancellationToken()
    context = ToolContext(object(), Deadline(30), ToolOutputLimits(), cancellation)

    assert call.arguments == {"path": "README.md"}
    assert feedback.result is result
    assert descriptor.definition is definition
    assert descriptor.access.value == "read_only"
    assert descriptor.execution_policy.value == "parallel_safe"
    assert presentation.argument_summary == "path=README.md"
    assert set(get_args(ToolScope)) == {"all", "read_only"}
    assert context.cancellation is cancellation
    assert inspect.iscoroutinefunction(Tool.prepare)
    assert inspect.iscoroutinefunction(Tool.execute)
    with pytest.raises(FrozenInstanceError):
        call.name = "changed"


def test_deadline_raises_after_expiry():
    now = [10.0]
    deadline = Deadline(2.0, clock=lambda: now[0])
    now[0] = 12.0

    with pytest.raises(DeadlineExceeded):
        deadline.check()


def test_register_lookup_and_order():
    registry = ToolRegistry()
    first = FakeTool("first")
    second = FakeTool("second")

    registry.register(first)
    registry.register(second)

    assert registry.get("first") is first
    assert [item.name for item in registry.definitions()] == ["first", "second"]


def test_definitions_filter_read_only_scope_without_leaking_descriptors():
    registry = ToolRegistry()
    read = FakeTool("read")
    read.access = ToolAccess.READ_ONLY
    read.execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    write = FakeTool("write")
    write.access = ToolAccess.MUTATING
    write.execution_policy = ToolExecutionPolicy.SERIAL
    defaulted = FakeTool("defaulted")

    registry.register(read)
    registry.register(write)
    registry.register(defaulted)

    assert [item.name for item in registry.definitions("all")] == [
        "read",
        "write",
        "defaulted",
    ]
    read_only = registry.definitions("read_only")
    assert read_only == (read.definition,)
    assert all(isinstance(item, ToolDefinition) for item in read_only)
    assert ToolRegistry().definitions("read_only") == ()


def test_registry_descriptor_uses_conservative_default_policy():
    registry = ToolRegistry()
    tool = FakeTool()

    registry.register(tool)

    descriptor = registry.descriptor("fake")
    assert registry.get("fake") is tool
    assert descriptor == ToolDescriptor(
        tool.definition,
        ToolAccess.MUTATING,
        ToolExecutionPolicy.SERIAL,
        False,
    )
    assert registry.descriptor("missing") is None


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_registry_rejects_dangerous_policy_for_parallel_mutation(
    requires_confirmation,
):
    tool = FakeTool()
    tool.access = ToolAccess.MUTATING
    tool.execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    tool.requires_confirmation = requires_confirmation

    with pytest.raises(ValueError, match="must use serial execution"):
        ToolRegistry().register(tool)


def test_registry_rejects_confirmation_with_parallel_policy():
    tool = FakeTool()
    tool.access = ToolAccess.READ_ONLY
    tool.execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    tool.requires_confirmation = True

    with pytest.raises(ValueError, match="must use serial execution"):
        ToolRegistry().register(tool)


def test_register_rejects_empty_and_duplicate_names():
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="must not be empty"):
        registry.register(FakeTool(" "))

    registry.register(FakeTool("same"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(FakeTool("same"))


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "string", "additionalProperties": False},
        {"type": "object", "properties": {"x": {"type": "not-a-type"}}, "additionalProperties": False},
        {"type": "object", "properties": {}},
    ],
)
def test_schema_rejects_invalid_definitions(schema):
    with pytest.raises(ValueError):
        ToolRegistry().register(FakeTool(schema=schema))
