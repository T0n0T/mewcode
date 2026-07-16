from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Collapsible, Markdown, Static

from mewcode.agent.events import ToolFinished, ToolStarted
from mewcode.tui.presentation import ErrorPresentation


class UserMessageView(Static):
    def __init__(self, text: str, *, unicode: bool = True) -> None:
        marker = "›" if unicode else ">"
        super().__init__(
            f"{marker} {text}",
            classes="user-message",
            markup=False,
        )


class AssistantMessageView(Vertical):
    def __init__(self, *, unicode: bool = True) -> None:
        super().__init__(classes="assistant-message")
        self.marker = "◆" if unicode else "*"
        self._stream = None
        self._interrupted = False

    def compose(self) -> ComposeResult:
        yield Static(self.marker, classes="message-marker", markup=False)
        yield Markdown("", classes="assistant-markdown")

    async def append_markdown(self, fragment: str) -> None:
        markdown = self.query_one(Markdown)
        if self._stream is None:
            self._stream = Markdown.get_stream(markdown)
        await self._stream.write(fragment)

    async def finalize(self) -> None:
        if self._stream is not None:
            await self._stream.stop()
            self._stream = None

    async def mark_interrupted(self) -> None:
        await self.finalize()
        if not self._interrupted:
            self._interrupted = True
            await self.mount(
                Static("INTERRUPTED", classes="interrupted status-warning")
            )


class ConversationView(VerticalScroll):
    class UnreadChanged(Message):
        def __init__(self, count: int) -> None:
            super().__init__()
            self.count = count

    def __init__(self, *children: Widget) -> None:
        super().__init__(*children, id="conversation", can_focus=True)
        self.follow_output = True
        self.unread_output = 0
        self._scrolling_to_latest = False

    async def append_widget(self, widget: Widget) -> None:
        await self.mount(widget)
        self.note_output()

    def note_output(self) -> None:
        if self.follow_output:
            self.call_after_refresh(self._scroll_to_latest)
            return
        self.unread_output += 1
        self.post_message(self.UnreadChanged(self.unread_output))

    def freeze_following(self) -> None:
        self.follow_output = False

    def return_to_bottom(self) -> None:
        self.follow_output = True
        self.unread_output = 0
        self._scroll_to_latest()
        self.post_message(self.UnreadChanged(0))

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if (
            self.follow_output
            and not self._scrolling_to_latest
            and new_value < self.max_scroll_y
        ):
            self.freeze_following()

    def _scroll_to_latest(self) -> None:
        if self.follow_output:
            self._scrolling_to_latest = True
            try:
                self.scroll_end(animate=False, immediate=True)
            finally:
                self._scrolling_to_latest = False

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.freeze_following()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"pageup", "up", "home"}:
            self.freeze_following()
        elif event.key == "end":
            event.stop()
            event.prevent_default()
            self.return_to_bottom()


class ToolCard(Collapsible):
    def __init__(self, payload: ToolStarted, *, unicode: bool = True) -> None:
        self.call_id = payload.call_id
        self.tool_name = payload.name
        self._separator = " · " if unicode else " - "
        self._details = Static(
            _started_details(payload),
            classes="tool-details",
            markup=False,
        )
        super().__init__(
            self._details,
            title=f"EXECUTING {payload.name}",
            collapsed=True,
            collapsed_symbol="▶" if unicode else ">",
            expanded_symbol="▼" if unicode else "v",
            classes="card tool-card",
        )

    def finish(self, payload: ToolFinished) -> None:
        if payload.call_id != self.call_id:
            raise ValueError("Tool completion does not match this card.")
        self.title = (
            f"{payload.status.upper()} {payload.name}"
            f"{self._separator}{payload.duration_ms}ms"
        )
        details = []
        if payload.error_message:
            details.append(f"error: {payload.error_message}")
        if payload.truncation is not None:
            details.append(
                "truncated: "
                f"{payload.truncation.returned}/{payload.truncation.original} "
                f"{payload.truncation.unit}"
            )
            details.append(f"hint: {payload.truncation.hint}")
        if not details:
            details.append("Result metadata only; full output was sent to the model.")
        next_step = {
            "error": "Review the error, correct the tool input, and try again.",
            "timeout": "Narrow the operation before trying the tool again.",
            "rejected": "Approve explicitly if you want this operation to run.",
        }.get(payload.status)
        if next_step is not None:
            details.append(f"NEXT: {next_step}")
        self._details.update("\n".join(details))
        self.remove_class("status-error", "status-warning", "status-success")
        status_class = {
            "success": "status-success",
            "rejected": "status-warning",
            "timeout": "status-warning",
            "error": "status-error",
        }[payload.status]
        self.add_class(status_class)

    def interrupt(self) -> None:
        self.title = f"INTERRUPTED {self.tool_name}"
        self._details.update(
            "Execution was interrupted; already-started side effects are not rolled back."
        )
        self.remove_class("status-error", "status-success")
        self.add_class("status-warning")


class ErrorCard(Vertical):
    def __init__(self, payload: ErrorPresentation, *, unicode: bool = True) -> None:
        details = payload.technical_detail or "No additional technical details."
        separator = " · " if unicode else " - "
        self.title = f"ERROR{separator}{payload.message}"
        self._technical = Collapsible(
            Static(details, markup=False),
            title="Technical details",
            collapsed=True,
            collapsed_symbol="▶" if unicode else ">",
            expanded_symbol="▼" if unicode else "v",
            classes="error-technical",
        )
        super().__init__(
            Static(self.title, classes="error-title", markup=False),
            Static(
                f"NEXT: {payload.suggestion}",
                classes="error-suggestion",
                markup=False,
            ),
            self._technical,
            classes="card error-card status-error",
        )

    @property
    def collapsed(self) -> bool:
        return self._technical.collapsed


def _started_details(payload: ToolStarted) -> str:
    return payload.argument_summary or "No displayable arguments."
