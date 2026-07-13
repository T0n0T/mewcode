import json
from dataclasses import FrozenInstanceError

import pytest

from mewcode.errors import DeadlineExceeded
from mewcode.tools.base import (
    ConfirmationPreview,
    Deadline,
    PreparedToolAction,
    ToolDefinition,
    ToolErrorInfo,
    ToolOutputLimits,
    ToolResult,
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
