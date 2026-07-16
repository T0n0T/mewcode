from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace

from mewcode.agent.events import AgentEvent, EventContext, RunStopped


class EventChannel:
    def __init__(
        self,
        run_id: str,
        *,
        capacity: int = 64,
        on_consumer_close: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("Event channel capacity must be at least 1.")
        self.run_id = run_id
        self._queue: asyncio.Queue[tuple[AgentEvent, bool]] = asyncio.Queue(
            capacity + 2
        )
        self._ordinary_slots = asyncio.Semaphore(capacity)
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._terminal = False
        self._consumer_claimed = False
        self._on_consumer_close = on_consumer_close

    async def publish(self, event: AgentEvent) -> bool:
        if isinstance(event, RunStopped):
            return await self.stop(event)
        if self._terminal:
            return False
        await self._ordinary_slots.acquire()
        enqueued = False
        try:
            async with self._lock:
                if self._terminal:
                    return False
                self._sequence += 1
                contextualized = replace(
                    event,
                    context=replace(
                        event.context,
                        run_id=self.run_id,
                        sequence=self._sequence,
                    ),
                )
                self._queue.put_nowait((contextualized, True))
                enqueued = True
                return True
        finally:
            if not enqueued:
                self._ordinary_slots.release()

    async def stop(
        self,
        event: RunStopped,
        *,
        before: AgentEvent | None = None,
    ) -> bool:
        if isinstance(before, RunStopped):
            raise ValueError("A terminal prelude cannot be RunStopped.")
        async with self._lock:
            if self._terminal:
                return False
            self._terminal = True
            if before is not None:
                self._sequence += 1
                contextualized_before = replace(
                    before,
                    context=replace(
                        before.context,
                        run_id=self.run_id,
                        sequence=self._sequence,
                    ),
                )
                self._queue.put_nowait((contextualized_before, False))
            self._sequence += 1
            contextualized = replace(
                event,
                context=replace(
                    event.context,
                    run_id=self.run_id,
                    sequence=self._sequence,
                ),
            )
            self._queue.put_nowait((contextualized, False))
            return True

    async def get(self) -> AgentEvent:
        event, uses_ordinary_slot = await self._queue.get()
        if uses_ordinary_slot:
            self._ordinary_slots.release()
        return event

    def events(self) -> _EventStream:
        if self._consumer_claimed:
            raise RuntimeError("An AgentRun permits only one consumer.")
        self._consumer_claimed = True
        return _EventStream(self)


class _EventStream(AsyncIterator[AgentEvent]):
    def __init__(self, channel: EventChannel) -> None:
        self._channel = channel
        self._closed = False
        self._terminal_seen = False
        self._close_lock = asyncio.Lock()

    def __aiter__(self) -> _EventStream:
        return self

    async def __anext__(self) -> AgentEvent:
        if self._closed or self._terminal_seen:
            self._closed = True
            raise StopAsyncIteration
        try:
            event = await self._channel.get()
        except asyncio.CancelledError:
            await self.aclose()
            raise
        if isinstance(event, RunStopped):
            self._terminal_seen = True
        return event

    async def aclose(self) -> None:
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            if not self._terminal_seen and self._channel._on_consumer_close is not None:
                await self._channel._on_consumer_close()


class ConfirmationBroker:
    def __init__(self, *, id_factory: Callable[[], str]) -> None:
        self._id_factory = id_factory
        self._pending: dict[str, asyncio.Future[bool]] = {}

    def create(self) -> tuple[str, asyncio.Future[bool]]:
        request_id = self._id_factory()
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        return request_id, future

    def resolve(self, request_id: str, approved: bool) -> bool:
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    def cancel_all(self) -> None:
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.cancel()
