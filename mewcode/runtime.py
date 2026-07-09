from __future__ import annotations

from collections.abc import Iterator

from mewcode.providers.base import ChatMessage, LLMProvider


class ChatRuntime:
    def __init__(self, provider: LLMProvider):
        self._provider = provider
        self._messages: list[ChatMessage] = []

    @property
    def messages(self) -> tuple[ChatMessage, ...]:
        return tuple(self._messages)

    def stream_turn(self, user_text: str) -> Iterator[str]:
        self._messages.append(ChatMessage(role="user", content=user_text))
        assistant_parts: list[str] = []

        for chunk in self._provider.stream_chat(tuple(self._messages)):
            assistant_parts.append(chunk)
            yield chunk

        self._messages.append(ChatMessage(role="assistant", content="".join(assistant_parts)))
