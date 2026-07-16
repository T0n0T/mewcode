from __future__ import annotations

import asyncio
import sys
from typing import TextIO

from mewcode.agent import (
    AgentSession,
    ConfirmationRequested,
    ConfirmationResolved,
    ProgressChanged,
    RunStarted,
    RunStopped,
    TextDeltaEvent,
    ToolFinished,
    ToolStarted,
    UsageReported,
)
from mewcode.config import LLMConfig
from mewcode.errors import MewCodeError
from mewcode.tui.mode import supports_unicode
from mewcode.tui.presentation import (
    activity_for_progress,
    error_for_stop,
    stop_label,
    usage_text,
)

EXIT_COMMANDS = {"exit", "quit"}

CAT_BANNER = r""" /\_/\
( o.o )
 > ^ <"""


class PlainChatApp:
    def __init__(
        self,
        session: AgentSession,
        config: LLMConfig,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> None:
        self.session = session
        self.config = config
        self.input_stream = input_stream or sys.stdin
        self.output_stream = output_stream or sys.stdout
        self._threaded_input = input_stream is None
        self._threaded_output = output_stream is None
        unicode_output = supports_unicode(self.output_stream)
        self.user_marker = "›" if unicode_output else ">"
        self.mewcode_marker = "◆" if unicode_output else "*"

    async def run(self) -> int:
        await self._write_header()

        while True:
            line = await self._readline()
            if line == "":
                return 0

            user_text = line.rstrip("\n")
            if not user_text.strip():
                continue
            if user_text.strip().lower() in EXIT_COMMANDS:
                await self._write("Bye.\n")
                return 0

            await self._write(f"\n{self.user_marker} {user_text}\n")
            try:
                run = await self.session.start(user_text)
            except MewCodeError as exc:
                await self._write(f"ERROR: {exc.user_message}\n")
                continue

            response_started = False
            try:
                async for event in run:
                    if isinstance(event, RunStarted):
                        await self._write(
                            f"{self.mewcode_marker} [{event.mode.value.upper()}]\n"
                        )
                    elif isinstance(event, ProgressChanged):
                        if response_started:
                            await self._write("\n")
                            response_started = False
                        state, detail = activity_for_progress(event)
                        await self._write(
                            f"{self.mewcode_marker} "
                            f"[{state.value.upper()} {detail}]\n"
                        )
                    elif isinstance(event, TextDeltaEvent):
                        if not response_started:
                            await self._write(f"{self.mewcode_marker} ")
                            response_started = True
                        await self._write(event.text)
                    elif isinstance(event, ToolStarted):
                        if response_started:
                            await self._write("\n")
                            response_started = False
                        suffix = (
                            f" ({event.argument_summary})"
                            if event.argument_summary
                            else ""
                        )
                        await self._write(
                            f"   [EXECUTING {event.name}]{suffix}\n"
                        )
                    elif isinstance(event, ToolFinished):
                        detail = event.status
                        if event.error_message:
                            detail = f"{detail}: {event.error_message}"
                        await self._write(
                            f"   [TOOL {event.name}] {detail} "
                            f"({event.duration_ms}ms)\n"
                        )
                    elif isinstance(event, ConfirmationRequested):
                        if response_started:
                            await self._write("\n")
                            response_started = False
                        await self._write(
                            f"\n{event.preview.title}\n"
                            f"{event.preview.details}\nApprove? [y/N] "
                        )
                        answer = await self._readline()
                        approved = answer.strip().lower() in {"y", "yes"}
                        run.resolve_confirmation(event.request_id, approved)
                    elif isinstance(event, ConfirmationResolved):
                        decision = "APPROVED" if event.approved else "REJECTED"
                        await self._write(f"   [CONFIRMATION {decision}]\n")
                    elif isinstance(event, UsageReported):
                        if response_started:
                            await self._write("\n")
                            response_started = False
                        await self._write(f"   [{usage_text(event)}]\n")
                    elif isinstance(event, RunStopped):
                        if response_started:
                            await self._write("\n")
                            response_started = False
                        error = error_for_stop(event)
                        if error is not None:
                            await self._write(f"ERROR: {error.message}\n")
                            await self._write(f"NEXT: {error.suggestion}\n")
                        await self._write(
                            f"{self.mewcode_marker} [{stop_label(event)}]\n"
                        )
            except KeyboardInterrupt:
                await run.cancel()
                await run.wait_closed()
            except asyncio.CancelledError:
                await asyncio.shield(run.cancel())
                raise

    async def _readline(self) -> str:
        if self._threaded_input:
            return await asyncio.to_thread(self.input_stream.readline)
        return self.input_stream.readline()

    async def _write(self, text: str) -> None:
        def write_and_flush() -> None:
            self.output_stream.write(text)
            self.output_stream.flush()

        if self._threaded_output:
            await asyncio.to_thread(write_and_flush)
        else:
            write_and_flush()

    async def _write_header(self) -> None:
        await self._write(
            f"{CAT_BANNER}\n"
            "MEWCODE // CYBER TERMINAL\n"
            f"config   {self.config.name}\n"
            f"provider {self.config.protocol}\n"
            f"model    {self.config.model}\n"
            "Commands: /plan <task>, /do, exit, quit.\n"
        )
