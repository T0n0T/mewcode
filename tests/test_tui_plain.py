from io import StringIO
from pathlib import Path

import pytest

from mewcode.config import LLMConfig
from mewcode.errors import MewCodeError
from mewcode.providers.base import ResponseCompleted, TextDelta, ToolCall
from mewcode.runtime import ChatRuntime
from mewcode.tools import Workspace, create_default_registry
from mewcode.tools.base import ConfirmationPreview, ToolErrorInfo, ToolResult
from mewcode.tools.executor import ToolExecutor
from mewcode.tui.plain import PlainChatApp, PlainToolInteraction
from mewcode.turns import (
    TurnCompleted,
    TurnPhase,
    TurnPhaseChanged,
    TurnTextDelta,
)


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


class FakeRuntime:
    def __init__(self, chunks=None, error: MewCodeError | None = None):
        self.chunks = chunks or ["Hel", "lo"]
        self.error = error
        self.inputs = []
        self.cancellations = []

    def stream_turn(self, user_text, cancellation):
        self.inputs.append(user_text)
        self.cancellations.append(cancellation)
        yield TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
        if self.error is not None:
            raise self.error
        for chunk in self.chunks:
            yield TurnTextDelta(chunk)
        yield TurnCompleted()


def config(protocol="openai"):
    return LLMConfig(
        name="test",
        protocol=protocol,
        model="model",
        base_url="https://example.com/v1",
        api_key="secret",
    )


def test_plain_app_streams_events_without_assistant_label():
    runtime = FakeRuntime(chunks=["Hel", "lo"])
    output = TrackingOutput()
    app = PlainChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("Hi\nexit\n"),
        output_stream=output,
    )

    assert app.run() == 0

    text = output.getvalue()
    assert runtime.inputs == ["Hi"]
    assert "› Hi" in text
    assert "◆ [UPLINKING model]" in text
    assert "◆ Hello" in text
    assert "assistant" not in text.lower()
    assert output.flush_count >= 2


def test_plain_app_header_empty_input_exit_and_eof():
    runtime = FakeRuntime()
    output = TrackingOutput()
    app = PlainChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("\nquit\n"),
        output_stream=output,
    )

    assert app.run() == 0
    assert runtime.inputs == []
    assert "( o.o )" in output.getvalue()
    assert "MEWCODE // CYBER TERMINAL" in output.getvalue()
    assert "Bye." in output.getvalue()

    assert PlainChatApp(
        FakeRuntime(),  # type: ignore[arg-type]
        config(),
        input_stream=StringIO(""),
        output_stream=StringIO(),
    ).run() == 0


def test_plain_app_reports_error_and_continues():
    runtime = FakeRuntime(error=MewCodeError("temporary failure"))
    output = TrackingOutput()
    app = PlainChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("Hi\nexit\n"),
        output_stream=output,
    )

    assert app.run() == 0
    assert "ERROR: temporary failure" in output.getvalue()
    assert "Bye." in output.getvalue()


def test_plain_app_supports_anthropic_and_ascii_output():
    output = AsciiOutput()
    app = PlainChatApp(
        FakeRuntime(chunks=["same"]),  # type: ignore[arg-type]
        config("anthropic"),
        input_stream=StringIO("Hi\nquit\n"),
        output_stream=output,
    )

    assert app.run() == 0
    assert "> Hi" in output.getvalue()
    assert "* same" in output.getvalue()
    assert "›" not in output.getvalue()
    assert "◆" not in output.getvalue()


def test_plain_tool_status_hides_results_and_sensitive_arguments():
    output = TrackingOutput()
    interaction = PlainToolInteraction(StringIO(""), output, secrets=("secret",))
    call = ToolCall("1", "read_file", {"path": "notes.txt", "content": "secret body"})

    interaction.tool_started(call)
    interaction.tool_finished(call, ToolResult(status="success", data={"content": "hidden"}))
    interaction.tool_finished(
        call,
        ToolResult(
            status="error",
            error=ToolErrorInfo("failure", "bad secret", retryable=False),
        ),
    )

    text = output.getvalue()
    assert "EXECUTING read_file" in text
    assert "notes.txt" in text
    assert "hidden" not in text
    assert "secret" not in text
    assert "[redacted]" in text


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("yes\n", True), ("Y\n", True), ("no\n", False), ("\n", False), ("", False)],
)
def test_plain_confirmation_is_redacted_and_defaults_to_reject(answer, expected):
    output = TrackingOutput()
    interaction = PlainToolInteraction(StringIO(answer), output, secrets=("secret",))

    approved = interaction.confirm(
        ConfirmationPreview("command", "Run secret command", "echo secret")
    )

    assert approved is expected
    assert "[redacted]" in output.getvalue()
    assert "secret" not in output.getvalue()


def test_plain_reports_tool_budget_exhaustion():
    output = TrackingOutput()
    PlainToolInteraction(StringIO(), output).tool_budget_exhausted()
    assert "tool limit" in output.getvalue().lower()


def test_plain_app_preserves_runtime_history_across_turns():
    class RecordingProvider:
        def __init__(self):
            self.calls = []

        def stream_response(self, history, tools, cancellation):
            self.calls.append(tuple(history))
            yield TextDelta(f"reply-{len(self.calls)}")
            yield ResponseCompleted([])

    provider = RecordingProvider()
    registry = create_default_registry()
    runtime = ChatRuntime(
        provider,  # type: ignore[arg-type]
        registry,
        ToolExecutor(registry, Workspace(Path.cwd())),
    )
    app = PlainChatApp(
        runtime,
        config(),
        input_stream=StringIO("one\ntwo\nexit\n"),
        output_stream=TrackingOutput(),
    )

    assert app.run() == 0
    assert len(provider.calls) == 2
    assert [message.content for message in provider.calls[1]] == [
        "one",
        "reply-1",
        "two",
    ]
