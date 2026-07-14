from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from mewcode.tools.base import ConfirmationPreview


class ConfirmationModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "reject", "Reject", show=False),
        Binding("n", "reject", "Reject", show=False),
        Binding("y", "approve", "Approve", show=False),
    ]

    def __init__(self, preview: ConfirmationPreview) -> None:
        super().__init__()
        self.preview = preview

    def compose(self) -> ComposeResult:
        with Container(id="confirmation-dialog"):
            yield Static(self.preview.title, id="confirmation-title", markup=False)
            with VerticalScroll(id="confirmation-preview"):
                yield Static(self.preview.details, markup=False)
            with Horizontal(id="confirmation-actions"):
                yield Button("Reject", id="reject", variant="error")
                yield Button("Approve", id="approve", variant="success")

    def on_mount(self) -> None:
        self.query_one("#reject", Button).focus()

    def action_reject(self) -> None:
        self.dismiss(False)

    def action_approve(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "approve":
            self.action_approve()
        else:
            self.action_reject()
