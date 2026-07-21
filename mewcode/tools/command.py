from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from mewcode.errors import ToolEncodingError, ToolInputError
from mewcode.tools.base import (
    ConfirmationPreview,
    JSONValue,
    PreparedToolAction,
    ToolAccess,
    ToolContext,
    ToolDefinition,
    ToolErrorInfo,
    ToolExecutionPolicy,
    ToolResult,
)


@dataclass(frozen=True)
class _CommandState:
    command: str
    timeout_seconds: float


class RunCommandTool:
    definition = ToolDefinition(
        name="run_command",
        description=(
            "Run a complete shell command in the workspace after user confirmation. "
            "Use this tool only when no dedicated MewCode tool fits the operation; do "
            "not use shell commands as substitutes for read_file, glob_files, "
            "search_code, write_file, or edit_file."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "minLength": 1},
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 300,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    )
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True
    manages_own_timeout = True

    def __init__(
        self,
        *,
        create_process: Callable[..., Awaitable[Any]] = asyncio.create_subprocess_shell,
    ):
        self._create_process = create_process
        self.active_process: Any | None = None

    async def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
        context.cancellation.raise_if_cancelled()
        command = str(arguments["command"])
        if not command.strip():
            raise ToolInputError("invalid_command", "Command must not be empty.")
        timeout_seconds = float(arguments.get("timeout_seconds", 30))
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ToolInputError(
                "invalid_timeout",
                "timeout_seconds must be greater than 0 and no more than 300.",
            )
        return PreparedToolAction(
            dict(arguments),
            ConfirmationPreview("command", "Run shell command", command),
            _CommandState(command, timeout_seconds),
        )

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        state = action.state
        if not isinstance(state, _CommandState):
            raise RuntimeError("Invalid prepared command state.")
        context.cancellation.raise_if_cancelled()
        process_kwargs: dict[str, Any] = {
            "cwd": context.workspace.root,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if os.name == "posix":
            process_kwargs["start_new_session"] = True
        elif os.name == "nt":
            process_kwargs["creationflags"] = 0x00000200

        process = await self._create_process(state.command, **process_kwargs)
        self.active_process = process
        try:
            try:
                stdout_raw, stderr_raw = await asyncio.wait_for(
                    process.communicate(), timeout=state.timeout_seconds
                )
            except TimeoutError:
                await _terminate_process_group(process)
                stdout_raw, stderr_raw = await process.communicate()
                return ToolResult(
                    status="timeout",
                    data=_command_data(process, stdout_raw, stderr_raw),
                    error=ToolErrorInfo(
                        "timeout",
                        f"Command exceeded {state.timeout_seconds:g} seconds and was terminated.",
                        True,
                    ),
                )
            except asyncio.CancelledError:
                await asyncio.shield(_terminate_process_group(process))
                raise

            data = _command_data(process, stdout_raw, stderr_raw)
            if process.returncode == 0:
                return ToolResult(status="success", data=data)
            return ToolResult(
                status="error",
                data=data,
                error=ToolErrorInfo(
                    "command_failed",
                    f"Command exited with status {process.returncode}.",
                    True,
                ),
            )
        finally:
            self.active_process = None


def _command_data(process: Any, stdout: bytes | str | None, stderr: bytes | str | None):
    return {
        "exit_code": process.returncode,
        "stdout": _decode_output(stdout, "stdout"),
        "stderr": _decode_output(stderr, "stderr"),
    }


def _decode_output(value: bytes | str | None, stream_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ToolEncodingError(f"{stream_name} is not valid UTF-8.") from exc


async def _terminate_process_group(process: Any) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=1)
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()
    else:
        process.kill()
        await process.wait()
