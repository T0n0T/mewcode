import pytest

from mewcode.errors import ProviderError
from mewcode.providers.sse import iter_sse_events


class LinesResponse:
    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        yield from self._lines


def test_iter_sse_events_parses_event_and_data():
    response = LinesResponse(
        [
            "event: response.output_text.delta",
            'data: {"type":"response.output_text.delta","delta":"Hi"}',
            "",
        ]
    )

    events = list(iter_sse_events(response))

    assert len(events) == 1
    assert events[0].event == "response.output_text.delta"
    assert events[0].data["delta"] == "Hi"


def test_iter_sse_events_merges_multiline_data():
    response = LinesResponse(
        [
            "event: example",
            'data: {"text":',
            'data: "hello"}',
            "",
        ]
    )

    events = list(iter_sse_events(response))

    assert events[0].data == {"text": "hello"}


def test_iter_sse_events_ignores_comments_and_stops_on_done():
    response = LinesResponse(
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

    events = list(iter_sse_events(response))

    assert len(events) == 1
    assert events[0].data == {"ok": True}


def test_iter_sse_events_rejects_non_json_data():
    response = LinesResponse(["data: not-json", ""])

    with pytest.raises(ProviderError, match="Invalid SSE data"):
        list(iter_sse_events(response))


def test_iter_sse_events_wraps_read_errors():
    class BrokenResponse:
        def iter_lines(self):
            raise RuntimeError("boom")
            yield ""

    with pytest.raises(ProviderError, match="Failed to read SSE stream"):
        list(iter_sse_events(BrokenResponse()))
