from __future__ import annotations

from concurrent.futures import Future
from threading import Lock
from time import monotonic
from typing import Any, Protocol

from textual.message import Message

from mewcode.errors import redact_secrets
from mewcode.providers.base import ToolCall
from mewcode.tools.base import ConfirmationPreview, ToolResult
from mewcode.tui.events import (
    ConfirmationPayload,
    ConfirmationRequestedMessage,
    ToolBudgetMessage,
    ToolBudgetPayload,
    ToolFinishedMessage,
    ToolFinishedPayload,
    ToolStartedMessage,
    ToolStartedPayload,
    TruncationPresentation,
)
from mewcode.tui.plain import argument_summary


class TuiEventTarget(Protocol):
    def call_from_thread(self, callback: Any, *args: Any, **kwargs: Any) -> Any: ...

    def post_message(self, message: Message) -> bool: ...


class TuiEventBridge:
    def __init__(self) -> None:
        self._lock = Lock()
        self._target: TuiEventTarget | None = None
        self._closed = False
        self._generation_id = 0
        self._pending_confirmations: set[Future[bool]] = set()

    @property
    def generation_id(self) -> int:
        with self._lock:
            return self._generation_id

    def begin_generation(self, generation_id: int) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The TUI event bridge is closed.")
            self._generation_id = generation_id

    def bind(self, target: TuiEventTarget) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("The TUI event bridge is closed.")
            if self._target is not None:
                raise RuntimeError("The TUI event bridge is already bound.")
            self._target = target

    def emit(self, message: Message) -> bool:
        with self._lock:
            if self._closed:
                return False
            target = self._target
        if target is None:
            raise RuntimeError("The TUI event bridge is not bound.")
        target.call_from_thread(target.post_message, message)
        return True

    def request_confirmation(self, preview: ConfirmationPreview) -> bool:
        decision: Future[bool] = Future()
        decision.add_done_callback(self._forget_confirmation)

        with self._lock:
            if self._closed:
                return False
            if self._target is None:
                raise RuntimeError("The TUI event bridge is not bound.")
            self._pending_confirmations.add(decision)
            generation_id = self._generation_id

        try:
            emitted = self.emit(
                ConfirmationRequestedMessage(
                    ConfirmationPayload(generation_id, preview, decision)
                )
            )
        except Exception:
            self.resolve_confirmation(decision, False)
            raise
        if not emitted:
            self.resolve_confirmation(decision, False)
        return decision.result()

    def resolve_confirmation(
        self,
        decision: Future[bool],
        approved: bool,
    ) -> None:
        if not decision.done():
            decision.set_result(approved)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._target = None
            pending = tuple(self._pending_confirmations)
            self._pending_confirmations.clear()
        for decision in pending:
            self.resolve_confirmation(decision, False)

    def _forget_confirmation(self, decision: Future[bool]) -> None:
        with self._lock:
            self._pending_confirmations.discard(decision)


class TuiToolInteraction:
    def __init__(
        self,
        bridge: TuiEventBridge,
        *,
        secrets: tuple[str, ...] = (),
        clock: Any = monotonic,
    ) -> None:
        self.bridge = bridge
        self.secrets = secrets
        self._clock = clock

    def tool_started(self, call: ToolCall) -> None:
        self.bridge.emit(
            ToolStartedMessage(
                ToolStartedPayload(
                    generation_id=self.bridge.generation_id,
                    call_id=call.call_id,
                    name=call.name,
                    argument_summary=argument_summary(call.arguments, self.secrets),
                    started_at=self._clock(),
                )
            )
        )

    def confirm(self, preview: ConfirmationPreview) -> bool:
        safe_preview = ConfirmationPreview(
            preview.kind,
            redact_secrets(preview.title, self.secrets),
            redact_secrets(preview.details, self.secrets),
        )
        return self.bridge.request_confirmation(safe_preview)

    def tool_finished(self, call: ToolCall, result: ToolResult) -> None:
        error_message = (
            redact_secrets(result.error.message, self.secrets)
            if result.error is not None
            else None
        )
        truncation = (
            TruncationPresentation(
                unit=result.truncation.unit,
                original=result.truncation.original,
                returned=result.truncation.returned,
                hint=redact_secrets(result.truncation.hint, self.secrets),
                field=result.truncation.field,
            )
            if result.truncation is not None
            else None
        )
        self.bridge.emit(
            ToolFinishedMessage(
                ToolFinishedPayload(
                    generation_id=self.bridge.generation_id,
                    call_id=call.call_id,
                    name=call.name,
                    status=result.status,
                    duration_ms=result.duration_ms,
                    error_message=error_message,
                    truncation=truncation,
                )
            )
        )

    def tool_budget_exhausted(self) -> None:
        self.bridge.emit(
            ToolBudgetMessage(ToolBudgetPayload(self.bridge.generation_id))
        )
