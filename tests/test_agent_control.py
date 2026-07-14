import asyncio

import pytest

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
