from dataclasses import FrozenInstanceError
from threading import Event, Thread

import pytest

from mewcode.errors import MewCodeError
from mewcode.turns import (
    TurnCancellation,
    TurnCompleted,
    TurnInterrupted,
    TurnPhase,
    TurnPhaseChanged,
    TurnTextDelta,
)


def test_turn_events_are_immutable_and_have_stable_values():
    phase = TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
    delta = TurnTextDelta("hello")
    completed = TurnCompleted()

    assert phase.phase.value == "initial_response"
    assert TurnPhase.FINAL_RESPONSE.value == "final_response"
    assert delta.text == "hello"
    assert completed == TurnCompleted()

    with pytest.raises(FrozenInstanceError):
        delta.text = "changed"  # type: ignore[misc]


def test_turn_interrupted_is_not_a_user_facing_error():
    assert not issubclass(TurnInterrupted, MewCodeError)


def test_new_cancellation_is_not_cancelled():
    cancellation = TurnCancellation()

    assert cancellation.is_cancelled is False
    cancellation.raise_if_cancelled()


def test_cancel_is_idempotent_and_raises_interrupted():
    cancellation = TurnCancellation()

    cancellation.cancel()
    cancellation.cancel()

    assert cancellation.is_cancelled is True
    with pytest.raises(TurnInterrupted):
        cancellation.raise_if_cancelled()


def test_active_stream_closer_is_called_once():
    cancellation = TurnCancellation()
    calls: list[str] = []

    with cancellation.bind_stream_closer(lambda: calls.append("closed")):
        cancellation.cancel()
        cancellation.cancel()

    assert calls == ["closed"]


def test_pre_cancelled_stream_is_closed_when_bound():
    cancellation = TurnCancellation()
    calls: list[str] = []
    cancellation.cancel()

    with cancellation.bind_stream_closer(lambda: calls.append("closed")):
        pass

    assert calls == ["closed"]


def test_unbound_expired_stream_is_not_closed():
    cancellation = TurnCancellation()
    calls: list[str] = []

    with cancellation.bind_stream_closer(lambda: calls.append("closed")):
        pass
    cancellation.cancel()

    assert calls == []


def test_overlapping_stream_bindings_are_rejected():
    cancellation = TurnCancellation()

    with cancellation.bind_stream_closer(lambda: None):
        with pytest.raises(RuntimeError, match="already bound"):
            with cancellation.bind_stream_closer(lambda: None):
                pass


def test_concurrent_cancellation_only_invokes_closer_once():
    cancellation = TurnCancellation()
    closer_started = Event()
    release_closer = Event()
    calls: list[str] = []

    def closer() -> None:
        calls.append("closed")
        closer_started.set()
        assert release_closer.wait(timeout=1)

    with cancellation.bind_stream_closer(closer):
        thread = Thread(target=cancellation.cancel)
        thread.start()
        assert closer_started.wait(timeout=1)
        cancellation.cancel()
        release_closer.set()
        thread.join(timeout=1)

    assert thread.is_alive() is False
    assert calls == ["closed"]


def test_closer_failure_does_not_replace_interruption():
    cancellation = TurnCancellation()

    def failing_closer() -> None:
        raise RuntimeError("close failed")

    with cancellation.bind_stream_closer(failing_closer):
        cancellation.cancel()

    with pytest.raises(TurnInterrupted):
        cancellation.raise_if_cancelled()
