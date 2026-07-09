from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

ProviderProtocol = Literal["openai", "anthropic"]
ChatRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: ChatRole
    content: str


class LLMProvider(Protocol):
    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield displayable assistant text chunks for the given conversation."""
