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
from mewcode.tools.defaults import create_default_registry


EXPECTED_BUILTIN_DESCRIPTIONS = {
    "read_file": (
        "Read a UTF-8 text file from the workspace, optionally by line range. "
        "You must use this tool before edit_file, and before write_file when replacing "
        "an existing file. Prefer it over run_command for reading file contents."
    ),
    "write_file": (
        "Create a new UTF-8 text file or completely replace an existing one in the "
        "workspace. Before replacing an existing file, first call read_file for the "
        "same path in the current run. Prefer edit_file for localized changes, and do "
        "not use run_command as a substitute."
    ),
    "edit_file": (
        "Replace one exact, unique text occurrence in a workspace UTF-8 file. Before "
        "calling this tool, first call read_file for the same path in the current run "
        "and copy old_text exactly from the fresh result. Prefer it over write_file for "
        "localized changes and over run_command for direct file edits."
    ),
    "run_command": (
        "Run a complete shell command in the workspace after user confirmation. Use "
        "this tool only when no dedicated MewCode tool fits the operation; do not use "
        "shell commands as substitutes for read_file, glob_files, search_code, "
        "write_file, or edit_file."
    ),
    "glob_files": (
        "Find workspace files matching a relative glob pattern. Prefer this dedicated "
        "tool over run_command for locating files by name or path pattern."
    ),
    "search_code": (
        "Search UTF-8 text files in the workspace for a literal string or regular "
        "expression, optionally restricted by a path pattern. Prefer this dedicated "
        "tool over run_command for searching file contents."
    ),
}

EXPECTED_BUILTIN_SCHEMA_SHAPES = {
    "read_file": (
        ("path", "start_line", "line_count"),
        ("path",),
    ),
    "write_file": (("path", "content"), ("path", "content")),
    "edit_file": (
        ("path", "old_text", "new_text"),
        ("path", "old_text", "new_text"),
    ),
    "run_command": (("command", "timeout_seconds"), ("command",)),
    "glob_files": (("pattern",), ("pattern",)),
    "search_code": (("query", "path_pattern", "regex"), ("query",)),
}


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
        {
            "type": "object",
            "properties": {"x": {"type": "not-a-type"}},
            "additionalProperties": False,
        },
        {"type": "object", "properties": {}},
    ],
)
def test_schema_rejects_invalid_definitions(schema):
    with pytest.raises(ValueError):
        ToolRegistry().register(FakeTool(schema=schema))


def test_default_registry_builtin_policy_and_registration_order():
    registry = create_default_registry()

    assert [definition.name for definition in registry.definitions()] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "glob_files",
        "search_code",
    ]
    for name in ("read_file", "glob_files", "search_code"):
        descriptor = registry.descriptor(name)
        assert descriptor.access is ToolAccess.READ_ONLY
        assert descriptor.execution_policy is ToolExecutionPolicy.PARALLEL_SAFE
        assert descriptor.requires_confirmation is False
    for name in ("write_file", "edit_file", "run_command"):
        descriptor = registry.descriptor(name)
        assert descriptor.access is ToolAccess.MUTATING
        assert descriptor.execution_policy is ToolExecutionPolicy.SERIAL
        assert descriptor.requires_confirmation is True


def test_default_registry_builtin_descriptions_and_schema_shapes_are_stable():
    definitions = create_default_registry().definitions()

    assert {
        definition.name: definition.description for definition in definitions
    } == EXPECTED_BUILTIN_DESCRIPTIONS
    assert {
        definition.name: (
            tuple(definition.input_schema["properties"]),
            tuple(definition.input_schema.get("required", ())),
        )
        for definition in definitions
    } == EXPECTED_BUILTIN_SCHEMA_SHAPES
    assert all(
        definition.input_schema["type"] == "object"
        and definition.input_schema["additionalProperties"] is False
        for definition in definitions
    )
