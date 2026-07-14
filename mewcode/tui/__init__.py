from mewcode.tui.metadata import SessionMetadata, build_session_metadata
from mewcode.tui.mode import TerminalMode, detect_terminal_mode
from mewcode.tui.plain import PlainChatApp, PlainToolInteraction
from mewcode.tui.app import CyberpunkChatApp
from mewcode.tui.interaction import TuiEventBridge, TuiToolInteraction

# Temporary compatibility exports while CLI wiring is migrated.
ChatApp = PlainChatApp
TerminalToolInteraction = PlainToolInteraction

__all__ = [
    "ChatApp",
    "CyberpunkChatApp",
    "PlainChatApp",
    "PlainToolInteraction",
    "SessionMetadata",
    "TerminalMode",
    "TerminalToolInteraction",
    "TuiEventBridge",
    "TuiToolInteraction",
    "build_session_metadata",
    "detect_terminal_mode",
]
