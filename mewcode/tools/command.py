from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from mewcode.errors import ToolEncodingError, ToolInputError
from mewcode.tools.base import (
    ConfirmationPreview,
    JSONValue,
    PreparedToolAction,
    ToolContext,
    ToolDefinition,
    ToolErrorInfo,
    ToolResult,
)


@dataclass(frozen=True)
class _CommandState:
    command: str
    timeout_seconds: float


class RunCommandTool:
    definition = ToolDefinition(
        name="run_command",
        description="Run a complete shell command in the workspace after user confirmation.",
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
    requires_confirmation = True
    manages_own_timeout = True

    def __init__(
        self,
        *,
        popen: Callable[..., Any] = subprocess.Popen,
    ):
        self._popen = popen

    def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
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

    def execute(self, action: PreparedToolAction, context: ToolContext) -> ToolResult:
        state = action.state
        if not isinstance(state, _CommandState):
            raise RuntimeError("Invalid prepared command state.")
        popen_kwargs: dict[str, Any] = {
            "cwd": context.workspace.root,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": True,
        }
        if os.name == "posix":
            popen_kwargs["start_new_session"] = True
        elif os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

        process = self._popen(state.command, **popen_kwargs)
        try:
            stdout_raw, stderr_raw = process.communicate(timeout=state.timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            stdout_raw, stderr_raw = process.communicate()
            return ToolResult(
                status="timeout",
                data={
                    "exit_code": process.returncode,
                    "stdout": _decode_output(stdout_raw, "stdout"),
                    "stderr": _decode_output(stderr_raw, "stderr"),
                },
                error=ToolErrorInfo(
                    "timeout",
                    f"Command exceeded {state.timeout_seconds:g} seconds and was terminated.",
                    True,
                ),
            )

        stdout = _decode_output(stdout_raw, "stdout")
        stderr = _decode_output(stderr_raw, "stderr")
        data = {"exit_code": process.returncode, "stdout": stdout, "stderr": stderr}
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


def _decode_output(value: bytes | str | None, stream_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ToolEncodingError(f"{stream_name} is not valid UTF-8.") from exc


def _terminate_process_group(process: Any) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        process.kill()
