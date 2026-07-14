from __future__ import annotations

from collections.abc import Callable
from time import monotonic

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Static

from mewcode.tui.events import ActivityState
from mewcode.tui.metadata import SessionMetadata


class SessionHeader(Horizontal):
    def __init__(
        self,
        metadata: SessionMetadata,
        *,
        unicode: bool = True,
        id: str | None = "session-header",
    ) -> None:
        super().__init__(id=id)
        self.metadata = metadata
        self._brand_marker = "◆" if unicode else "*"

    def compose(self) -> ComposeResult:
        yield Static(f"{self._brand_marker} MEWCODE", id="brand")
        yield Static(f"model:{self.metadata.model}", id="header-model")
        yield Static(
            f"workspace:{self.metadata.workspace}",
            id="header-workspace",
            classes="compact-only",
        )
        branch = (
            f"git:{self.metadata.git_branch}"
            if self.metadata.git_branch is not None
            else ""
        )
        yield Static(branch, id="header-branch", classes="wide-only")
        yield Static("READY", id="connection-status")

    def set_activity(
        self,
        state: ActivityState,
        detail: str | None = None,
    ) -> None:
        text = state.value.upper()
        if detail:
            text = f"{text}:{detail}"
        self.query_one("#connection-status", Static).update(text)


class WelcomeCard(Static):
    def __init__(self, metadata: SessionMetadata) -> None:
        workspace = metadata.workspace.name or str(metadata.workspace)
        cat_ears = " /" + "\\" + "_/" + "\\"
        content = (
            f"{cat_ears}\n"
            "( o.o )   MEWCODE // CYBER TERMINAL\n"
            " > ^ <\n"
            f"model     {metadata.model}\n"
            f"workspace {workspace}\n"
            "Chat, stream responses, and approve existing workspace tools."
        )
        super().__init__(content, classes="card welcome-card", markup=False)


class ActivityIndicator(Static):
    _UNICODE_SPINNER = ("◆", "◇", "◈", "◇")
    _ASCII_SPINNER = ("|", "/", "-", "\\")
    _LABELS = {
        ActivityState.READY: "READY",
        ActivityState.UPLINKING: "UPLINKING",
        ActivityState.STREAMING: "STREAMING",
        ActivityState.EXECUTING: "EXECUTING",
        ActivityState.SYNTHESIZING: "SYNTHESIZING",
        ActivityState.INTERRUPTED: "INTERRUPTED",
        ActivityState.ERROR: "ERROR",
    }

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
        unicode: bool = True,
    ) -> None:
        super().__init__("", classes="activity")
        self.state = ActivityState.READY
        self.detail: str | None = None
        self._clock = clock
        self._spinner = self._UNICODE_SPINNER if unicode else self._ASCII_SPINNER
        self._static_marker = "◆" if unicode else "*"
        self._separator = " · " if unicode else " - "
        self._started_at = clock()
        self._frame = 0
        self._refresh_content()

    def on_mount(self) -> None:
        self.set_interval(0.125, self._tick)

    def set_activity(
        self,
        state: ActivityState,
        detail: str | None = None,
    ) -> None:
        self.state = state
        self.detail = detail
        self._started_at = self._clock()
        self._frame = 0
        self._refresh_content()

    def _tick(self) -> None:
        if self.state in {
            ActivityState.UPLINKING,
            ActivityState.EXECUTING,
            ActivityState.SYNTHESIZING,
        }:
            self._frame += 1
            self._refresh_content()

    def _refresh_content(self) -> None:
        label = self._LABELS[self.state]
        detail = f" {self.detail}" if self.detail else ""
        if self.state in {
            ActivityState.UPLINKING,
            ActivityState.EXECUTING,
            ActivityState.SYNTHESIZING,
        }:
            elapsed = max(0.0, self._clock() - self._started_at)
            marker = self._spinner[self._frame % len(self._spinner)]
            self.update(
                f"{marker} {label}{detail}{self._separator}{elapsed:.1f}s"
            )
        else:
            self.update(f"{self._static_marker} {label}{detail}")


class NewOutputIndicator(Button):
    class ReturnToBottom(Message):
        pass

    def __init__(self, *, unicode: bool = True) -> None:
        self._arrow = "↓" if unicode else "v"
        super().__init__(f"NEW OUTPUT {self._arrow}", id="new-output")
        self.count = 0
        self.display = False

    def set_count(self, count: int) -> None:
        self.count = max(0, count)
        self.label = (
            f"NEW OUTPUT ({self.count}) {self._arrow}"
            if self.count
            else f"NEW OUTPUT {self._arrow}"
        )
        self.display = self.count > 0

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button is self:
            event.stop()
            self.post_message(self.ReturnToBottom())
