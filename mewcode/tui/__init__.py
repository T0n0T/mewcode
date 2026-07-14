from mewcode.tui.metadata import SessionMetadata, build_session_metadata
from mewcode.tui.mode import TerminalMode, detect_terminal_mode
from mewcode.tui.plain import PlainChatApp, PlainToolInteraction

# Temporary compatibility exports while CLI wiring is migrated.
ChatApp = PlainChatApp
TerminalToolInteraction = PlainToolInteraction

__all__ = [
    "ChatApp",
    "PlainChatApp",
    "PlainToolInteraction",
    "SessionMetadata",
    "TerminalMode",
    "TerminalToolInteraction",
    "build_session_metadata",
    "detect_terminal_mode",
]
