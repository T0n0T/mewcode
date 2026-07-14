from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from typing import TypeAlias


class TurnPhase(str, Enum):
    INITIAL_RESPONSE = "initial_response"
    FINAL_RESPONSE = "final_response"


@dataclass(frozen=True)
class TurnPhaseChanged:
    phase: TurnPhase


@dataclass(frozen=True)
class TurnTextDelta:
    text: str


@dataclass(frozen=True)
class TurnCompleted:
    pass


TurnEvent: TypeAlias = TurnPhaseChanged | TurnTextDelta | TurnCompleted


class TurnInterrupted(Exception):
    """Signal a user-requested turn interruption."""


class TurnCancellation:
    def __init__(self) -> None:
        self._lock = Lock()
        self._cancelled = False
        self._stream_closer: Callable[[], None] | None = None
        self._stream_closer_called = False

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        closer: Callable[[], None] | None = None
        with self._lock:
            if self._cancelled:
                return
            self._cancelled = True
            if self._stream_closer is not None and not self._stream_closer_called:
                self._stream_closer_called = True
                closer = self._stream_closer
        if closer is not None:
            _close_safely(closer)

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TurnInterrupted()

    @contextmanager
    def bind_stream_closer(self, closer: Callable[[], None]) -> Iterator[None]:
        close_immediately = False
        with self._lock:
            if self._stream_closer is not None:
                raise RuntimeError("A provider stream is already bound to this turn.")
            if self._cancelled:
                close_immediately = True
            else:
                self._stream_closer = closer
                self._stream_closer_called = False

        if close_immediately:
            _close_safely(closer)

        try:
            yield
        finally:
            with self._lock:
                if self._stream_closer is closer:
                    self._stream_closer = None
                    self._stream_closer_called = False


def _close_safely(closer: Callable[[], None]) -> None:
    try:
        closer()
    except Exception:
        # Cancellation is already recorded. Provider iteration will observe it
        # and must not turn a best-effort close failure into a user-facing error.
        pass
