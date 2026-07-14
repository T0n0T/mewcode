import asyncio

import pytest

from mewcode.agent.control import ConfirmationBroker, EventChannel
from mewcode.agent.events import EventContext, RunStopped, TextDeltaEvent
from mewcode.agent.types import StopReason
from mewcode.cancellation import CancellationToken


@pytest.mark.asyncio
async def test_cancellation_token_is_idempotent_and_releases_all_waiters():
    token = CancellationToken()
    assert token.is_cancelled is False
    token.raise_if_cancelled()
    waiters = [
        asyncio.create_task(token.wait_cancelled()),
        asyncio.create_task(token.wait_cancelled()),
    ]
    token.cancel()
    token.cancel()
    await asyncio.gather(*waiters)
    assert token.is_cancelled is True
    with pytest.raises(asyncio.CancelledError):
        token.raise_if_cancelled()


def text_event(value: str):
    return TextDeltaEvent(EventContext("run", 0, 1), value)


def test_event_queue_rejects_unbounded_capacity():
    with pytest.raises(ValueError, match="capacity"):
        EventChannel("run", capacity=0)


@pytest.mark.asyncio
async def test_event_queue_sequence_is_unique_and_concurrent_safe():
    channel = EventChannel("run", capacity=64)
    await asyncio.gather(
        *(channel.publish(text_event(str(index))) for index in range(20))
    )
    events = [await channel.get() for _ in range(20)]

    assert [event.context.sequence for event in events] == list(range(1, 21))
    assert all(isinstance(event, TextDeltaEvent) for event in events)
    assert {event.text for event in events if isinstance(event, TextDeltaEvent)} == {
        str(index) for index in range(20)
    }


@pytest.mark.asyncio
async def test_event_queue_applies_backpressure_at_capacity():
    channel = EventChannel("run", capacity=2)
    await channel.publish(text_event("one"))
    await channel.publish(text_event("two"))
    blocked = asyncio.create_task(channel.publish(text_event("three")))
    await asyncio.sleep(0)
    assert not blocked.done()
    await channel.get()
    await blocked


@pytest.mark.asyncio
async def test_terminal_event_uses_reserved_capacity_when_queue_is_full():
    channel = EventChannel("run", capacity=1)
    await channel.publish(text_event("queued"))
    terminal = RunStopped(EventContext("run", 0, 1), StopReason.CANCELLED, "cancelled")

    stopping = asyncio.create_task(channel.stop(terminal))
    await asyncio.sleep(0)
    completed_without_drain = stopping.done()
    if not completed_without_drain:
        stopping.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stopping

    assert completed_without_drain
    assert stopping.result() is True
    queued = await channel.get()
    assert isinstance(queued, TextDeltaEvent)
    observed = await anext(channel.events())
    assert isinstance(observed, RunStopped)


@pytest.mark.asyncio
async def test_late_publish_is_rejected_immediately_when_queue_remains_full():
    channel = EventChannel("run", capacity=1)
    await channel.publish(text_event("queued"))
    await channel.stop(
        RunStopped(EventContext("run", 0, 1), StopReason.CANCELLED, "cancelled")
    )

    late = asyncio.create_task(channel.publish(text_event("late")))
    await asyncio.sleep(0)
    completed_without_drain = late.done()
    if not completed_without_drain:
        late.cancel()
        with pytest.raises(asyncio.CancelledError):
            await late

    assert completed_without_drain
    assert late.result() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason",
    [StopReason.COMPLETED, StopReason.CANCELLED, StopReason.PROVIDER_ERROR],
)
async def test_single_consumer_unique_terminal_and_late_events_are_ignored(reason):
    channel = EventChannel("run")
    events = channel.events()
    with pytest.raises(RuntimeError, match="one consumer"):
        channel.events()

    terminal = RunStopped(EventContext("run", 0, 1), reason, "done")
    assert await channel.stop(terminal) is True
    assert await channel.stop(terminal) is False
    assert await channel.publish(text_event("late")) is False
    observed = await anext(events)
    assert isinstance(observed, RunStopped)
    assert observed.reason is reason
    with pytest.raises(StopAsyncIteration):
        await anext(events)


@pytest.mark.asyncio
async def test_publishing_run_stopped_closes_channel_and_rejects_late_events():
    channel = EventChannel("run")
    events = channel.events()
    terminal = RunStopped(
        EventContext("run", 0, 1), StopReason.INTERNAL_ERROR, "failed"
    )

    assert await channel.publish(terminal) is True
    assert await channel.publish(terminal) is False
    assert await channel.publish(text_event("late")) is False
    observed = await anext(events)
    assert isinstance(observed, RunStopped)
    assert observed.reason is StopReason.INTERNAL_ERROR
    with pytest.raises(StopAsyncIteration):
        await anext(events)


@pytest.mark.asyncio
async def test_confirmation_broker_resolves_once_and_cancel_cleans_pending():
    ids = iter(["confirm-1", "confirm-2", "confirm-3"])
    broker = ConfirmationBroker(id_factory=lambda: next(ids))
    request_id, decision = broker.create()

    assert request_id == "confirm-1"
    assert broker.resolve(request_id, True) is True
    assert broker.resolve(request_id, False) is False
    assert broker.resolve("missing", True) is False
    assert await decision is True

    second_id, rejected = broker.create()
    assert broker.resolve(second_id, False) is True
    assert await rejected is False

    third_id, pending = broker.create()
    broker.cancel_all()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert broker.resolve(third_id, True) is False


@pytest.mark.asyncio
async def test_consumer_close_invokes_cancel_callback_once_and_cleans_confirmations():
    calls = 0
    broker = ConfirmationBroker(id_factory=lambda: "confirm-1")
    _request_id, decision = broker.create()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def cancel():
        nonlocal calls
        calls += 1
        broker.cancel_all()
        cleanup_started.set()
        await allow_cleanup.wait()

    channel = EventChannel("run", on_consumer_close=cancel)
    events = channel.events()
    pending = asyncio.ensure_future(anext(events))
    await asyncio.sleep(0)
    pending.cancel()
    await cleanup_started.wait()
    assert not pending.done()
    allow_cleanup.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await events.aclose()

    assert calls == 1
    with pytest.raises(asyncio.CancelledError):
        await decision


@pytest.mark.asyncio
async def test_consumer_aclose_before_iteration_still_runs_cleanup():
    calls = 0

    async def cancel():
        nonlocal calls
        calls += 1

    events = EventChannel("run", on_consumer_close=cancel).events()
    await events.aclose()

    assert calls == 1
