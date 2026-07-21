from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from mewcode.cancellation import CancellationToken
from mewcode.errors import ProviderError
from mewcode.providers.base import (
    LLMProvider,
    ProviderRequest,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)

TextSink = Callable[[str], Awaitable[None]]
StreamStartedSink = Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class RawToolCall:
    slot: int
    call_id: str
    name: str
    arguments_text: str


@dataclass(frozen=True)
class CollectedResponse:
    text: str
    provider_state: object = field(repr=False)
    usage: TokenUsage = TokenUsage(None, None, None)
    calls: tuple[RawToolCall, ...] = ()


class ResponseCollector:
    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def collect(
        self,
        request: ProviderRequest,
        *,
        run_id: str,
        iteration: int,
        cancellation: CancellationToken,
        on_text: TextSink,
        on_stream_started: StreamStartedSink,
    ) -> CollectedResponse:
        text_parts: list[str] = []
        calls: dict[int, list[str]] = {}
        completed: ProviderResponseCompleted | None = None
        stream_started = False

        async for event in self._provider.stream_response(
            request,
            cancellation=cancellation,
        ):
            cancellation.raise_if_cancelled()
            if not stream_started:
                stream_started = True
                await on_stream_started()
            if completed is not None:
                if isinstance(event, ProviderResponseCompleted):
                    raise ProviderError(
                        "Provider emitted more than one completed event."
                    )
                raise ProviderError("Provider emitted an event after completion.")
            if isinstance(event, ProviderTextDelta):
                text_parts.append(event.text)
                await on_text(event.text)
            elif isinstance(event, ProviderToolCallDelta):
                if (
                    not isinstance(event.slot, int)
                    or isinstance(event.slot, bool)
                    or event.slot < 0
                ):
                    raise ProviderError("Provider emitted an unstable tool call slot.")
                parts = calls.setdefault(event.slot, ["", "", ""])
                parts[0] += event.call_id_delta
                parts[1] += event.name_delta
                parts[2] += event.arguments_delta
            elif isinstance(event, ProviderResponseCompleted):
                if completed is not None:
                    raise ProviderError(
                        "Provider emitted more than one completed event."
                    )
                completed = event

        cancellation.raise_if_cancelled()
        if completed is None:
            raise ProviderError("Provider response ended without a completed event.")

        raw_calls = tuple(
            RawToolCall(
                slot,
                parts[0] or f"{run_id}:{iteration}:{slot}",
                parts[1],
                parts[2],
            )
            for slot, parts in sorted(calls.items())
        )
        call_ids = [call.call_id for call in raw_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ProviderError("Provider emitted a duplicate tool call ID.")
        return CollectedResponse(
            "".join(text_parts),
            completed.provider_state,
            completed.usage,
            raw_calls,
        )
