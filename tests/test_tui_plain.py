from io import StringIO
from pathlib import Path

import pytest

from mewcode.agent import AgentSession
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
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
    assert "ERROR: temporary failure" in text
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
