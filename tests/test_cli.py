from io import StringIO
from pathlib import Path

import pytest

import mewcode.cli as cli
from mewcode.agent import AgentSession
from mewcode.providers.base import ProviderResponseCompleted, ProviderTextDelta
from mewcode.tui import TerminalMode


def write_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "name: test\n"
        "protocol: openai\n"
        "model: model\n"
        "base_url: https://example.com/v1\n"
        "api_key: secret\n",
        encoding="utf-8",
    )
    return config_path


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []
        self.close_calls = 0

    async def stream_response(
        self, history, tools, *, instructions, cancellation
    ):
        self.calls.append((tuple(history), tuple(tools), instructions))
        yield ProviderTextDelta("ok")
        yield ProviderResponseCompleted({"ok": True})

    async def aclose(self):
        self.close_calls += 1


def test_cli_main_returns_nonzero_for_startup_config_error(tmp_path: Path):
    stderr = StringIO()

    code = cli.main(
        config_path=tmp_path / "missing.yaml",
        stdin=StringIO(""),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert code == 1
    assert "Config file not found" in stderr.getvalue()


def test_cli_injected_streams_use_plain_async_main_and_close_once(
    monkeypatch, tmp_path: Path
):
    config_path = write_config(tmp_path)
    provider = FakeProvider()
    monkeypatch.setattr(cli, "create_provider", lambda loaded: provider)
    stdout = StringIO()

    code = cli.main(
        config_path=config_path,
        stdin=StringIO("Hi\nexit\n"),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert code == 0
    assert "◆ ok" in stdout.getvalue()
    assert "assistant" not in stdout.getvalue().lower()
    assert "\x1b" not in stdout.getvalue()
    assert provider.close_calls == 1


def test_cli_fixes_current_directory_as_workspace(monkeypatch, tmp_path: Path):
    config_path = write_config(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = FakeProvider()
    observed = {}
    real_workspace = cli.Workspace

    def recording_workspace(root):
        observed["root"] = root
        return real_workspace(root)

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli, "Workspace", recording_workspace)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: provider)

    code = cli.main(
        config_path=config_path,
        stdin=StringIO("Hi\nexit\n"),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert code == 0
    assert observed["root"] == workspace
    assert [definition.name for definition in provider.calls[0][1]] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "glob_files",
        "search_code",
    ]


@pytest.mark.asyncio
async def test_async_main_fullscreen_wires_session_and_uses_single_close(
    monkeypatch,
    tmp_path: Path,
):
    config_path = write_config(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    provider = FakeProvider()
    observed = {}

    class FakeFullscreenApp:
        def __init__(self, session, metadata, *, unicode_output):
            observed["session"] = session
            observed["metadata"] = metadata
            observed["unicode_output"] = unicode_output

        async def run_async(self):
            return 23

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: provider)
    monkeypatch.setattr(
        cli,
        "detect_terminal_mode",
        lambda input_stream, output_stream: TerminalMode.FULLSCREEN,
    )
    monkeypatch.setattr(cli, "CyberpunkChatApp", FakeFullscreenApp)

    code = await cli.async_main(
        config_path=config_path,
        stdin=StringIO(),
        stdout=StringIO(),
    )

    assert code == 23
    assert isinstance(observed["session"], AgentSession)
    assert observed["metadata"].workspace == workspace
    assert observed["metadata"].model == "model"
    assert observed["unicode_output"] is True
    assert provider.close_calls == 1


@pytest.mark.asyncio
async def test_async_main_closes_session_when_interface_fails(monkeypatch, tmp_path):
    config_path = write_config(tmp_path)
    provider = FakeProvider()

    class FailingPlainApp:
        def __init__(self, session, config, **kwargs):
            pass

        async def run(self):
            raise RuntimeError("interface failed")

    monkeypatch.setattr(cli, "create_provider", lambda loaded: provider)
    monkeypatch.setattr(cli, "PlainChatApp", FailingPlainApp)

    with pytest.raises(RuntimeError, match="interface failed"):
        await cli.async_main(
            config_path=config_path,
            stdin=StringIO(),
            stdout=StringIO(),
        )

    assert provider.close_calls == 1
