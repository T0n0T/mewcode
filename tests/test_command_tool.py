from pathlib import Path

from mewcode.providers.base import ToolCall
from mewcode.tools.base import ToolOutputLimits
from mewcode.tools.command import RunCommandTool
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class Interaction:
    def __init__(self, approved=True):
        self.approved = approved
        self.previews = []

    def tool_started(self, call):
        pass

    def confirm(self, preview):
        self.previews.append(preview)
        return self.approved

    def tool_finished(self, call, result):
        pass

    def tool_budget_exhausted(self):
        pass


def executor(tmp_path: Path, interaction=None, limits=None):
    registry = ToolRegistry()
    registry.register(RunCommandTool())
    return ToolExecutor(registry, Workspace(tmp_path), interaction or Interaction(), limits=limits)


def test_prepare_preview_and_rejection(tmp_path: Path):
    interaction = Interaction(approved=False)
    result = executor(tmp_path, interaction).execute(
        ToolCall("1", "run_command", {"command": "touch nope"})
    )

    assert result.status == "rejected"
    assert interaction.previews[0].details == "touch nope"
    assert not (tmp_path / "nope").exists()


def test_execute_shell_syntax_cwd_exit_code_and_truncated(tmp_path: Path):
    result = executor(tmp_path).execute(
        ToolCall(
            "1",
            "run_command",
            {"command": "pwd; printf abcdef | cut -c1-3; false", "timeout_seconds": 5},
        )
    )

    assert result.status == "error"
    assert str(tmp_path) in result.data["stdout"]
    assert "abc" in result.data["stdout"]
    assert result.data["exit_code"] != 0

    truncated = executor(
        tmp_path,
        limits=ToolOutputLimits(command_characters=3),
    ).execute(ToolCall("2", "run_command", {"command": "printf abcdef"}))
    assert truncated.data["stdout"] == "abc"
    assert truncated.truncation.original == 6


def test_timeout_validation_and_encoding(tmp_path: Path):
    invalid = executor(tmp_path).execute(
        ToolCall("1", "run_command", {"command": "echo ok", "timeout_seconds": 301})
    )
    assert invalid.error.code == "invalid_arguments"

    timed_out = executor(tmp_path).execute(
        ToolCall("2", "run_command", {"command": "sleep 2", "timeout_seconds": 0.1})
    )
    assert timed_out.status == "timeout"

    bad = executor(tmp_path).execute(
        ToolCall("3", "run_command", {"command": "printf '\\377'"})
    )
    assert bad.error.code == "invalid_encoding"


def test_command_can_use_timeout_longer_than_ordinary_tool_deadline(tmp_path: Path):
    now = [0.0]

    class Process:
        returncode = 0

        def communicate(self, timeout=None):
            assert timeout == 60
            now[0] = 45.0
            return b"done", b""

    registry = ToolRegistry()
    registry.register(RunCommandTool(popen=lambda *args, **kwargs: Process()))
    result = ToolExecutor(
        registry,
        Workspace(tmp_path),
        Interaction(),
        clock=lambda: now[0],
    ).execute(
        ToolCall(
            "1",
            "run_command",
            {"command": "long operation", "timeout_seconds": 60},
        )
    )

    assert result.status == "success"
    assert result.data["stdout"] == "done"
