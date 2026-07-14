from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import TextArea


class PromptHistory:
    def __init__(self) -> None:
        self._entries: list[str] = []
        self._cursor: int | None = None
        self._draft = ""

    @property
    def entries(self) -> tuple[str, ...]:
        return tuple(self._entries)

    @property
    def is_navigating(self) -> bool:
        return self._cursor is not None

    def record(self, prompt: str) -> None:
        if not prompt.strip():
            return
        self._entries.append(prompt)
        self.reset_navigation()

    def previous(self, current_draft: str) -> str:
        if not self._entries:
            return current_draft
        if self._cursor is None:
            self._draft = current_draft
            self._cursor = len(self._entries) - 1
        elif self._cursor > 0:
            self._cursor -= 1
        return self._entries[self._cursor]

    def next(self) -> str:
        if self._cursor is None:
            return self._draft
        if self._cursor < len(self._entries) - 1:
            self._cursor += 1
            return self._entries[self._cursor]
        self._cursor = None
        return self._draft

    def reset_navigation(self) -> None:
        self._cursor = None
        self._draft = ""


class PromptComposer(TextArea):
    class Submitted(Message):
        def __init__(self, prompt: str) -> None:
            super().__init__()
            self.prompt = prompt

    def __init__(
        self,
        history: PromptHistory | None = None,
        *,
        unicode: bool = True,
    ) -> None:
        super().__init__(
            "",
            compact=True,
            highlight_cursor_line=False,
            placeholder="Describe a task…" if unicode else "Describe a task...",
            id="prompt-composer",
        )
        self.prompt_history = history or PromptHistory()
        self.busy = False
        self._sync_height()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.set_class(busy, "busy")

    def record_submission(self, prompt: str) -> None:
        self.prompt_history.record(prompt)
        self.load_text("")
        self._sync_height()

    def on_key(self, event: events.Key) -> None:
        if event.key in {"shift+enter", "ctrl+j"}:
            event.stop()
            event.prevent_default()
            self.prompt_history.reset_navigation()
            self.insert("\n")
            self._sync_height()
            return

        if event.key == "enter":
            event.stop()
            event.prevent_default()
            if not self.busy and self.text.strip():
                self.post_message(self.Submitted(self.text))
            return

        if event.key == "up" and (
            not self.text or self.prompt_history.is_navigating
        ):
            event.stop()
            event.prevent_default()
            self._load_history(self.prompt_history.previous(self.text))
            return

        if event.key == "down" and self.prompt_history.is_navigating:
            event.stop()
            event.prevent_default()
            self._load_history(self.prompt_history.next())
            return

        self.prompt_history.reset_navigation()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area is self:
            self._sync_height()

    def _load_history(self, text: str) -> None:
        self.load_text(text)
        lines = text.split("\n")
        self.move_cursor((len(lines) - 1, len(lines[-1])))
        self._sync_height()

    def _sync_height(self) -> None:
        line_count = min(6, max(1, self.text.count("\n") + 1))
        self.styles.height = line_count
