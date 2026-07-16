import json
from io import StringIO
from pathlib import Path

import pytest

from mewcode.agent import AgentSession
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.messages import UserMessage
from mewcode.providers.base import (
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
)
from mewcode.tools.base import (
    ConfirmationPreview,
    PreparedToolAction,
    ToolAccess,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from mewcode.tools.defaults import create_default_registry
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace
from mewcode.tui.plain import PlainChatApp


class TrackingOutput(StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        super().flush()


class AsciiOutput(TrackingOutput):
    @property
    def encoding(self):
        return "ascii"


class ScriptedProvider:
    def __init__(self, scripts=()) -> None:
        self.scripts = iter(scripts)
        self.calls = []
        self.close_calls = 0

    async def stream_response(
        self, history, tools, *, instructions, cancellation
    ):
        self.calls.append((tuple(history), tuple(tools), instructions))
        for event in next(self.scripts):
            cancellation.raise_if_cancelled()
            if isinstance(event, BaseException):
                raise event
            yield event

    async def aclose(self):
        self.close_calls += 1


class ConfirmingTool:
    manages_own_timeout = False
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True
    definition = ToolDefinition(
        "write_test",
        "write test data",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )

    def __init__(self) -> None:
        self.executed = False

    async def prepare(self, arguments, context):
        return PreparedToolAction(
            {},
            ConfirmationPreview(
                "write",
                "Write secret test data",
                "target secret location",
            ),
        )

    async def execute(self, action, context):
        self.executed = True
        return ToolResult(status="success")


class CountingReadTool:
    manages_own_timeout = False
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False
    definition = ToolDefinition(
        "read_test",
        "read test data",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )

    def __init__(self) -> None:
        self.executions = 0

    async def prepare(self, arguments, context):
        return PreparedToolAction({}, None)

    async def execute(self, action, context):
        self.executions += 1
        return ToolResult(status="success")


def config(protocol="openai"):
    return LLMConfig(
        name="test",
        protocol=protocol,
        model="model",
        base_url="https://example.com/v1",
        api_key="secret",
    )


def completed(text: str):
    return [ProviderTextDelta(text), ProviderResponseCompleted({"text": text})]


def tool_response(call_id: str, name: str, arguments: dict):
    return [
        ProviderToolCallDelta(
            0,
            call_id_delta=call_id,
            name_delta=name,
            arguments_delta=json.dumps(arguments),
        ),
        ProviderResponseCompleted({"tool": name}),
    ]


def build_session(
    tmp_path: Path,
    provider,
    *,
    tool=None,
):
    registry = ToolRegistry()
    if tool is not None:
        registry.register(tool)
    executor = ToolExecutor(
        registry,
        Workspace(tmp_path),
        secrets=("secret",),
    )
    return AgentSession(provider, registry, executor)


def build_default_session(tmp_path: Path, provider):
    registry = create_default_registry()
    executor = ToolExecutor(
        registry,
        Workspace(tmp_path),
        secrets=("secret",),
    )
    return AgentSession(provider, registry, executor)


@pytest.mark.asyncio
async def test_plain_events_progress_stop_reason_and_recovery(tmp_path: Path):
    provider = ScriptedProvider(
        [completed("Hello"), [ProviderError("temporary failure")], completed("Back")]
    )
    output = TrackingOutput()
    app = PlainChatApp(
        build_session(tmp_path, provider),
        config(),
        input_stream=StringIO("Hi\nfail\nagain\nexit\n"),
        output_stream=output,
    )

    assert await app.run() == 0

    text = output.getvalue()
    assert "› Hi" in text
    assert "[UPLINKING round 1/10]" in text
    assert "◆ Hello" in text
    assert "[COMPLETED]" in text
    assert "ERROR: The model provider stopped because of an error." in text
    assert "temporary failure" not in text
    assert "[PROVIDER ERROR]" in text
    assert "◆ Back" in text
    assert "assistant" not in text.lower()
    assert output.flush_count >= 3


@pytest.mark.asyncio
async def test_plain_input_header_exit_and_eof(tmp_path: Path):
    provider = ScriptedProvider()
    output = TrackingOutput()
    app = PlainChatApp(
        build_session(tmp_path, provider),
        config(),
        input_stream=StringIO("\nquit\n"),
        output_stream=output,
    )

    assert await app.run() == 0
    assert provider.calls == []
    assert "( o.o )" in output.getvalue()
    assert "MEWCODE // CYBER TERMINAL" in output.getvalue()
    assert "Bye." in output.getvalue()

    eof = PlainChatApp(
        build_session(tmp_path, ScriptedProvider()),
        config(),
        input_stream=StringIO(""),
        output_stream=StringIO(),
    )
    assert await eof.run() == 0


@pytest.mark.asyncio
async def test_plain_ascii_output_has_no_unicode_control_sequences(tmp_path: Path):
    output = AsciiOutput()
    app = PlainChatApp(
        build_session(tmp_path, ScriptedProvider([completed("same")])),
        config("anthropic"),
        input_stream=StringIO("Hi\nquit\n"),
        output_stream=output,
    )

    assert await app.run() == 0
    output.getvalue().encode("ascii")
    assert "> Hi" in output.getvalue()
    assert "* same" in output.getvalue()


@pytest.mark.asyncio
async def test_plain_confirmation_uses_safe_preview_and_run_control(tmp_path: Path):
    tool = ConfirmingTool()
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-1",
                    name_delta="write_test",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}),
            ],
            completed("done"),
        ]
    )
    output = TrackingOutput()
    app = PlainChatApp(
        build_session(tmp_path, provider, tool=tool),
        config(),
        input_stream=StringIO("task\nyes\nexit\n"),
        output_stream=output,
    )

    assert await app.run() == 0
    text = output.getvalue()
    assert tool.executed is True
    assert "[redacted]" in text
    assert "secret" not in text
    assert "[CONFIRMATION APPROVED]" in text
    assert "[TOOL write_test] success" in text


@pytest.mark.asyncio
async def test_plain_invalid_command_and_history_recover_for_next_input(tmp_path: Path):
    provider = ScriptedProvider([completed("one"), completed("two")])
    session = build_session(tmp_path, provider)
    output = TrackingOutput()
    app = PlainChatApp(
        session,
        config(),
        input_stream=StringIO("/do\none\ntwo\nexit\n"),
        output_stream=output,
    )

    assert await app.run() == 0
    assert "[INVALID REQUEST]" in output.getvalue()
    assert len(provider.calls) == 2
    assert [message.content for message in provider.calls[1][0]] == [
        "one",
        "one",
        "two",
    ]


@pytest.mark.asyncio
async def test_e2e_autonomous_task_reads_searches_edits_and_validates(
    tmp_path: Path,
):
    target = tmp_path / "sample.txt"
    target.write_text("old\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            tool_response("call-read", "read_file", {"path": "sample.txt"}),
            tool_response(
                "call-search",
                "search_code",
                {"query": "old", "path_pattern": "*.txt"},
            ),
            tool_response(
                "call-edit",
                "edit_file",
                {
                    "path": "sample.txt",
                    "old_text": "old",
                    "new_text": "new",
                },
            ),
            tool_response(
                "call-command",
                "run_command",
                {"command": 'test "$(cat sample.txt)" = new'},
            ),
            completed("validated final answer"),
        ]
    )
    output = TrackingOutput()
    app = PlainChatApp(
        build_default_session(tmp_path, provider),
        config(),
        input_stream=StringIO("update and validate\nyes\nyes\nexit\n"),
        output_stream=output,
    )

    assert await app.run() == 0

    text = output.getvalue()
    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(provider.calls) == 5
    assert [
        provider.calls[index][0][-1].results[0].name
        for index in range(1, 5)
    ] == ["read_file", "search_code", "edit_file", "run_command"]
    assert text.count("[CONFIRMATION APPROVED]") == 2
    assert "[TOOL read_file] success" in text
    assert "[TOOL search_code] success" in text
    assert "[TOOL edit_file] success" in text
    assert "[TOOL run_command] success" in text
    assert "validated final answer" in text
    assert "[COMPLETED]" in text


@pytest.mark.asyncio
async def test_e2e_plan_do_reads_then_confirms_write_and_consumes_plan(
    tmp_path: Path,
):
    target = tmp_path / "plan.txt"
    target.write_text("old plan\n", encoding="utf-8")
    provider = ScriptedProvider(
        [
            tool_response("call-plan-read", "read_file", {"path": "plan.txt"}),
            completed("Replace old plan with executed plan."),
            tool_response(
                "call-do-edit",
                "edit_file",
                {
                    "path": "plan.txt",
                    "old_text": "old plan",
                    "new_text": "executed plan",
                },
            ),
            completed("plan execution complete"),
        ]
    )
    session = build_default_session(tmp_path, provider)
    output = TrackingOutput()
    app = PlainChatApp(
        session,
        config(),
        input_stream=StringIO(
            "/plan inspect and update plan.txt\n/do\nyes\n/do\nexit\n"
        ),
        output_stream=output,
    )

    assert await app.run() == 0

    read_only = ["read_file", "glob_files", "search_code"]
    all_tools = [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "glob_files",
        "search_code",
    ]
    assert target.read_text(encoding="utf-8") == "executed plan\n"
    assert len(provider.calls) == 4
    assert all(
        [definition.name for definition in provider.calls[index][1]] == read_only
        for index in (0, 1)
    )
    assert all(
        [definition.name for definition in provider.calls[index][1]] == all_tools
        for index in (2, 3)
    )
    assert provider.calls[0][2] == provider.calls[1][2]
    assert provider.calls[2][2] == provider.calls[3][2]
    assert provider.calls[0][2] != provider.calls[2][2]
    assert provider.calls[2][0][-1].content == (
        "Replace old plan with executed plan."
    )
    assert session.current_plan is not None
    assert session.current_plan.status.value == "completed"
    assert output.getvalue().count("[CONFIRMATION APPROVED]") == 1
    assert "[INVALID REQUEST]" in output.getvalue()


@pytest.mark.asyncio
async def test_e2e_stream_error_recovery_keeps_partial_text_without_calling_tool(
    tmp_path: Path,
):
    tool = CountingReadTool()
    provider = ScriptedProvider(
        [
            [
                ProviderTextDelta("partial visible"),
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-incomplete",
                    name_delta="read_test",
                    arguments_delta="{}",
                ),
                ProviderError("stream failed with secret"),
            ],
            completed("recovered answer"),
        ]
    )
    output = TrackingOutput()
    app = PlainChatApp(
        build_session(tmp_path, provider, tool=tool),
        config(),
        input_stream=StringIO("first\nsecond\nexit\n"),
        output_stream=output,
    )

    assert await app.run() == 0

    text = output.getvalue()
    assert tool.executions == 0
    assert len(provider.calls) == 2
    assert [message.content for message in provider.calls[1][0]] == [
        "first",
        "second",
    ]
    assert "partial visible" in text
    assert "stream failed with secret" not in text
    assert "[PROVIDER ERROR]" in text
    assert "recovered answer" in text
    assert "[COMPLETED]" in text


@pytest.mark.asyncio
async def test_e2e_restart_drops_plan_and_keeps_plain_chat_and_quit(
    tmp_path: Path,
):
    first_provider = ScriptedProvider([completed("saved transient plan")])
    first_session = build_session(tmp_path, first_provider)
    first = PlainChatApp(
        first_session,
        config(),
        input_stream=StringIO("/plan inspect\nexit\n"),
        output_stream=StringIO(),
    )
    assert await first.run() == 0
    assert first_session.current_plan is not None

    restarted_provider = ScriptedProvider([completed("fresh chat works")])
    restarted_session = build_session(tmp_path, restarted_provider)
    restarted_output = StringIO()
    restarted = PlainChatApp(
        restarted_session,
        config(),
        input_stream=StringIO("/do\nhello\nquit\n"),
        output_stream=restarted_output,
    )

    assert await restarted.run() == 0

    text = restarted_output.getvalue()
    assert restarted_session.current_plan is None
    assert len(restarted_provider.calls) == 1
    assert restarted_provider.calls[0][0] == (UserMessage("hello"),)
    assert "[INVALID REQUEST]" in text
    assert "fresh chat works" in text
    assert "[COMPLETED]" in text
    assert "Bye." in text
