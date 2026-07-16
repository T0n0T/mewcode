import asyncio
import inspect
import json
from dataclasses import FrozenInstanceError

import httpx
import pytest

from mewcode.cancellation import CancellationToken
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.messages import AssistantMessage, ToolResultsMessage, UserMessage
from mewcode.providers import create_provider
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import (
    LLMProvider,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)
from mewcode.providers.openai import OpenAIProvider
from mewcode.tools.base import ToolDefinition, ToolFeedback, ToolResult


class MockStream:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *_args):
        await self.response.aclose()


class MockResponse:
    def __init__(self, lines=None, status_code=200, text="", on_line=None):
        self._lines = lines or []
        self.status_code = status_code
        self.text = text
        self.on_line = on_line
        self.close_calls = 0

    async def aiter_lines(self):
        for index, line in enumerate(self._lines):
            yield line
            if self.on_line is not None:
                value = self.on_line(index)
                if inspect.isawaitable(value):
                    await value

    async def aread(self):
        return self.text.encode()

    async def aclose(self):
        self.close_calls += 1


class MockHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.close_calls = 0

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return MockStream(self.response)

    async def aclose(self):
        self.close_calls += 1


@pytest.fixture
def openai_config():
    return LLMConfig(
        name="openai-main",
        protocol="openai",
        model="gpt-5-mini",
        base_url="https://api.openai.test/v1",
        api_key="openai-secret",
    )


@pytest.fixture
def anthropic_config():
    return LLMConfig(
        name="claude-main",
        protocol="anthropic",
        model="claude-sonnet-4-5",
        base_url="https://api.anthropic.test/v1",
        api_key="anthropic-secret",
        thinking=True,
    )


@pytest.fixture
def tool_definition():
    return ToolDefinition(
        "read_file",
        "Read a file",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    )


@pytest.fixture
def no_proxy_env(monkeypatch):
    for name in (
        "ALL_PROXY",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "http_proxy",
        "https_proxy",
    ):
        monkeypatch.delenv(name, raising=False)


def sse(data, event=None):
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.extend((f"data: {json.dumps(data, separators=(',', ':'))}", ""))
    return lines


def feedback(call_id="call-1", content="hello"):
    return ToolFeedback(
        call_id,
        "read_file",
        ToolResult(status="success", data={"content": content}),
    )


async def collect_events(provider, history=(), tools=(), cancellation=None, instructions="mode"):
    return [
        event
        async for event in provider.stream_response(
            history,
            tools,
            instructions=instructions,
            cancellation=cancellation or CancellationToken(),
        )
    ]


def test_base_types_token_usage_and_protocol_are_async():
    state = {"secret": "provider state"}
    usage = TokenUsage(11, None, 19)
    completed = ProviderResponseCompleted(state, usage)

    assert ProviderTextDelta("hi").text == "hi"
    assert ProviderToolCallDelta(2, name_delta="read_file").slot == 2
    assert completed.usage == usage
    assert "provider state" not in repr(completed)
    with pytest.raises(FrozenInstanceError):
        usage.input_tokens = 0
    signature = inspect.signature(LLMProvider.stream_response)
    assert signature.parameters["instructions"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.iscoroutinefunction(LLMProvider.aclose)


@pytest.mark.asyncio
async def test_factory_creates_both_providers_and_rejects_unknown(
    openai_config, anthropic_config, no_proxy_env
):
    openai = create_provider(openai_config)
    anthropic = create_provider(anthropic_config)
    assert isinstance(openai, OpenAIProvider)
    assert isinstance(anthropic, AnthropicProvider)
    bad = LLMConfig("bad", "other", "model", "https://example.test", "secret")
    with pytest.raises(ProviderError, match="Unsupported protocol"):
        create_provider(bad)
    await openai.aclose()
    await anthropic.aclose()


@pytest.mark.asyncio
async def test_openai_request_instructions_text_delta_and_completed(
    openai_config, tool_definition
):
    output = [{"type": "message", "role": "assistant", "content": []}]
    response = {
        "output": output,
        "usage": {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
    }
    client = MockHTTPClient(
        MockResponse(
            [
                *sse({"type": "response.output_text.delta", "delta": "Hi"}),
                *sse({"type": "response.completed", "response": response}),
                "data: [DONE]",
                "",
            ]
        )
    )

    events = await collect_events(
        OpenAIProvider(openai_config, http_client=client),
        [UserMessage("Hello")],
        [tool_definition],
        instructions="execute safely",
    )

    assert events == [
        ProviderTextDelta("Hi"),
        ProviderResponseCompleted(output, TokenUsage(4, 2, 6)),
    ]
    method, url, kwargs = client.calls[0]
    assert (method, url) == ("POST", "https://api.openai.test/v1/responses")
    assert kwargs["json"]["instructions"] == "execute safely"
    assert kwargs["json"]["input"] == [{"role": "user", "content": "Hello"}]
    assert kwargs["json"]["tools"][0]["name"] == "read_file"


@pytest.mark.asyncio
async def test_openai_history_multiple_feedback_and_tool_deltas(openai_config):
    state = [
        {"type": "function_call", "call_id": "one", "name": "read_file", "arguments": "{}"},
        {"type": "function_call", "call_id": "two", "name": "read_file", "arguments": "{}"},
    ]
    lines = [
        *sse({"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "call_id": "one", "name": "first"}}),
        *sse({"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "call_id": "two", "name": "second"}}),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": "{}"}),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{}"}),
        *sse({"type": "response.completed", "response": {"output": []}}),
    ]
    client = MockHTTPClient(MockResponse(lines))
    events = await collect_events(
        OpenAIProvider(openai_config, client),
        [
            UserMessage("read"),
            AssistantMessage("", state),
            ToolResultsMessage((feedback("one", "a"), feedback("two", "b"))),
        ],
    )

    deltas = [event for event in events if isinstance(event, ProviderToolCallDelta)]
    assert [event.slot for event in deltas] == [0, 1, 0, 1]
    body = client.calls[0][2]["json"]
    assert [item["call_id"] for item in body["input"][-2:]] == ["one", "two"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"input_tokens": 1, "output_tokens": 2}, TokenUsage(1, 2, None)),
        ({"input_tokens": True, "output_tokens": -1, "total_tokens": "3"}, TokenUsage(None, None, None)),
        ({}, TokenUsage(None, None, None)),
    ],
)
async def test_openai_usage_validation(openai_config, raw, expected):
    client = MockHTTPClient(
        MockResponse(sse({"type": "response.completed", "response": {"output": [], "usage": raw}}))
    )
    events = await collect_events(OpenAIProvider(openai_config, client))
    assert events[-1].usage == expected


@pytest.mark.asyncio
async def test_openai_completed_protocol_errors_and_redaction(openai_config):
    for lines in (
        [*sse({"type": "response.output_text.delta", "delta": "partial"}), "data: [DONE]", ""],
        [*sse({"type": "response.completed", "response": {"output": []}}), *sse({"type": "response.completed", "response": {"output": []}})],
    ):
        with pytest.raises(ProviderError):
            await collect_events(OpenAIProvider(openai_config, MockHTTPClient(MockResponse(lines))))

    provider = OpenAIProvider(
        openai_config,
        MockHTTPClient(MockResponse(status_code=401, text="bad openai-secret")),
    )
    with pytest.raises(ProviderError) as exc_info:
        await collect_events(provider)
    assert "openai-secret" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_openai_cancellation_and_client_ownership(openai_config, no_proxy_env):
    cancelled = CancellationToken()
    cancelled.cancel()
    client = MockHTTPClient(MockResponse())
    with pytest.raises(asyncio.CancelledError):
        await collect_events(OpenAIProvider(openai_config, client), cancellation=cancelled)
    assert client.calls == []

    injected = OpenAIProvider(openai_config, client)
    await injected.aclose()
    assert client.close_calls == 0
    owned = OpenAIProvider(openai_config)
    owned_client = owned._http_client
    await owned.aclose()
    assert owned_client.is_closed


@pytest.mark.asyncio
async def test_anthropic_request_system_content_blocks_usage_and_completed(
    anthropic_config, tool_definition
):
    lines = [
        *sse({"type": "message_start", "message": {"content": [], "usage": {"input_tokens": 7}}}, "message_start"),
        *sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start"),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}}, "content_block_delta"),
        *sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {}}}, "content_block_start"),
        *sse({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a"}'}}, "content_block_delta"),
        *sse({"type": "message_delta", "delta": {}, "usage": {"output_tokens": 3}}, "message_delta"),
        *sse({"type": "message_stop"}, "message_stop"),
    ]
    client = MockHTTPClient(MockResponse(lines))
    events = await collect_events(
        AnthropicProvider(anthropic_config, client),
        [UserMessage("Hello")],
        [tool_definition],
        instructions="plan only",
    )

    assert events[:3] == [
        ProviderTextDelta("Hi"),
        ProviderToolCallDelta(1, call_id_delta="call-1", name_delta="read_file"),
        ProviderToolCallDelta(1, arguments_delta='{"path":"a"}'),
    ]
    assert events[-1].usage == TokenUsage(7, 3, None)
    body = client.calls[0][2]["json"]
    assert body["system"] == "plan only"
    assert body["thinking"] == {"type": "adaptive", "display": "omitted"}


@pytest.mark.asyncio
async def test_anthropic_thinking_multiple_tools_and_history(anthropic_config):
    blocks = [
        {"type": "tool_use", "id": "one", "name": "read_file", "input": {}},
        {"type": "tool_use", "id": "two", "name": "read_file", "input": {}},
    ]
    lines = [
        *sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hidden"}}),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}),
        *sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "one", "name": "first", "input": {}}}),
        *sse({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "two", "name": "second", "input": {}}}),
        *sse({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
        *sse({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
        *sse({"type": "message_stop"}),
    ]
    client = MockHTTPClient(MockResponse(lines))
    events = await collect_events(
        AnthropicProvider(anthropic_config, client),
        [
            AssistantMessage("", blocks),
            ToolResultsMessage((feedback("one"), feedback("two"))),
            UserMessage("continue"),
        ],
    )

    assert not any(isinstance(event, ProviderTextDelta) for event in events)
    assert events[-1].provider_state[0] == {
        "type": "thinking",
        "thinking": "hidden",
        "signature": "sig",
    }
    user_content = client.calls[0][2]["json"]["messages"][1]["content"]
    assert [block["tool_use_id"] for block in user_content[:2]] == ["one", "two"]


@pytest.mark.asyncio
async def test_anthropic_completed_errors_redaction_and_thinking_disabled(anthropic_config):
    with pytest.raises(ProviderError, match="without a completed event"):
        await collect_events(
            AnthropicProvider(
                anthropic_config,
                MockHTTPClient(MockResponse(sse({"type": "message_delta", "usage": {"output_tokens": 1}}))),
            )
        )
    duplicate = [*sse({"type": "message_stop"}), *sse({"type": "message_stop"})]
    with pytest.raises(ProviderError):
        await collect_events(AnthropicProvider(anthropic_config, MockHTTPClient(MockResponse(duplicate))))
    bad = AnthropicProvider(
        anthropic_config,
        MockHTTPClient(MockResponse(status_code=401, text="bad anthropic-secret")),
    )
    with pytest.raises(ProviderError) as exc_info:
        await collect_events(bad)
    assert "anthropic-secret" not in str(exc_info.value)

    config = LLMConfig(
        anthropic_config.name,
        anthropic_config.protocol,
        anthropic_config.model,
        anthropic_config.base_url,
        anthropic_config.api_key,
        thinking=False,
    )
    client = MockHTTPClient(MockResponse(sse({"type": "message_stop"})))
    await collect_events(AnthropicProvider(config, client))
    assert "thinking" not in client.calls[0][2]["json"]


@pytest.mark.asyncio
async def test_anthropic_cancellation_and_client_ownership(
    anthropic_config, no_proxy_env
):
    cancelled = CancellationToken()
    cancelled.cancel()
    client = MockHTTPClient(MockResponse())
    with pytest.raises(asyncio.CancelledError):
        await collect_events(AnthropicProvider(anthropic_config, client), cancellation=cancelled)
    assert client.calls == []

    injected = AnthropicProvider(anthropic_config, client)
    await injected.aclose()
    assert client.close_calls == 0
    owned = AnthropicProvider(anthropic_config)
    owned_client = owned._http_client
    await owned.aclose()
    assert owned_client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type", [OpenAIProvider, AnthropicProvider])
async def test_dual_provider_stream_cancellation_closes_response(
    provider_type, openai_config, anthropic_config
):
    token = CancellationToken()

    def cancel_after_first_line(_index):
        token.cancel()

    response = MockResponse(
        [*sse({"type": "response.output_text.delta", "delta": "partial"})]
        if provider_type is OpenAIProvider
        else [*sse({"type": "message_delta", "usage": {"output_tokens": 1}})],
        on_line=cancel_after_first_line,
    )
    config = openai_config if provider_type is OpenAIProvider else anthropic_config
    with pytest.raises(asyncio.CancelledError):
        await collect_events(provider_type(config, MockHTTPClient(response)), cancellation=token)
    assert response.close_calls == 1
