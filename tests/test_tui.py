from io import StringIO
from pathlib import Path

from mewcode.cli import main
from mewcode.config import LLMConfig
from mewcode.errors import ConfigError, MewCodeError
from mewcode.runtime import ChatRuntime
from mewcode.tui import ChatApp


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
        def stream_chat(self, messages):
            yield "ok"

    monkeypatch.setattr("mewcode.cli.create_provider", lambda loaded_config: FakeProvider())

    stdout = StringIO()
    code = main(config_path=config_path, stdin=StringIO("Hi\nexit\n"), stdout=stdout, stderr=StringIO())

    assert code == 0
    assert "╰─ assistant" in stdout.getvalue()
    assert "ok" in stdout.getvalue()


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

        def stream_chat(self, messages):
            self.calls.append(tuple(messages))
            yield f"reply-{len(self.calls)}"

    provider = RecordingProvider()
    runtime = ChatRuntime(provider)
    app = ChatApp(runtime, config(), input_stream=StringIO("one\ntwo\nexit\n"), output_stream=TrackingOutput())

    assert app.run() == 0

    assert len(provider.calls) == 2
    second_call = provider.calls[1]
    assert [message.content for message in second_call] == ["one", "reply-1", "two"]
