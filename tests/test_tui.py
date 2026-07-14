from io import StringIO
from pathlib import Path

from mewcode.cli import main
from mewcode.config import LLMConfig
from mewcode.errors import ConfigError, MewCodeError
from mewcode.providers.base import ResponseCompleted, TextDelta, ToolCall
from mewcode.runtime import ChatRuntime
from mewcode.tools.base import ConfirmationPreview, ToolErrorInfo, ToolResult
from mewcode.tui import ChatApp, TerminalToolInteraction


class TrackingOutput(StringIO):
    def __init__(self):
        super().__init__()
        self.flush_count = 0

    def flush(self):
        self.flush_count += 1
        super().flush()


class FakeRuntime:
    def __init__(self, chunks=None, error: MewCodeError | None = None):
        self.chunks = chunks or ["Hel", "lo"]
        self.error = error
        self.inputs = []

    def stream_turn(self, user_text):
        self.inputs.append(user_text)
        if self.error is not None:
            raise self.error
        yield from self.chunks


def config():
    return LLMConfig(
        name="test",
        protocol="openai",
        model="model",
        base_url="https://example.com/v1",
        api_key="secret",
    )


def test_tui_streams_chunks_and_flushes():
    runtime = FakeRuntime(chunks=["Hel", "lo"])
    output = TrackingOutput()
    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("Hi\nexit\n"),
        output_stream=output,
    )

    assert app.run() == 0

    assert runtime.inputs == ["Hi"]
    assert "╰─ assistant" in output.getvalue()
    assert "Hello" in output.getvalue()
    assert output.flush_count >= 2


def test_tui_renders_claude_like_header_with_cat():
    runtime = FakeRuntime()
    output = TrackingOutput()
    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("exit\n"),
        output_stream=output,
    )

    assert app.run() == 0

    text = output.getvalue()
    assert "/\\_/\\" in text
    assert "MewCode" in text
    assert "openai" in text
    assert "╭─ you" in text


def test_tui_ignores_empty_input():
    runtime = FakeRuntime()
    output = TrackingOutput()
    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("\nquit\n"),
        output_stream=output,
    )

    assert app.run() == 0

    assert runtime.inputs == []


def test_tui_exit_commands_end_session():
    for command in ("exit", "quit"):
        runtime = FakeRuntime()
        output = TrackingOutput()
        app = ChatApp(
            runtime,  # type: ignore[arg-type]
            config(),
            input_stream=StringIO(f"{command}\n"),
            output_stream=output,
        )

        assert app.run() == 0
        assert "Bye." in output.getvalue()


def test_tui_ctrl_d_ends_session():
    runtime = FakeRuntime()
    output = TrackingOutput()
    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO(""),
        output_stream=output,
    )

    assert app.run() == 0


def test_tui_prints_runtime_error_and_continues():
    runtime = FakeRuntime(error=MewCodeError("temporary failure"))
    output = TrackingOutput()
    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        config(),
        input_stream=StringIO("Hi\nexit\n"),
        output_stream=output,
    )

    assert app.run() == 0

    text = output.getvalue()
    assert "Error: temporary failure" in text
    assert "Bye." in text


def test_cli_main_returns_nonzero_for_startup_config_error(tmp_path: Path):
    stderr = StringIO()

    code = main(config_path=tmp_path / "missing.yaml", stdin=StringIO(""), stdout=StringIO(), stderr=stderr)

    assert code == 1
    assert "Config file not found" in stderr.getvalue()


def test_cli_main_wires_runtime_and_tui(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
name: test
protocol: openai
model: model
base_url: https://example.com/v1
api_key: secret
""",
        encoding="utf-8",
    )

    class FakeProvider:
        def stream_response(self, history, tools, cancellation):
            yield TextDelta("ok")
            yield ResponseCompleted([])

    monkeypatch.setattr("mewcode.cli.create_provider", lambda loaded_config: FakeProvider())

    stdout = StringIO()
    code = main(config_path=config_path, stdin=StringIO("Hi\nexit\n"), stdout=stdout, stderr=StringIO())

    assert code == 0
    assert "╰─ assistant" in stdout.getvalue()
    assert "ok" in stdout.getvalue()


def test_cli_fixes_current_directory_as_workspace(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "name: test\nprotocol: openai\nmodel: model\nbase_url: https://example.com/v1\napi_key: secret\n",
        encoding="utf-8",
    )
    workdir = tmp_path / "workspace"
    workdir.mkdir()
    observed = {}

    class FakeProvider:
        def stream_response(self, history, tools, cancellation):
            observed["tools"] = [tool.name for tool in tools]
            yield TextDelta("ok")
            yield ResponseCompleted([])

    real_workspace = __import__("mewcode.tools.workspace", fromlist=["Workspace"]).Workspace

    def recording_workspace(root):
        observed["root"] = root
        return real_workspace(root)

    monkeypatch.chdir(workdir)
    monkeypatch.setattr("mewcode.cli.Workspace", recording_workspace)
    monkeypatch.setattr("mewcode.cli.create_provider", lambda loaded_config: FakeProvider())
    code = main(config_path=config_path, stdin=StringIO("Hi\nexit\n"), stdout=StringIO(), stderr=StringIO())

    assert code == 0
    assert observed["root"] == workdir
    assert observed["tools"] == [
        "read_file", "write_file", "edit_file", "run_command", "glob_files", "search_code"
    ]


def test_tui_uses_uniform_runtime_interface_for_anthropic_config():
    runtime = FakeRuntime(chunks=["same"])
    anthropic_config = LLMConfig(
        name="claude-test",
        protocol="anthropic",
        model="claude",
        base_url="https://example.com/v1",
        api_key="secret",
    )
    output = TrackingOutput()

    app = ChatApp(
        runtime,  # type: ignore[arg-type]
        anthropic_config,
        input_stream=StringIO("Hi\nquit\n"),
        output_stream=output,
    )

    assert app.run() == 0
    assert "╰─ assistant" in output.getvalue()
    assert "same" in output.getvalue()


def test_end_to_end_history_with_fake_provider():
    class RecordingProvider:
        def __init__(self):
            self.calls = []

        def stream_response(self, history, tools, cancellation):
            self.calls.append(tuple(history))
            reply = f"reply-{len(self.calls)}"
            yield TextDelta(reply)
            yield ResponseCompleted([])

    provider = RecordingProvider()
    from mewcode.tools import Workspace, create_default_registry
    from mewcode.tools.executor import ToolExecutor

    registry = create_default_registry()
    runtime = ChatRuntime(provider, registry, ToolExecutor(registry, Workspace(Path.cwd())))
    app = ChatApp(runtime, config(), input_stream=StringIO("one\ntwo\nexit\n"), output_stream=TrackingOutput())

    assert app.run() == 0

    assert len(provider.calls) == 2
    second_call = provider.calls[1]
    assert [message.content for message in second_call] == ["one", "reply-1", "two"]


def test_terminal_tool_status_hides_results_and_sensitive_arguments():
    output = TrackingOutput()
    interaction = TerminalToolInteraction(StringIO(""), output, secrets=("secret",))
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
    assert "read_file" in text
    assert "notes.txt" in text
    assert "hidden" not in text
    assert "secret" not in text
    assert "[redacted]" in text


def test_terminal_confirmation_shows_redacted_preview_and_accepts_only_yes():
    for answer, expected in (("yes\n", True), ("Y\n", True), ("no\n", False), ("\n", False), ("", False)):
        output = TrackingOutput()
        interaction = TerminalToolInteraction(StringIO(answer), output, secrets=("secret",))
        approved = interaction.confirm(
            ConfirmationPreview("command", "Run secret command", "echo secret")
        )
        assert approved is expected
        assert "[redacted]" in output.getvalue()
        assert "secret" not in output.getvalue()


def test_terminal_reports_tool_budget_exhaustion():
    output = TrackingOutput()
    TerminalToolInteraction(StringIO(), output).tool_budget_exhausted()
    assert "tool limit" in output.getvalue().lower()
