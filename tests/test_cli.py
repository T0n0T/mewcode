from io import StringIO
from pathlib import Path

import mewcode.cli as cli
from mewcode.providers.base import ResponseCompleted, TextDelta
from mewcode.tui import TerminalMode
from mewcode.tui.interaction import TuiToolInteraction


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
    def stream_response(self, history, tools, cancellation):
        yield TextDelta("ok")
        yield ResponseCompleted([])


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


def test_cli_injected_streams_use_plain_mode(monkeypatch, tmp_path: Path):
    config_path = write_config(tmp_path)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: FakeProvider())
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


def test_cli_fixes_current_directory_as_workspace(monkeypatch, tmp_path: Path):
    config_path = write_config(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    observed = {}

    class RecordingProvider:
        def stream_response(self, history, tools, cancellation):
            observed["tools"] = [tool.name for tool in tools]
            yield TextDelta("ok")
            yield ResponseCompleted([])

    real_workspace = cli.Workspace

    def recording_workspace(root):
        observed["root"] = root
        return real_workspace(root)

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli, "Workspace", recording_workspace)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: RecordingProvider())

    code = cli.main(
        config_path=config_path,
        stdin=StringIO("Hi\nexit\n"),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert code == 0
    assert observed["root"] == workspace
    assert observed["tools"] == [
        "read_file",
        "write_file",
        "edit_file",
        "run_command",
        "glob_files",
        "search_code",
    ]


def test_cli_fullscreen_mode_wires_bridge_runtime_and_metadata(
    monkeypatch,
    tmp_path: Path,
):
    config_path = write_config(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    observed = {}

    class FakeFullscreenApp:
        def __init__(
            self,
            runtime,
            metadata,
            bridge,
            *,
            unicode_output,
        ):
            observed["runtime"] = runtime
            observed["metadata"] = metadata
            observed["bridge"] = bridge
            observed["unicode_output"] = unicode_output

        def run(self):
            return 23

    monkeypatch.chdir(workspace)
    monkeypatch.setattr(cli, "create_provider", lambda loaded: object())
    monkeypatch.setattr(
        cli,
        "detect_terminal_mode",
        lambda input_stream, output_stream: TerminalMode.FULLSCREEN,
        raising=False,
    )
    monkeypatch.setattr(
        cli,
        "CyberpunkChatApp",
        FakeFullscreenApp,
        raising=False,
    )

    code = cli.main(
        config_path=config_path,
        stdin=StringIO(),
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert code == 23
    assert observed["metadata"].workspace == workspace
    assert observed["metadata"].model == "model"
    assert observed["unicode_output"] is True
    interaction = observed["runtime"]._executor.interaction
    assert isinstance(interaction, TuiToolInteraction)
    assert interaction.bridge is observed["bridge"]
