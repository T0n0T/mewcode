import json
import inspect
from dataclasses import FrozenInstanceError

import httpx
import pytest

from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.messages import (
    AssistantMessage,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.providers import create_provider
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import (
    LLMProvider,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    ResponseCompleted,
    TextDelta,
    TokenUsage,
    ToolCallDelta,
    ToolFeedback,
)
from mewcode.providers.openai import OpenAIProvider
from mewcode.tools.base import ToolDefinition, ToolResult
from mewcode.turns import TurnCancellation, TurnInterrupted


class MockStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, traceback):
        return None


class MockResponse:
    def __init__(self, lines=None, status_code=200, text="", on_line=None):
        self._lines = lines or []
        self.status_code = status_code
        self.text = text
        self.on_line = on_line
        self.close_calls = 0

    def iter_lines(self):
        for index, line in enumerate(self._lines):
            yield line
            if self.on_line is not None:
                self.on_line(index)

    def read(self):
        return None

    def close(self):
        self.close_calls += 1


class MockHTTPClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return MockStream(self.response)


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


def sse(data, event=None):
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.extend((f"data: {json.dumps(data, separators=(',', ':'))}", ""))
    return lines


def feedback():
    return ToolFeedback(
        "call-1",
        "read_file",
        ToolResult(status="success", data={"content": "hello"}),
    )


def collect_events(provider, history=(), tools=(), cancellation=None):
    return list(
        provider.stream_response(
            history,
            tools,
            cancellation or TurnCancellation(),
        )
    )


def test_base_types_hide_provider_state():
    state = {"secret": "protocol state"}
    assistant = AssistantMessage("hello", state)
    user = UserMessage("hello")
    results = ToolResultsMessage((feedback(),))
    completed = ResponseCompleted(state)

    assert "protocol state" not in repr(assistant)
    assert "protocol state" not in repr(completed)
    with pytest.raises(FrozenInstanceError):
        user.content = "changed"
    with pytest.raises(FrozenInstanceError):
        assistant.content = "changed"
    with pytest.raises(FrozenInstanceError):
        results.results = ()


def test_base_types_token_usage_and_protocol_are_async():
    state = {"secret": "provider state"}
    usage = TokenUsage(11, None, 19)
    completed = ProviderResponseCompleted(state, usage)

    assert ProviderTextDelta("hi").text == "hi"
    assert ProviderToolCallDelta(2, name_delta="read_file").slot == 2
    assert completed.usage == usage
    assert TokenUsage(None, None, None).total_tokens is None
    assert "provider state" not in repr(completed)
    with pytest.raises(FrozenInstanceError):
        usage.input_tokens = 0

    signature = inspect.signature(LLMProvider.stream_response)
    assert signature.parameters["instructions"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["cancellation"].kind is inspect.Parameter.KEYWORD_ONLY
    assert inspect.iscoroutinefunction(LLMProvider.aclose)


def test_factory_creates_both_providers(openai_config, anthropic_config):
    assert isinstance(create_provider(openai_config), OpenAIProvider)
    assert isinstance(create_provider(anthropic_config), AnthropicProvider)


def test_factory_rejects_unknown_protocol(openai_config):
    bad_config = LLMConfig(
        name=openai_config.name,
        protocol="other",  # type: ignore[arg-type]
        model=openai_config.model,
        base_url=openai_config.base_url,
        api_key=openai_config.api_key,
    )
    with pytest.raises(ProviderError, match="Unsupported protocol"):
        create_provider(bad_config)


def test_openai_tools_user_message_text_delta_and_completed(openai_config, tool_definition):
    output = [{"type": "message", "role": "assistant", "content": []}]
    lines = [
        *sse({"type": "response.output_text.delta", "delta": "Hi"}),
        *sse({"type": "response.completed", "response": {"output": output}}),
        "data: [DONE]",
        "",
    ]
    client = MockHTTPClient(MockResponse(lines))
    events = collect_events(
        OpenAIProvider(openai_config, http_client=client),
        [UserMessage("Hello")],
        [tool_definition],
    )

    assert events == [TextDelta("Hi"), ResponseCompleted(output)]
    method, url, kwargs = client.calls[0]
    assert (method, url) == ("POST", "https://api.openai.test/v1/responses")
    assert kwargs["json"]["input"] == [{"role": "user", "content": "Hello"}]
    assert kwargs["json"]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": tool_definition.input_schema,
        }
    ]


def test_openai_history_feedback_and_empty_tools(openai_config):
    state = [{"type": "function_call", "call_id": "call-1", "name": "read_file", "arguments": "{}"}]
    lines = sse({"type": "response.completed", "response": {"output": []}})
    client = MockHTTPClient(MockResponse(lines))
    provider = OpenAIProvider(openai_config, http_client=client)

    collect_events(
        provider,
        [UserMessage("read"), AssistantMessage("", state), ToolResultsMessage((feedback(),))],
        [],
    )

    body = client.calls[0][2]["json"]
    assert "tools" not in body
    assert body["input"][:2] == [{"role": "user", "content": "read"}, *state]
    tool_output = body["input"][2]
    assert tool_output["type"] == "function_call_output"
    assert tool_output["call_id"] == "call-1"
    assert json.loads(tool_output["output"])["status"] == "success"


def test_openai_tool_call_deltas_share_slot(openai_config):
    output = [{"type": "function_call", "call_id": "call-1", "name": "read_file", "arguments": '{"path":"a"}'}]
    lines = [
        *sse(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {"type": "function_call", "call_id": "call-1", "name": "read_file", "arguments": ""},
            }
        ),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"path":'}),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '"a"}'}),
        *sse({"type": "response.completed", "response": {"output": output}}),
    ]
    events = collect_events(OpenAIProvider(openai_config, MockHTTPClient(MockResponse(lines))))

    assert events[:3] == [
        ToolCallDelta(0, call_id_delta="call-1", name_delta="read_file"),
        ToolCallDelta(0, arguments_delta='{"path":'),
        ToolCallDelta(0, arguments_delta='"a"}'),
    ]


def test_openai_tool_deltas_keep_multiple_slots_separate(openai_config):
    lines = [
        *sse({"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "call_id": "one", "name": "first"}}),
        *sse({"type": "response.output_item.added", "output_index": 1, "item": {"type": "function_call", "call_id": "two", "name": "second"}}),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 0, "delta": "{}"}),
        *sse({"type": "response.function_call_arguments.delta", "output_index": 1, "delta": "{}"}),
        *sse({"type": "response.completed", "response": {"output": []}}),
    ]
    events = collect_events(OpenAIProvider(openai_config, MockHTTPClient(MockResponse(lines))))
    deltas = [event for event in events if isinstance(event, ToolCallDelta)]
    assert [event.slot for event in deltas] == [0, 1, 0, 1]


def test_openai_requires_completed_event(openai_config):
    client = MockHTTPClient(MockResponse([*sse({"type": "response.output_text.delta", "delta": "partial"}), "data: [DONE]", ""]))
    with pytest.raises(ProviderError, match="without a completed event"):
        collect_events(OpenAIProvider(openai_config, client))


def test_openai_redacts_http_and_stream_errors(openai_config):
    provider = OpenAIProvider(
        openai_config,
        MockHTTPClient(MockResponse(status_code=401, text="bad openai-secret")),
    )
    with pytest.raises(ProviderError) as exc_info:
        collect_events(provider)
    assert "openai-secret" not in str(exc_info.value)

    client = MockHTTPClient(MockResponse(sse({"type": "error", "error": {"message": "bad things"}}, "error")))
    with pytest.raises(ProviderError, match="bad things"):
        collect_events(OpenAIProvider(openai_config, client))


def test_openai_connection_error_has_url_hint(openai_config):
    class FailingHTTPClient:
        def stream(self, method, url, **kwargs):
            raise httpx.ConnectError("connection refused", request=httpx.Request(method, url))

    with pytest.raises(ProviderError) as exc_info:
        collect_events(OpenAIProvider(openai_config, FailingHTTPClient()))
    assert "https://api.openai.test/v1/responses" in str(exc_info.value)
    assert "base_url" in str(exc_info.value)


def test_anthropic_tools_text_tool_delta_and_completed(anthropic_config, tool_definition):
    lines = [
        *sse({"type": "message_start", "message": {"content": []}}, "message_start"),
        *sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start"),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}}, "content_block_delta"),
        *sse({"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "call-1", "name": "read_file", "input": {}}}, "content_block_start"),
        *sse({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": '{"path":"a"}'}}, "content_block_delta"),
        *sse({"type": "message_stop"}, "message_stop"),
    ]
    client = MockHTTPClient(MockResponse(lines))
    events = collect_events(
        AnthropicProvider(anthropic_config, client),
        [UserMessage("Hello")],
        [tool_definition],
    )

    assert events[:3] == [
        TextDelta("Hi"),
        ToolCallDelta(1, call_id_delta="call-1", name_delta="read_file"),
        ToolCallDelta(1, arguments_delta='{"path":"a"}'),
    ]
    assert isinstance(events[-1], ResponseCompleted)
    body = client.calls[0][2]["json"]
    assert body["messages"] == [{"role": "user", "content": "Hello"}]
    assert body["tools"][0]["input_schema"] == tool_definition.input_schema
    assert body["thinking"] == {"type": "adaptive", "display": "omitted"}


def test_anthropic_tool_deltas_keep_multiple_slots_separate(anthropic_config):
    lines = [
        *sse({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "one", "name": "first", "input": {}}}),
        *sse({"type": "content_block_start", "index": 2, "content_block": {"type": "tool_use", "id": "two", "name": "second", "input": {}}}),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
        *sse({"type": "content_block_delta", "index": 2, "delta": {"type": "input_json_delta", "partial_json": "{}"}}),
        *sse({"type": "message_stop"}),
    ]
    events = collect_events(AnthropicProvider(anthropic_config, MockHTTPClient(MockResponse(lines))))
    deltas = [event for event in events if isinstance(event, ToolCallDelta)]
    assert [event.slot for event in deltas] == [0, 2, 0, 2]


def test_anthropic_history_feedback_merges_adjacent_user_content(anthropic_config):
    blocks = [{"type": "tool_use", "id": "call-1", "name": "read_file", "input": {"path": "a"}}]
    client = MockHTTPClient(MockResponse(sse({"type": "message_stop"}, "message_stop")))
    collect_events(
        AnthropicProvider(anthropic_config, client),
        [
            AssistantMessage("", blocks),
            ToolResultsMessage((feedback(),)),
            UserMessage("continue"),
        ],
        [],
    )

    body = client.calls[0][2]["json"]
    assert "tools" not in body
    assert body["messages"][0] == {"role": "assistant", "content": blocks}
    user_content = body["messages"][1]["content"]
    assert user_content[0]["type"] == "tool_result"
    assert user_content[0]["tool_use_id"] == "call-1"
    assert user_content[1] == {"type": "text", "text": "continue"}


def test_anthropic_thinking_is_preserved_but_not_displayed(anthropic_config):
    lines = [
        *sse({"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}}, "content_block_start"),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hidden"}}, "content_block_delta"),
        *sse({"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig"}}, "content_block_delta"),
        *sse({"type": "message_stop"}, "message_stop"),
    ]
    events = collect_events(AnthropicProvider(anthropic_config, MockHTTPClient(MockResponse(lines))))
    assert events == [ResponseCompleted([{"type": "thinking", "thinking": "hidden", "signature": "sig"}])]


def test_anthropic_requires_message_stop_and_redacts_errors(anthropic_config):
    client = MockHTTPClient(MockResponse(sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "partial"}})))
    with pytest.raises(ProviderError, match="without a completed event"):
        collect_events(AnthropicProvider(anthropic_config, client))

    client = MockHTTPClient(MockResponse(status_code=401, text="bad anthropic-secret"))
    with pytest.raises(ProviderError) as exc_info:
        collect_events(AnthropicProvider(anthropic_config, client))
    assert "anthropic-secret" not in str(exc_info.value)


def test_anthropic_omits_thinking_when_disabled(anthropic_config):
    config = LLMConfig(
        name=anthropic_config.name,
        protocol="anthropic",
        model=anthropic_config.model,
        base_url=anthropic_config.base_url,
        api_key=anthropic_config.api_key,
        thinking=False,
    )
    client = MockHTTPClient(MockResponse(sse({"type": "message_stop"}, "message_stop")))
    collect_events(AnthropicProvider(config, client))
    assert "thinking" not in client.calls[0][2]["json"]


def test_openai_cancellation_stops_before_request_and_closes_active_stream(openai_config):
    cancellation = TurnCancellation()
    client = MockHTTPClient(MockResponse(sse({"type": "response.completed", "response": {"output": []}})))
    cancellation.cancel()

    with pytest.raises(TurnInterrupted):
        collect_events(OpenAIProvider(openai_config, client), cancellation=cancellation)
    assert client.calls == []

    cancellation = TurnCancellation()
    response = MockResponse(
        sse({"type": "response.output_text.delta", "delta": "partial"}),
        on_line=lambda index: cancellation.cancel() if index == 0 else None,
    )
    with pytest.raises(TurnInterrupted):
        collect_events(
            OpenAIProvider(openai_config, MockHTTPClient(response)),
            cancellation=cancellation,
        )
    assert response.close_calls == 1


def test_anthropic_cancellation_stops_before_request_and_closes_active_stream(anthropic_config):
    cancellation = TurnCancellation()
    client = MockHTTPClient(MockResponse(sse({"type": "message_stop"})))
    cancellation.cancel()

    with pytest.raises(TurnInterrupted):
        collect_events(AnthropicProvider(anthropic_config, client), cancellation=cancellation)
    assert client.calls == []

    cancellation = TurnCancellation()
    response = MockResponse(
        sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "partial"}}),
        on_line=lambda index: cancellation.cancel() if index == 0 else None,
    )
    with pytest.raises(TurnInterrupted):
        collect_events(
            AnthropicProvider(anthropic_config, MockHTTPClient(response)),
            cancellation=cancellation,
        )
    assert response.close_calls == 1
