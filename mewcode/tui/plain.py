from __future__ import annotations

import sys
from typing import TextIO

from mewcode.config import LLMConfig
from mewcode.errors import MewCodeError, redact_secrets
from mewcode.providers.base import ToolCall
from mewcode.runtime import ChatRuntime
from mewcode.tools.base import ConfirmationPreview, JSONValue, ToolResult
from mewcode.tui.events import DEFAULT_ERROR_SUGGESTION
from mewcode.tui.mode import supports_unicode
from mewcode.turns import (
    TurnCancellation,
    TurnCompleted,
    TurnInterrupted,
    TurnPhase,
    TurnPhaseChanged,
    TurnTextDelta,
)

EXIT_COMMANDS = {"exit", "quit"}

CAT_BANNER = r""" /\_/\
( o.o )
 > ^ <"""


class PlainToolInteraction:
    def __init__(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        *,
        secrets: tuple[str, ...] = (),
    ):
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self.secrets = secrets

    def tool_started(self, call: ToolCall) -> None:
        summary = argument_summary(call.arguments, self.secrets)
        suffix = f" ({summary})" if summary else ""
        self._write(f"   [EXECUTING {call.name}]{suffix}\n")

    def confirm(self, preview: ConfirmationPreview) -> bool:
        title = redact_secrets(preview.title, self.secrets)
        details = redact_secrets(preview.details, self.secrets)
        self._write(f"\n{title}\n{details}\nApprove? [y/N] ")
        answer = self.input_stream.readline()
        return answer.strip().lower() in {"y", "yes"}

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        if result.error is None:
            detail = result.status
        else:
            message = redact_secrets(result.error.message, self.secrets)
            detail = f"{result.status}: {message}"
        self._write(f"   [TOOL {call.name}] {detail}\n")

    def tool_budget_exhausted(self) -> None:
        self._write("   [TOOL LIMIT] Additional request was not executed.\n")

    def _write(self, text: str) -> None:
        self.output_stream.write(text)
        self.output_stream.flush()


def argument_summary(
    arguments: dict[str, JSONValue],
    secrets: tuple[str, ...],
) -> str:
    visible_keys = ("path", "pattern", "query", "command")
    parts: list[str] = []
    for key in visible_keys:
        value = arguments.get(key)
        if isinstance(value, str):
            parts.append(f"{key}={redact_secrets(value, secrets)}")
    return ", ".join(parts)


class PlainChatApp:
    def __init__(
        self,
        runtime: ChatRuntime,
        config: LLMConfig,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ):
        self.runtime = runtime
        self.config = config
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        unicode_output = supports_unicode(self.output_stream)
        self.user_marker = "›" if unicode_output else ">"
        self.mewcode_marker = "◆" if unicode_output else "*"

    def run(self) -> int:
        self._write_header()

        while True:
            line = self.input_stream.readline()
            if line == "":
                return 0

            user_text = line.rstrip("\n")
            if not user_text.strip():
                continue
            if user_text.strip().lower() in EXIT_COMMANDS:
                self._write("Bye.\n")
                return 0

            self._write(f"\n{self.user_marker} {user_text}\n")
            cancellation = TurnCancellation()
            response_started = False
            try:
                for event in self.runtime.stream_turn(user_text, cancellation):
                    if isinstance(event, TurnPhaseChanged):
                        if response_started:
                            self._write("\n")
                            response_started = False
                        label = (
                            f"UPLINKING {self.config.model}"
                            if event.phase is TurnPhase.INITIAL_RESPONSE
                            else "SYNTHESIZING"
                        )
                        self._write(f"{self.mewcode_marker} [{label}]\n")
                    elif isinstance(event, TurnTextDelta):
                        if not response_started:
                            self._write(f"{self.mewcode_marker} ")
                            response_started = True
                        self._write(event.text)
                    elif isinstance(event, TurnCompleted) and response_started:
                        self._write("\n")
                        response_started = False
            except TurnInterrupted:
                if response_started:
                    self._write("\n")
                self._write(f"{self.mewcode_marker} [INTERRUPTED]\n")
            except MewCodeError as exc:
                if response_started:
                    self._write("\n")
                self._write(f"ERROR: {exc.user_message}\n")
                self._write(f"NEXT: {DEFAULT_ERROR_SUGGESTION}\n")

    def _write(self, text: str) -> None:
        self.output_stream.write(text)
        self.output_stream.flush()

    def _write_header(self) -> None:
        self._write(
            f"{CAT_BANNER}\n"
            "MEWCODE // CYBER TERMINAL\n"
            f"config   {self.config.name}\n"
            f"provider {self.config.protocol}\n"
            f"model    {self.config.model}\n"
            "Type 'exit' or 'quit' to end the session.\n"
        )
