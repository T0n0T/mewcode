import pytest

from mewcode.errors import ProviderError
from mewcode.providers.base import ChatMessage
from mewcode.runtime import ChatRuntime


class FakeProvider:
    def __init__(self, chunks=None, error: Exception | None = None):
        self.chunks = chunks or ["hello", " world"]
        self.error = error
        self.calls = []

    def stream_chat(self, messages):
        self.calls.append(tuple(messages))
        for chunk in self.chunks:
            yield chunk
        if self.error is not None:
            raise self.error


def test_runtime_streams_chunks_and_appends_history():
    provider = FakeProvider()
    runtime = ChatRuntime(provider)

    chunks = list(runtime.stream_turn("Hi"))

    assert chunks == ["hello", " world"]
    assert runtime.messages == (
        ChatMessage(role="user", content="Hi"),
        ChatMessage(role="assistant", content="hello world"),
    )


def test_runtime_includes_previous_messages_on_next_turn():
    provider = FakeProvider(chunks=["first"])
    runtime = ChatRuntime(provider)
    list(runtime.stream_turn("One"))
    provider.chunks = ["second"]
    list(runtime.stream_turn("Two"))

    assert provider.calls[1] == (
        ChatMessage(role="user", content="One"),
        ChatMessage(role="assistant", content="first"),
        ChatMessage(role="user", content="Two"),
    )


def test_runtime_does_not_append_partial_assistant_message_on_failure():
    provider = FakeProvider(chunks=["partial"], error=ProviderError("bad network"))
    runtime = ChatRuntime(provider)

    with pytest.raises(ProviderError):
        list(runtime.stream_turn("Hi"))

    assert runtime.messages == (ChatMessage(role="user", content="Hi"),)
