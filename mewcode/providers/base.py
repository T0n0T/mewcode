from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

from mewcode.tools.base import JSONValue, ToolDefinition, ToolResult
from mewcode.turns import TurnCancellation

ProviderProtocol = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str
    provider_state: object = field(repr=False)


@dataclass(frozen=True)
class ToolCallDelta:
    slot: int
    call_id_delta: str = ""
    name_delta: str = ""
    arguments_delta: str = ""


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, JSONValue]


@dataclass(frozen=True)
class ToolFeedback:
    call_id: str
    name: str
    result: ToolResult


@dataclass(frozen=True)
class ToolResultsMessage:
    results: tuple[ToolFeedback, ...]


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ResponseCompleted:
    provider_state: object = field(repr=False)


ConversationMessage = UserMessage | AssistantMessage | ToolResultsMessage
ProviderEvent = TextDelta | ToolCallDelta | ResponseCompleted


class LLMProvider(Protocol):
    def stream_response(
        self,
        history: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        cancellation: TurnCancellation,
    ) -> Iterator[ProviderEvent]:
        """Yield unified provider events for the given conversation."""
