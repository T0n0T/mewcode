from pathlib import Path

import pytest

from mewcode.errors import ProviderError
from mewcode.providers.base import (
    AssistantMessage,
    ResponseCompleted,
    TextDelta,
    ToolCallDelta,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.runtime import ChatRuntime
from mewcode.tools.base import PreparedToolAction, ToolDefinition, ToolResult
from mewcode.tools.defaults import create_default_registry
from mewcode.tools.executor import NullToolInteraction, ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def stream_response(self, history, tools):
        self.calls.append((tuple(history), tuple(tools)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield from response


class RecordingTool:
    definition = ToolDefinition(
        "echo",
        "Echo text",
        {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    )
    requires_confirmation = False

    def __init__(self):
        self.calls = []

    def prepare(self, arguments, context):
        return PreparedToolAction(dict(arguments), None)

    def execute(self, action, context):
        self.calls.append(action.arguments)
        return ToolResult(status="success", data={"echo": action.arguments["text"]})


class RecordingInteraction(NullToolInteraction):
    def __init__(self):
        self.budget_events = 0

    def tool_budget_exhausted(self):
        self.budget_events += 1


def build_runtime(tmp_path: Path, responses):
    registry = ToolRegistry()
    tool = RecordingTool()
    registry.register(tool)
    interaction = RecordingInteraction()
    executor = ToolExecutor(registry, Workspace(tmp_path), interaction)
    return ChatRuntime(FakeProvider(responses), registry, executor), tool, interaction


def completed(text="", state=None):
    return [TextDelta(text)] if text else []


def plain_response(text):
    return [TextDelta(text), ResponseCompleted({"output": text})]


def tool_response(arguments='{"text":"hi"}', slot=0, call_id="call-1", name="echo"):
    return [
        ToolCallDelta(slot, call_id_delta=call_id, name_delta=name),
        ToolCallDelta(slot, arguments_delta=arguments),
        ResponseCompleted({"tool": call_id}),
    ]


def test_plain_response_streams_and_commits_history(tmp_path):
    runtime, _, _ = build_runtime(tmp_path, [plain_response("hello")])
    assert list(runtime.stream_turn("Hi")) == ["hello"]
    assert runtime.history == (
        UserMessage("Hi"),
        AssistantMessage("hello", {"output": "hello"}),
    )
    assert len(runtime._provider.calls) == 1


def test_plain_response_includes_previous_history(tmp_path):
    runtime, _, _ = build_runtime(tmp_path, [plain_response("first"), plain_response("second")])
    list(runtime.stream_turn("One"))
    list(runtime.stream_turn("Two"))
    assert runtime._provider.calls[1][0] == (
        UserMessage("One"),
        AssistantMessage("first", {"output": "first"}),
        UserMessage("Two"),
    )


def test_provider_failure_keeps_user_but_not_partial_assistant(tmp_path):
    response = [TextDelta("partial")]

    class FailingProvider(FakeProvider):
        def stream_response(self, history, tools):
            self.calls.append((tuple(history), tuple(tools)))
            yield from response
            raise ProviderError("bad network")

    runtime, _, _ = build_runtime(tmp_path, [])
    runtime._provider = FailingProvider([])
    with pytest.raises(ProviderError):
        list(runtime.stream_turn("Hi"))
    assert runtime.history == (UserMessage("Hi"),)


def test_single_tool_executes_once_and_requests_final_response(tmp_path):
    runtime, tool, _ = build_runtime(tmp_path, [tool_response(), plain_response("done")])
    assert list(runtime.stream_turn("echo")) == ["done"]
    assert tool.calls == [{"text": "hi"}]
    assert len(runtime._provider.calls) == 2
    assert runtime._provider.calls[1][1] == ()
    assert isinstance(runtime.history[1], AssistantMessage)
    assert isinstance(runtime.history[2], ToolResultsMessage)
    assert runtime.history[-1] == AssistantMessage("done", {"output": "done"})


@pytest.mark.parametrize("arguments", ['{"text":', "[]", '"text"'])
def test_invalid_arguments_are_fed_back_without_execution(tmp_path, arguments):
    runtime, tool, _ = build_runtime(tmp_path, [tool_response(arguments), plain_response("invalid")])
    assert list(runtime.stream_turn("bad")) == ["invalid"]
    assert tool.calls == []
    feedback = runtime.history[2].results[0]
    assert feedback.call_id == "call-1"
    assert feedback.result.error.code == "invalid_tool_arguments"


def test_multiple_tool_calls_are_all_rejected(tmp_path):
    response = [
        *tool_response(slot=0, call_id="one")[:-1],
        *tool_response(slot=1, call_id="two")[:-1],
        ResponseCompleted({"two_tools": True}),
    ]
    runtime, tool, _ = build_runtime(tmp_path, [response, plain_response("limited")])
    assert list(runtime.stream_turn("two")) == ["limited"]
    assert tool.calls == []
    results = runtime.history[2].results
    assert [item.call_id for item in results] == ["one", "two"]
    assert {item.result.error.code for item in results} == {"multiple_tool_calls"}


def test_second_tool_call_exhausts_budget_without_third_request(tmp_path):
    runtime, tool, interaction = build_runtime(tmp_path, [tool_response(), [TextDelta("thinking"), *tool_response(call_id="again")]])
    assert list(runtime.stream_turn("loop")) == ["thinking"]
    assert tool.calls == [{"text": "hi"}]
    assert interaction.budget_events == 1
    assert len(runtime._provider.calls) == 2
    assert len(runtime.history) == 3


def test_missing_completed_event_is_rejected(tmp_path):
    runtime, _, _ = build_runtime(tmp_path, [[TextDelta("partial")]])
    with pytest.raises(ProviderError, match="without a completed event"):
        list(runtime.stream_turn("Hi"))
    assert runtime.history == (UserMessage("Hi"),)


def test_e2e_read_file_executes_and_feeds_result_back(tmp_path):
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    provider = FakeProvider(
        [
            tool_response('{"path":"note.txt"}', name="read_file"),
            plain_response("The file says hello."),
        ]
    )
    registry = create_default_registry()
    runtime = ChatRuntime(provider, registry, ToolExecutor(registry, Workspace(tmp_path)))

    assert list(runtime.stream_turn("read note.txt")) == ["The file says hello."]
    result = runtime.history[2].results[0].result
    assert result.status == "success"
    assert result.data["content"] == "hello"


def test_e2e_write_file_rejection_has_no_side_effect(tmp_path):
    provider = FakeProvider(
        [
            tool_response('{"path":"new.txt","content":"hello"}', name="write_file"),
            plain_response("Not written."),
        ]
    )
    registry = create_default_registry()
    runtime = ChatRuntime(provider, registry, ToolExecutor(registry, Workspace(tmp_path)))

    assert list(runtime.stream_turn("write a file")) == ["Not written."]
    assert runtime.history[2].results[0].result.status == "rejected"
    assert not (tmp_path / "new.txt").exists()


def test_e2e_workspace_escape_is_structured_and_external_file_unchanged(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-secret.txt"
    outside.write_text("secret", encoding="utf-8")
    provider = FakeProvider(
        [
            tool_response('{"path":"../' + outside.name + '"}', name="read_file"),
            plain_response("Access denied."),
        ]
    )
    registry = create_default_registry()
    runtime = ChatRuntime(provider, registry, ToolExecutor(registry, Workspace(tmp_path)))

    assert list(runtime.stream_turn("read outside")) == ["Access denied."]
    assert runtime.history[2].results[0].result.error.code == "path_outside_workspace"
    assert outside.read_text(encoding="utf-8") == "secret"
