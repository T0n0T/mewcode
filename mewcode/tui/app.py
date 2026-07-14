from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Static

from mewcode.runtime import ChatRuntime
from mewcode.tui.interaction import TuiEventBridge
from mewcode.tui.metadata import SessionMetadata


class CyberpunkChatApp(App[None]):
    CSS_PATH = "cyberpunk.tcss"
    TITLE = "MewCode"
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        runtime: ChatRuntime,
        metadata: SessionMetadata,
        bridge: TuiEventBridge,
    ) -> None:
        super().__init__()
        self.runtime = runtime
        self.metadata = metadata
        self.bridge = bridge

    def compose(self) -> ComposeResult:
        yield Static("MEWCODE", id="app-placeholder")

    def on_mount(self) -> None:
        self.bridge.bind(self)
