import asyncio

import pytest

from mewcode.errors import ProviderError
from mewcode.providers.sse import iter_sse_events


class LinesResponse:
    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line


async def collect(response):
    return [event async for event in iter_sse_events(response)]


@pytest.mark.asyncio
async def test_iter_sse_events_parses_event_and_data():
    events = await collect(
        LinesResponse(
            [
                "event: response.output_text.delta",
                'data: {"type":"response.output_text.delta","delta":"Hi"}',
                "",
            ]
        )
    )

    assert len(events) == 1
    assert events[0].event == "response.output_text.delta"
    assert events[0].data["delta"] == "Hi"


@pytest.mark.asyncio
async def test_iter_sse_events_merges_multiline_data_and_flushes_eof():
    events = await collect(
        LinesResponse(["event: example", 'data: {"text":', 'data: "hello"}'])
    )

    assert events[0].data == {"text": "hello"}


@pytest.mark.asyncio
async def test_iter_sse_events_ignores_comments_and_stops_on_done():
    events = await collect(
        LinesResponse(
            [
                ": keep-alive",
                'data: {"ok": true}',
                "",
                "data: [DONE]",
                "",
                'data: {"ok": false}',
                "",
            ]
        )
    )

    assert [event.data for event in events] == [{"ok": True}]


@pytest.mark.asyncio
@pytest.mark.parametrize("data", ["not-json", "[]", "null"])
async def test_iter_sse_events_rejects_invalid_data(data):
    with pytest.raises(ProviderError, match="Invalid SSE data"):
        await collect(LinesResponse([f"data: {data}", ""]))


@pytest.mark.asyncio
async def test_iter_sse_events_wraps_read_errors():
    class BrokenResponse:
        async def aiter_lines(self):
            raise RuntimeError("boom")
            yield ""

    with pytest.raises(ProviderError, match="Failed to read SSE stream"):
        await collect(BrokenResponse())


@pytest.mark.asyncio
async def test_iter_sse_events_propagates_cancellation_and_stops_output():
    release = asyncio.Event()

    class BlockingResponse:
        async def aiter_lines(self):
            yield 'data: {"first": true}'
            yield ""
            await release.wait()
            yield 'data: {"late": true}'
            yield ""

    events = iter_sse_events(BlockingResponse())
    assert (await anext(events)).data == {"first": True}
    task = asyncio.create_task(anext(events))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    with pytest.raises(StopAsyncIteration):
        await anext(events)
