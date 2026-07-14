from __future__ import annotations

import asyncio


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        self._cancelled.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise asyncio.CancelledError

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()
