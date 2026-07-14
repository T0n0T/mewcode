import asyncio
import os
from pathlib import Path

import pytest

from mewcode.cancellation import CancellationToken
from mewcode.tools.base import ToolCall, ToolOutputLimits
from mewcode.tools.command import RunCommandTool
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


def executor(tmp_path: Path, tool=None, limits=None):
    registry = ToolRegistry()
    registry.register(tool or RunCommandTool())
    return ToolExecutor(registry, Workspace(tmp_path), limits=limits)


async def execute(
    tmp_path: Path,
    call: ToolCall,
    *,
    approved: bool = True,
    tool=None,
    limits=None,
    cancellation=None,
):
    previews = []

    async def confirm(_call, preview):
        previews.append(preview)
        return approved

    result = await executor(tmp_path, tool, limits).execute(
        call,
        cancellation=cancellation or CancellationToken(),
        confirm=confirm,
    )
    return result, previews


@pytest.mark.asyncio
async def test_prepare_preview_and_rejection(tmp_path: Path):
    result, previews = await execute(
        tmp_path,
        ToolCall("1", "run_command", {"command": "touch nope"}),
        approved=False,
    )

    assert result.status == "rejected"
    assert previews[0].details == "touch nope"
    assert not (tmp_path / "nope").exists()


@pytest.mark.asyncio
async def test_execute_shell_syntax_cwd_exit_code_and_truncated(tmp_path: Path):
    result, _ = await execute(
        tmp_path,
        ToolCall(
            "1",
            "run_command",
            {"command": "pwd; printf abcdef | cut -c1-3; false", "timeout_seconds": 5},
        ),
    )

    assert result.status == "error"
    assert str(tmp_path) in result.data["stdout"]
    assert "abc" in result.data["stdout"]
    assert result.data["exit_code"] != 0

    truncated, _ = await execute(
        tmp_path,
        ToolCall("2", "run_command", {"command": "printf abcdef"}),
        limits=ToolOutputLimits(command_characters=3),
    )
    assert truncated.data["stdout"] == "abc"
    assert truncated.truncation.original == 6


@pytest.mark.asyncio
async def test_timeout_validation_and_encoding(tmp_path: Path):
    invalid, _ = await execute(
        tmp_path,
        ToolCall("1", "run_command", {"command": "echo ok", "timeout_seconds": 301}),
    )
    assert invalid.error.code == "invalid_arguments"

    timed_out, _ = await execute(
        tmp_path,
        ToolCall("2", "run_command", {"command": "sleep 2", "timeout_seconds": 0.05}),
    )
    assert timed_out.status == "timeout"

    bad, _ = await execute(
        tmp_path,
        ToolCall("3", "run_command", {"command": "printf '\\377'"}),
    )
    assert bad.error.code == "invalid_encoding"


@pytest.mark.asyncio
async def test_command_can_use_timeout_longer_than_ordinary_tool_deadline(
    tmp_path: Path,
):
    class Process:
        returncode = 0
        pid = 123

        async def communicate(self):
            return b"done", b""

    async def create_process(*_args, **_kwargs):
        return Process()

    result, _ = await execute(
        tmp_path,
        ToolCall(
            "1",
            "run_command",
            {"command": "long operation", "timeout_seconds": 60},
        ),
        tool=RunCommandTool(create_process=create_process),
    )

    assert result.status == "success"
    assert result.data["stdout"] == "done"


@pytest.mark.asyncio
async def test_cancellation_terminates_active_process_group(tmp_path: Path):
    if os.name != "posix":
        pytest.skip("Process group assertion is POSIX-specific.")

    token = CancellationToken()
    tool = RunCommandTool()
    task = asyncio.create_task(
        execute(
            tmp_path,
            ToolCall("1", "run_command", {"command": "sleep 30"}),
            tool=tool,
            cancellation=token,
        )
    )

    while tool.active_process is None:
        await asyncio.sleep(0)
    process = tool.active_process
    token.cancel()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    assert process.returncode is not None
