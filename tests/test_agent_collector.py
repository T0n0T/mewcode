import asyncio
from dataclasses import FrozenInstanceError

import pytest

from mewcode.agent.collector import ResponseCollector
from mewcode.cancellation import CancellationToken
from mewcode.errors import ProviderError
from mewcode.prompting import PromptPackage
from mewcode.providers.base import (
    ProviderRequest,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)


class FakeProvider:
    def __init__(self, events):
        self.events = events
        self.calls = []

    async def stream_response(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        for event in self.events:
            cancellation.raise_if_cancelled()
            if isinstance(event, BaseException):
                raise event
            yield event

    async def aclose(self):
        pass


async def collect(provider, on_text=None, on_stream_started=None):
    request = ProviderRequest(
        (),
        PromptPackage(
            "stable",
            "<system-reminder>dynamic</system-reminder>",
            (),
            "a" * 64,
        ),
    )
    return await ResponseCollector(provider).collect(
        request,
        run_id="run-1",
        iteration=2,
        cancellation=CancellationToken(),
        on_text=on_text or (lambda _text: asyncio.sleep(0)),
        on_stream_started=on_stream_started or (lambda: asyncio.sleep(0)),
    )


@pytest.mark.asyncio
async def test_provider_request_is_forwarded_unchanged_with_separate_cancellation():
    provider = FakeProvider([ProviderResponseCompleted([])])
    cancellation = CancellationToken()
    request = ProviderRequest(
        (),
        PromptPackage(
            "stable",
            "<system-reminder>dynamic</system-reminder>",
            (),
            "b" * 64,
        ),
    )

    await ResponseCollector(provider).collect(
        request,
        run_id="run-1",
        iteration=1,
        cancellation=cancellation,
        on_text=lambda _text: asyncio.sleep(0),
        on_stream_started=lambda: asyncio.sleep(0),
    )

    assert provider.calls == [(request, cancellation)]
    with pytest.raises(FrozenInstanceError):
        request.history = ()


@pytest.mark.asyncio
async def test_text_is_streamed_with_backpressure_and_collected_in_order():
    seen = []
    first_text_seen = asyncio.Event()
    release = asyncio.Event()

    async def on_text(text):
        seen.append(text)
        first_text_seen.set()
        if text == "A":
            await release.wait()

    task = asyncio.create_task(
        collect(
            FakeProvider(
                [
                    ProviderTextDelta("A"),
                    ProviderTextDelta("B"),
                    ProviderResponseCompleted([], TokenUsage(1, 2, 3)),
                ]
            ),
            on_text,
        )
    )
    await first_text_seen.wait()
    assert seen == ["A"]
    release.set()
    response = await task

    assert seen == ["A", "B"]
    assert response.text == "AB"
    assert response.usage == TokenUsage(1, 2, 3)


@pytest.mark.asyncio
async def test_stream_started_is_reported_once_for_a_tool_only_response():
    notifications = []

    async def on_stream_started():
        notifications.append("started")

    await collect(
        FakeProvider(
            [
                ProviderToolCallDelta(0, name_delta="read", arguments_delta="{}"),
                ProviderResponseCompleted([]),
            ]
        ),
        on_stream_started=on_stream_started,
    )

    assert notifications == ["started"]


@pytest.mark.asyncio
async def test_tool_calls_are_collected_by_slot_with_stable_fallback_ids():
    response = await collect(
        FakeProvider(
            [
                ProviderToolCallDelta(3, name_delta="second", arguments_delta="{"),
                ProviderToolCallDelta(1, call_id_delta="one", name_delta="first"),
                ProviderToolCallDelta(3, arguments_delta="}"),
                ProviderToolCallDelta(1, arguments_delta="{}"),
                ProviderResponseCompleted({"ok": True}),
            ]
        )
    )

    assert [
        (call.slot, call.call_id, call.name, call.arguments_text)
        for call in response.calls
    ] == [
        (1, "one", "first", "{}"),
        (3, "run-1:2:3", "second", "{}"),
    ]


@pytest.mark.asyncio
async def test_unstable_tool_call_slot_is_rejected():
    with pytest.raises(ProviderError, match="tool call slot"):
        await collect(
            FakeProvider(
                [
                    ProviderToolCallDelta(-1, name_delta="read", arguments_delta="{}"),
                    ProviderResponseCompleted([]),
                ]
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("events", "message"),
    [
        ([ProviderTextDelta("partial")], "without a completed event"),
        (
            [ProviderResponseCompleted([]), ProviderResponseCompleted([])],
            "more than one",
        ),
        (
            [ProviderResponseCompleted([]), ProviderTextDelta("late")],
            "after completion",
        ),
    ],
)
async def test_provider_protocol_errors_do_not_return_partial_response(events, message):
    with pytest.raises(ProviderError, match=message):
        await collect(FakeProvider(events))


@pytest.mark.asyncio
async def test_duplicate_id_is_rejected_without_a_collected_response():
    with pytest.raises(ProviderError, match="duplicate tool call ID"):
        await collect(
            FakeProvider(
                [
                    ProviderToolCallDelta(0, call_id_delta="same", name_delta="a"),
                    ProviderToolCallDelta(1, call_id_delta="same", name_delta="b"),
                    ProviderResponseCompleted([]),
                ]
            )
        )


@pytest.mark.asyncio
async def test_provider_id_cannot_collide_with_a_fallback_id():
    with pytest.raises(ProviderError, match="duplicate tool call ID"):
        await collect(
            FakeProvider(
                [
                    ProviderToolCallDelta(
                        1, call_id_delta="run-1:2:3", name_delta="first"
                    ),
                    ProviderToolCallDelta(3, name_delta="second"),
                    ProviderResponseCompleted([]),
                ]
            )
        )


@pytest.mark.asyncio
async def test_provider_error_leaves_forwarded_text_visible_but_no_response():
    seen = []

    async def on_text(text):
        seen.append(text)

    with pytest.raises(ProviderError, match="broken"):
        await collect(
            FakeProvider([ProviderTextDelta("partial"), ProviderError("broken")]),
            on_text,
        )
    assert seen == ["partial"]


@pytest.mark.asyncio
async def test_cancelled_stream_leaves_forwarded_text_visible_but_no_response():
    seen = []

    async def on_text(text):
        seen.append(text)

    with pytest.raises(asyncio.CancelledError):
        await collect(
            FakeProvider([ProviderTextDelta("partial"), asyncio.CancelledError()]),
            on_text,
        )

    assert seen == ["partial"]
