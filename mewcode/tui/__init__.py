from mewcode.tui.metadata import SessionMetadata, build_session_metadata
from mewcode.tui.mode import TerminalMode, detect_terminal_mode, supports_unicode

__all__ = [
    "CyberpunkChatApp",
    "PlainChatApp",
    "PlainToolInteraction",
    "SessionMetadata",
    "TerminalMode",
    "TuiEventBridge",
    "TuiToolInteraction",
    "build_session_metadata",
    "detect_terminal_mode",
    "supports_unicode",
]


def __getattr__(name: str):
    if name == "CyberpunkChatApp":
        from mewcode.tui.app import CyberpunkChatApp

        return CyberpunkChatApp
    if name in {"PlainChatApp", "PlainToolInteraction"}:
        from mewcode.tui.plain import PlainChatApp, PlainToolInteraction

        return {
            "PlainChatApp": PlainChatApp,
            "PlainToolInteraction": PlainToolInteraction,
        }[name]
    if name in {"TuiEventBridge", "TuiToolInteraction"}:
        from mewcode.tui.interaction import TuiEventBridge, TuiToolInteraction

        return {
            "TuiEventBridge": TuiEventBridge,
            "TuiToolInteraction": TuiToolInteraction,
        }[name]
    raise AttributeError(name)
