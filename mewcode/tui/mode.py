from __future__ import annotations

import sys
from enum import Enum
from typing import TextIO


class TerminalMode(str, Enum):
    FULLSCREEN = "fullscreen"
    PLAIN = "plain"


def detect_terminal_mode(
    input_stream: TextIO,
    output_stream: TextIO,
) -> TerminalMode:
    if input_stream is not sys.stdin or output_stream is not sys.stdout:
        return TerminalMode.PLAIN
    try:
        interactive = input_stream.isatty() and output_stream.isatty()
    except (AttributeError, OSError):
        return TerminalMode.PLAIN
    return TerminalMode.FULLSCREEN if interactive else TerminalMode.PLAIN
