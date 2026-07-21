from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

from mewcode.cancellation import CancellationToken
from mewcode.messages import ConversationMessage
from mewcode.prompting import PromptPackage

ProviderProtocol = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cache_read_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None


@dataclass(frozen=True)
class ProviderRequest:
    history: tuple[ConversationMessage, ...]
    prompt: PromptPackage


@dataclass(frozen=True)
class ProviderTextDelta:
    text: str


@dataclass(frozen=True)
class ProviderToolCallDelta:
    slot: int
    call_id_delta: str = ""
    name_delta: str = ""
    arguments_delta: str = ""


@dataclass(frozen=True)
class ProviderResponseCompleted:
    provider_state: object = field(repr=False)
    usage: TokenUsage = TokenUsage(None, None, None)


ProviderEvent = ProviderTextDelta | ProviderToolCallDelta | ProviderResponseCompleted


class LLMProvider(Protocol):
    def stream_response(
        self,
        request: ProviderRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield unified provider events for the given conversation."""

    async def aclose(self) -> None:
        """Release resources owned by the provider."""
