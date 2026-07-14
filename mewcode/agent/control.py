from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import replace
from typing import cast

from mewcode.agent.events import AgentEvent, EventContext, RunStopped

_CLOSED = object()


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
        self._queue: asyncio.Queue[AgentEvent | object] = asyncio.Queue(capacity)
        self._lock = asyncio.Lock()
        self._sequence = 0
        self._terminal = False
        self._consumer_claimed = False
        self._on_consumer_close = on_consumer_close

    async def publish(self, event: AgentEvent) -> bool:
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
            await self._queue.put(contextualized)
            return True

    async def stop(self, event: RunStopped) -> bool:
        async with self._lock:
            if self._terminal:
                return False
            self._terminal = True
            self._sequence += 1
            contextualized = replace(
                event,
                context=replace(
                    event.context,
                    run_id=self.run_id,
                    sequence=self._sequence,
                ),
            )
            await self._queue.put(contextualized)
            await self._queue.put(_CLOSED)
            return True

    async def get(self) -> AgentEvent:
        item = await self._queue.get()
        if item is _CLOSED:
            raise StopAsyncIteration
        return cast(AgentEvent, item)

    def events(self) -> AsyncGenerator[AgentEvent, None]:
        if self._consumer_claimed:
            raise RuntimeError("An AgentRun permits only one consumer.")
        self._consumer_claimed = True
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[AgentEvent, None]:
        exhausted = False
        try:
            while True:
                item = await self._queue.get()
                if item is _CLOSED:
                    exhausted = True
                    return
                yield cast(AgentEvent, item)
        finally:
            if not exhausted and self._on_consumer_close is not None:
                await self._on_consumer_close()


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
