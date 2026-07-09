from __future__ import annotations

import sys
from typing import TextIO

from mewcode.config import LLMConfig
from mewcode.errors import MewCodeError
from mewcode.runtime import ChatRuntime

EXIT_COMMANDS = {"exit", "quit"}


class ChatApp:
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

    def run(self) -> int:
        self._write(f"MewCode\nUsing config: {self.config.name} ({self.config.protocol})\n")
        self._write("Type 'exit' or 'quit' to end the session.\n")

        while True:
            self._write("\nYou> ")
            line = self.input_stream.readline()
            if line == "":
                self._write("\n")
                return 0

            user_text = line.rstrip("\n")
            if not user_text.strip():
                continue
            if user_text.strip().lower() in EXIT_COMMANDS:
                self._write("Bye.\n")
                return 0

            self._write("AI> ")
            try:
                for chunk in self.runtime.stream_turn(user_text):
                    self._write(chunk)
                self._write("\n")
            except MewCodeError as exc:
                self._write(f"\nError: {exc.user_message}\n")

    def _write(self, text: str) -> None:
        self.output_stream.write(text)
        self.output_stream.flush()
