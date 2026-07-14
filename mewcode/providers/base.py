from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from mewcode.cancellation import CancellationToken
from mewcode.messages import (
    AssistantMessage,
    ConversationMessage,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.tools.base import ToolCall, ToolDefinition, ToolFeedback

ProviderProtocol = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


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


# Temporary migration aliases for the synchronous providers. They are removed
# when both concrete adapters move to the asynchronous contract.
TextDelta = ProviderTextDelta
ToolCallDelta = ProviderToolCallDelta
ResponseCompleted = ProviderResponseCompleted


ProviderEvent = ProviderTextDelta | ProviderToolCallDelta | ProviderResponseCompleted


class LLMProvider(Protocol):
    def stream_response(
        self,
        history: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        *,
        instructions: str,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        """Yield unified provider events for the given conversation."""

    async def aclose(self) -> None:
        """Release resources owned by the provider."""
