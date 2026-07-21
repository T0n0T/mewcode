import asyncio
from copy import deepcopy
import inspect
import json
from dataclasses import FrozenInstanceError

import httpx
import pytest

from mewcode.agent import AgentSession, RunStopped, StopReason, UsageReported
from mewcode.cancellation import CancellationToken
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.messages import AssistantMessage, ToolResultsMessage, UserMessage
from mewcode.prompting import PromptPackage
from mewcode.providers import create_provider
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import (
    LLMProvider,
    ProviderRequest,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)
from mewcode.providers.cache import is_unsupported_cache_hint
from mewcode.providers.openai import OpenAIProvider
from mewcode.tools.base import (
    PreparedToolAction,
    ToolAccess,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolFeedback,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


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
            if isinstance(line, BaseException):
                raise line
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


class SequentialMockHTTPClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []
        self.close_calls = 0

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return MockStream(next(self.responses))

    async def aclose(self):
        self.close_calls += 1


class RaisingHTTPClient:
    def __init__(self, error):
        self.error = error
        self.calls = []

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        raise self.error


class EchoTool:
    manages_own_timeout = False
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False

    def __init__(self, name):
        self.definition = ToolDefinition(
            name,
            name,
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.executions = 0

    async def prepare(self, arguments, context):
        return PreparedToolAction({}, None)

    async def execute(self, action, context):
        self.executions += 1
        return ToolResult(status="success", data={"name": self.definition.name})


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


def make_provider_request(
    history=(),
    tools=(),
    *,
    stable="mode",
    supplement="<system-reminder>dynamic context</system-reminder>",
    cache_identity="c" * 64,
):
    return ProviderRequest(
        tuple(history),
        PromptPackage(
            stable,
            supplement,
            tuple(tools),
            cache_identity,
        ),
    )


async def collect_events(
    provider,
    history=(),
    tools=(),
    cancellation=None,
    instructions="mode",
    request=None,
):
    provider_request = request or make_provider_request(
        history,
        tools,
        stable=instructions,
    )
    return [
        event
        async for event in provider.stream_response(
            provider_request,
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
    assert signature.parameters["request"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert signature.parameters["cancellation"].kind is inspect.Parameter.KEYWORD_ONLY
    assert "instructions" not in signature.parameters
    assert inspect.iscoroutinefunction(LLMProvider.aclose)


@pytest.mark.parametrize(
    ("status_code", "body", "field_name", "expected"),
    [
        (
            400,
            {
                "error": {
                    "code": "unsupported_parameter",
                    "param": "prompt_cache_key",
                    "message": "Unsupported parameter: prompt_cache_key",
                }
            },
            "prompt_cache_key",
            True,
        ),
        (
            422,
            {
                "errors": [
                    {
                        "loc": ["body", "cache_control"],
                        "msg": "field is not supported",
                    }
                ]
            },
            "cache_control",
            True,
        ),
        (
            400,
            {
                "error": {
                    "code": "invalid_value",
                    "param": "prompt_cache_key",
                    "message": "must be 64 characters",
                }
            },
            "prompt_cache_key",
            False,
        ),
        (
            400,
            {"error": {"message": "Unsupported parameter: another_field"}},
            "prompt_cache_key",
            False,
        ),
        (401, {"error": {"message": "prompt_cache_key unsupported"}}, "prompt_cache_key", False),
        (403, {"error": {"message": "cache_control unsupported"}}, "cache_control", False),
        (429, {"error": {"message": "cache_control unsupported"}}, "cache_control", False),
        (500, {"error": {"message": "cache_control unsupported"}}, "cache_control", False),
        (400, "prompt_cache_key is unsupported", "prompt_cache_key", False),
        (400, None, "prompt_cache_key", False),
    ],
)
def test_cache_hint_classifier_matrix(status_code, body, field_name, expected):
    assert is_unsupported_cache_hint(status_code, body, field_name) is expected


def test_cache_hint_classifier_does_not_expose_secret(capsys):
    secret = "sk-classifier-secret"
    body = {
        "error": {
            "message": f"invalid prompt_cache_key {secret}",
            "param": "prompt_cache_key",
        }
    }

    assert is_unsupported_cache_hint(400, body, "prompt_cache_key") is False
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


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
async def test_openai_prompt_mapping_text_delta_and_completed(
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
    assert kwargs["json"]["input"] == [
        {
            "role": "system",
            "content": "<system-reminder>dynamic context</system-reminder>",
        },
        {"role": "user", "content": "Hello"},
    ]
    assert kwargs["json"]["prompt_cache_key"] == "c" * 64
    assert kwargs["json"]["tools"][0]["name"] == "read_file"


@pytest.mark.asyncio
async def test_openai_prompt_mapping_keeps_stable_prefix_across_dynamic_inputs(
    openai_config,
    tool_definition,
):
    second_tool = ToolDefinition(
        "search_code",
        "Search code",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    requests = [
        make_provider_request(
            [UserMessage("first")],
            [tool_definition, second_tool],
            stable="stable instructions",
            supplement="<system-reminder>environment A</system-reminder>",
            cache_identity="d" * 64,
        ),
        make_provider_request(
            [UserMessage("second")],
            [tool_definition, second_tool],
            stable="stable instructions",
            supplement="<system-reminder>environment B</system-reminder>",
            cache_identity="d" * 64,
        ),
    ]
    bodies = []
    for request in requests:
        client = MockHTTPClient(
            MockResponse(
                sse(
                    {
                        "type": "response.completed",
                        "response": {"output": []},
                    }
                )
            )
        )
        await collect_events(
            OpenAIProvider(openai_config, client),
            request=request,
        )
        bodies.append(client.calls[0][2]["json"])

    assert bodies[0]["instructions"] == bodies[1]["instructions"]
    assert bodies[0]["prompt_cache_key"] == bodies[1]["prompt_cache_key"]
    assert bodies[0]["tools"] == bodies[1]["tools"]
    assert [tool["name"] for tool in bodies[0]["tools"]] == [
        "read_file",
        "search_code",
    ]
    assert bodies[0]["input"] != bodies[1]["input"]


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
        (
            {
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "input_tokens_details": {
                    "cached_tokens": 4,
                    "cache_write_tokens": 5,
                },
            },
            TokenUsage(1, 2, 3, 4, 5),
        ),
        (
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
            },
            TokenUsage(0, 0, 0, 0, 0),
        ),
        ({}, TokenUsage(None, None, None, None, None)),
    ],
)
async def test_openai_usage_missing_zero_and_positive(openai_config, raw, expected):
    client = MockHTTPClient(
        MockResponse(sse({"type": "response.completed", "response": {"output": [], "usage": raw}}))
    )
    events = await collect_events(OpenAIProvider(openai_config, client))
    assert events[-1].usage == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raw",
    [
        {"input_tokens": True},
        {"output_tokens": -1},
        {"total_tokens": 1.5},
        {"input_tokens": "1"},
        {"input_tokens_details": {"cached_tokens": False}},
        {"input_tokens_details": {"cache_write_tokens": -2}},
        {"input_tokens_details": []},
        None,
    ],
)
async def test_openai_usage_invalid_values_stop_completion(openai_config, raw):
    client = MockHTTPClient(
        MockResponse(
            sse(
                {
                    "type": "response.completed",
                    "response": {"output": [], "usage": raw},
                }
            )
        )
    )
    observed = []

    with pytest.raises(ProviderError, match="usage"):
        async for event in OpenAIProvider(
            openai_config,
            client,
        ).stream_response(
            make_provider_request(),
            cancellation=CancellationToken(),
        ):
            observed.append(event)

    assert not any(
        isinstance(event, ProviderResponseCompleted) for event in observed
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 422])
async def test_openai_cache_fallback_success(
    openai_config,
    tool_definition,
    status_code,
):
    rejection = {
        "error": {
            "code": "unsupported_parameter",
            "param": "prompt_cache_key",
            "message": "Unsupported parameter: prompt_cache_key",
        }
    }
    client = SequentialMockHTTPClient(
        [
            MockResponse(
                status_code=status_code,
                text=json.dumps(rejection),
            ),
            MockResponse(
                sse(
                    {
                        "type": "response.completed",
                        "response": {"output": []},
                    }
                )
            ),
        ]
    )
    request = make_provider_request(
        [UserMessage("hello")],
        [tool_definition],
        stable="stable",
        supplement="<system-reminder>dynamic</system-reminder>",
        cache_identity="e" * 64,
    )

    events = await collect_events(
        OpenAIProvider(openai_config, client),
        request=request,
    )

    assert events == [
        ProviderResponseCompleted([], TokenUsage(None, None, None))
    ]
    assert len(client.calls) == 2
    first = client.calls[0][2]["json"]
    second = client.calls[1][2]["json"]
    expected_second = dict(first)
    expected_second.pop("prompt_cache_key")
    assert second == expected_second
    assert request.prompt.cache_identity == "e" * 64


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (401, {"error": {"message": "unauthorized"}}),
        (429, {"error": {"message": "rate limited"}}),
        (400, {"error": {"message": "unknown model"}}),
        (
            422,
            {
                "error": {
                    "param": "prompt_cache_key",
                    "message": "must be 64 characters",
                }
            },
        ),
    ],
)
async def test_openai_cache_no_retry_for_non_cache_errors(
    openai_config,
    status_code,
    body,
):
    client = MockHTTPClient(
        MockResponse(status_code=status_code, text=json.dumps(body))
    )

    with pytest.raises(ProviderError):
        await collect_events(OpenAIProvider(openai_config, client))

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_openai_cache_no_retry_for_plain_text_or_stream_error(openai_config):
    plain_client = MockHTTPClient(
        MockResponse(
            status_code=400,
            text="prompt_cache_key is unsupported",
        )
    )
    with pytest.raises(ProviderError):
        await collect_events(OpenAIProvider(openai_config, plain_client))
    assert len(plain_client.calls) == 1

    stream_client = SequentialMockHTTPClient(
        [
            MockResponse(
                [
                    *sse(
                        {
                            "type": "response.output_text.delta",
                            "delta": "partial",
                        }
                    ),
                    *sse(
                        {
                            "type": "error",
                            "error": {
                                "message": (
                                    "prompt_cache_key is unsupported after streaming"
                                )
                            },
                        },
                        "error",
                    ),
                ]
            ),
            MockResponse(),
        ]
    )
    with pytest.raises(ProviderError):
        await collect_events(OpenAIProvider(openai_config, stream_client))
    assert len(stream_client.calls) == 1


@pytest.mark.asyncio
async def test_openai_cache_no_retry_for_network_error(openai_config):
    error = httpx.ConnectError("network unavailable")
    client = RaisingHTTPClient(error)

    with pytest.raises(ProviderError, match="network unavailable"):
        await collect_events(OpenAIProvider(openai_config, client))

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_openai_cache_no_retry_after_single_fallback(openai_config):
    rejection = json.dumps(
        {
            "error": {
                "param": "prompt_cache_key",
                "message": "prompt_cache_key is unsupported",
            }
        }
    )
    client = SequentialMockHTTPClient(
        [
            MockResponse(status_code=400, text=rejection),
            MockResponse(status_code=422, text=rejection),
        ]
    )

    with pytest.raises(ProviderError):
        await collect_events(OpenAIProvider(openai_config, client))

    assert len(client.calls) == 2


@pytest.mark.asyncio
async def test_openai_cache_redaction_and_completed_protocol_errors(openai_config):
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
async def test_anthropic_prompt_mapping_system_blocks_usage_and_completed(
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
    assert body["system"] == [
        {
            "type": "text",
            "text": "plan only",
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": "<system-reminder>dynamic context</system-reminder>",
        },
    ]
    assert body["tools"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["thinking"] == {"type": "adaptive", "display": "omitted"}


@pytest.mark.asyncio
async def test_anthropic_prompt_mapping_marks_only_last_tool_and_not_history(
    anthropic_config,
    tool_definition,
):
    second_tool = ToolDefinition(
        "search_code",
        "Search code",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )
    response_lines = sse({"type": "message_stop"}, "message_stop")
    bodies = []
    for tools, supplement in (
        ((), "<system-reminder>environment A</system-reminder>"),
        (
            (tool_definition,),
            "<system-reminder>environment B</system-reminder>",
        ),
        (
            (tool_definition, second_tool),
            "<system-reminder>environment C</system-reminder>",
        ),
    ):
        client = MockHTTPClient(MockResponse(response_lines))
        request = make_provider_request(
            [UserMessage("hello")],
            tools,
            stable="stable instructions",
            supplement=supplement,
            cache_identity="f" * 64,
        )
        await collect_events(
            AnthropicProvider(anthropic_config, client),
            request=request,
        )
        bodies.append(client.calls[0][2]["json"])

    assert "tools" not in bodies[0]
    assert bodies[0]["system"][0] == bodies[1]["system"][0]
    assert bodies[1]["system"][0] == bodies[2]["system"][0]
    assert bodies[0]["system"][1] != bodies[1]["system"][1]
    assert bodies[1]["tools"][0]["cache_control"] == {
        "type": "ephemeral"
    }
    assert "cache_control" not in bodies[2]["tools"][0]
    assert bodies[2]["tools"][1]["cache_control"] == {
        "type": "ephemeral"
    }
    assert [tool["name"] for tool in bodies[2]["tools"]] == [
        "read_file",
        "search_code",
    ]
    serialized_messages = json.dumps(bodies[2]["messages"])
    assert "environment C" not in serialized_messages


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_usage", "delta_usage", "expected"),
    [
        (
            {
                "input_tokens": 7,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 2,
            },
            {"output_tokens": 3},
            TokenUsage(7, 3, None, 5, 2),
        ),
        (
            {
                "input_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
            {"output_tokens": 0},
            TokenUsage(0, 0, None, 0, 0),
        ),
        ({}, {}, TokenUsage(None, None, None, None, None)),
    ],
)
async def test_anthropic_usage_missing_zero_positive_and_preserved(
    anthropic_config,
    input_usage,
    delta_usage,
    expected,
):
    lines = [
        *sse(
            {
                "type": "message_start",
                "message": {"content": [], "usage": input_usage},
            },
            "message_start",
        ),
        *sse(
            {
                "type": "message_start",
                "message": {"content": []},
            },
            "message_start",
        ),
        *sse(
            {
                "type": "message_delta",
                "delta": {},
                "usage": delta_usage,
            },
            "message_delta",
        ),
        *sse(
            {"type": "message_delta", "delta": {}},
            "message_delta",
        ),
        *sse({"type": "message_stop"}, "message_stop"),
    ]

    events = await collect_events(
        AnthropicProvider(
            anthropic_config,
            MockHTTPClient(MockResponse(lines)),
        )
    )

    assert events[-1].usage == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "usage"),
    [
        ("message_start", {"input_tokens": True}),
        ("message_start", {"cache_read_input_tokens": -1}),
        ("message_start", {"cache_creation_input_tokens": 1.5}),
        ("message_delta", {"output_tokens": "3"}),
        ("message_delta", []),
    ],
)
async def test_anthropic_usage_invalid_values_stop_completion(
    anthropic_config,
    event_type,
    usage,
):
    if event_type == "message_start":
        invalid = {
            "type": "message_start",
            "message": {"content": [], "usage": usage},
        }
    else:
        invalid = {
            "type": "message_delta",
            "delta": {},
            "usage": usage,
        }
    lines = [
        *sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            }
        ),
        *sse(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "partial"},
            }
        ),
        *sse(invalid, event_type),
        *sse({"type": "message_stop"}, "message_stop"),
    ]
    observed = []

    with pytest.raises(ProviderError, match="usage"):
        async for event in AnthropicProvider(
            anthropic_config,
            MockHTTPClient(MockResponse(lines)),
        ).stream_response(
            make_provider_request(),
            cancellation=CancellationToken(),
        ):
            observed.append(event)

    assert observed == [ProviderTextDelta("partial")]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 422])
async def test_anthropic_cache_fallback_success(
    anthropic_config,
    tool_definition,
    status_code,
):
    rejection = {
        "error": {
            "code": "unsupported_field",
            "field": "cache_control",
            "message": "cache_control is not supported",
        }
    }
    client = SequentialMockHTTPClient(
        [
            MockResponse(
                status_code=status_code,
                text=json.dumps(rejection),
            ),
            MockResponse(sse({"type": "message_stop"}, "message_stop")),
        ]
    )
    original_schema = deepcopy(tool_definition.input_schema)
    request = make_provider_request(
        [UserMessage("hello")],
        [tool_definition],
        stable="stable",
        supplement="<system-reminder>dynamic</system-reminder>",
    )

    events = await collect_events(
        AnthropicProvider(anthropic_config, client),
        request=request,
    )

    assert events == [
        ProviderResponseCompleted([], TokenUsage(None, None, None))
    ]
    assert len(client.calls) == 2
    first = client.calls[0][2]["json"]
    second = client.calls[1][2]["json"]
    expected_second = deepcopy(first)
    for block in expected_second["system"]:
        block.pop("cache_control", None)
    for tool in expected_second["tools"]:
        tool.pop("cache_control", None)
    assert second == expected_second
    assert all(
        "cache_control" not in block for block in second["system"]
    )
    assert all("cache_control" not in tool for tool in second["tools"])
    assert tool_definition.input_schema == original_schema


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (401, {"error": {"message": "unauthorized"}}),
        (429, {"error": {"message": "rate limited"}}),
        (400, {"error": {"message": "unknown model"}}),
        (
            422,
            {
                "error": {
                    "field": "cache_control",
                    "message": "must be an object",
                }
            },
        ),
    ],
)
async def test_anthropic_cache_no_retry_for_non_cache_errors(
    anthropic_config,
    status_code,
    body,
):
    client = MockHTTPClient(
        MockResponse(status_code=status_code, text=json.dumps(body))
    )

    with pytest.raises(ProviderError):
        await collect_events(AnthropicProvider(anthropic_config, client))

    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_anthropic_cache_no_retry_for_plain_stream_or_network_errors(
    anthropic_config,
):
    plain_client = MockHTTPClient(
        MockResponse(status_code=400, text="cache_control is unsupported")
    )
    with pytest.raises(ProviderError):
        await collect_events(AnthropicProvider(anthropic_config, plain_client))
    assert len(plain_client.calls) == 1

    stream_client = SequentialMockHTTPClient(
        [
            MockResponse(
                [
                    *sse(
                        {
                            "type": "content_block_start",
                            "index": 0,
                            "content_block": {"type": "text", "text": ""},
                        }
                    ),
                    *sse(
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {
                                "type": "text_delta",
                                "text": "partial",
                            },
                        }
                    ),
                    *sse(
                        {
                            "type": "error",
                            "error": {
                                "message": "cache_control is unsupported"
                            },
                        },
                        "error",
                    ),
                ]
            ),
            MockResponse(),
        ]
    )
    with pytest.raises(ProviderError):
        await collect_events(AnthropicProvider(anthropic_config, stream_client))
    assert len(stream_client.calls) == 1

    network_client = RaisingHTTPClient(
        httpx.ConnectError("network unavailable")
    )
    with pytest.raises(ProviderError, match="network unavailable"):
        await collect_events(
            AnthropicProvider(anthropic_config, network_client)
        )
    assert len(network_client.calls) == 1


@pytest.mark.asyncio
async def test_anthropic_cache_no_retry_after_single_fallback(
    anthropic_config,
):
    rejection = json.dumps(
        {
            "error": {
                "field": "cache_control",
                "message": "cache_control is unsupported",
            }
        }
    )
    client = SequentialMockHTTPClient(
        [
            MockResponse(status_code=400, text=rejection),
            MockResponse(status_code=422, text=rejection),
        ]
    )

    with pytest.raises(ProviderError):
        await collect_events(AnthropicProvider(anthropic_config, client))

    assert len(client.calls) == 2


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
async def test_anthropic_cache_redaction_completed_errors_and_thinking_disabled(
    anthropic_config,
):
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
async def test_e2e_dual_provider_stream_cancellation_closes_response(
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


@pytest.mark.asyncio
async def test_provider_request_e2e_same_request_normalizes_both_providers(
    openai_config,
    anthropic_config,
    tool_definition,
):
    request = make_provider_request(
        [UserMessage("inspect")],
        [tool_definition],
        stable="stable instructions",
        supplement="<system-reminder>dynamic context</system-reminder>",
        cache_identity="9" * 64,
    )
    original_schema = deepcopy(tool_definition.input_schema)
    openai_lines = [
        *sse(
            {
                "type": "response.output_item.added",
                "output_index": 0,
                "item": {
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "read_file",
                },
            }
        ),
        *sse(
            {
                "type": "response.function_call_arguments.delta",
                "output_index": 0,
                "delta": "{}",
            }
        ),
        *sse({"type": "response.output_text.delta", "delta": "Hi"}),
        *sse(
            {
                "type": "response.completed",
                "response": {
                    "output": [],
                    "usage": {
                        "input_tokens": 7,
                        "output_tokens": 3,
                        "input_tokens_details": {
                            "cached_tokens": 2,
                            "cache_write_tokens": 1,
                        },
                    },
                },
            }
        ),
    ]
    anthropic_lines = [
        *sse(
            {
                "type": "message_start",
                "message": {
                    "content": [],
                    "usage": {
                        "input_tokens": 7,
                        "cache_read_input_tokens": 2,
                        "cache_creation_input_tokens": 1,
                    },
                },
            },
            "message_start",
        ),
        *sse(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "call-1",
                    "name": "read_file",
                    "input": {},
                },
            },
            "content_block_start",
        ),
        *sse(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": "{}",
                },
            },
            "content_block_delta",
        ),
        *sse(
            {
                "type": "content_block_start",
                "index": 1,
                "content_block": {"type": "text", "text": ""},
            },
            "content_block_start",
        ),
        *sse(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Hi"},
            },
            "content_block_delta",
        ),
        *sse(
            {
                "type": "message_delta",
                "delta": {},
                "usage": {"output_tokens": 3},
            },
            "message_delta",
        ),
        *sse({"type": "message_stop"}, "message_stop"),
    ]

    openai_events = await collect_events(
        OpenAIProvider(
            openai_config,
            MockHTTPClient(MockResponse(openai_lines)),
        ),
        request=request,
    )
    anthropic_events = await collect_events(
        AnthropicProvider(
            anthropic_config,
            MockHTTPClient(MockResponse(anthropic_lines)),
        ),
        request=request,
    )

    assert openai_events[:-1] == anthropic_events[:-1]
    assert openai_events[-1].usage == TokenUsage(7, 3, None, 2, 1)
    assert anthropic_events[-1].usage == openai_events[-1].usage
    assert request.prompt.tools[0].input_schema == original_schema


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_provider_request_e2e_dual_provider_multi_round_multi_tool_usage_and_history(
    protocol,
    openai_config,
    anthropic_config,
    tmp_path,
):
    if protocol == "openai":
        first_state = [
            {
                "type": "function_call",
                "call_id": "one",
                "name": "first",
                "arguments": "{}",
            },
            {
                "type": "function_call",
                "call_id": "two",
                "name": "second",
                "arguments": "{}",
            },
        ]
        first_lines = [
            *sse(
                {
                    "type": "response.output_item.added",
                    "output_index": 0,
                    "item": {
                        "type": "function_call",
                        "call_id": "one",
                        "name": "first",
                    },
                }
            ),
            *sse(
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": {
                        "type": "function_call",
                        "call_id": "two",
                        "name": "second",
                    },
                }
            ),
            *sse(
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 0,
                    "delta": "{}",
                }
            ),
            *sse(
                {
                    "type": "response.function_call_arguments.delta",
                    "output_index": 1,
                    "delta": "{}",
                }
            ),
            *sse(
                {
                    "type": "response.completed",
                    "response": {
                        "output": first_state,
                        "usage": {
                            "input_tokens": 3,
                            "output_tokens": 4,
                            "total_tokens": 7,
                        },
                    },
                }
            ),
        ]
        second_lines = [
            *sse({"type": "response.output_text.delta", "delta": "done"}),
            *sse(
                {
                    "type": "response.completed",
                    "response": {
                        "output": [
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": [],
                            }
                        ],
                        "usage": {"input_tokens": 5},
                    },
                }
            ),
        ]
        provider_type = OpenAIProvider
        config = openai_config
        expected_first_usage = TokenUsage(3, 4, 7)
    else:
        first_lines = [
            *sse(
                {
                    "type": "message_start",
                    "message": {"content": [], "usage": {"input_tokens": 3}},
                },
                "message_start",
            ),
            *sse(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "one",
                        "name": "first",
                        "input": {},
                    },
                },
                "content_block_start",
            ),
            *sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": "{}",
                    },
                },
                "content_block_delta",
            ),
            *sse(
                {
                    "type": "content_block_start",
                    "index": 1,
                    "content_block": {
                        "type": "tool_use",
                        "id": "two",
                        "name": "second",
                        "input": {},
                    },
                },
                "content_block_start",
            ),
            *sse(
                {
                    "type": "content_block_delta",
                    "index": 1,
                    "delta": {
                        "type": "input_json_delta",
                        "partial_json": "{}",
                    },
                },
                "content_block_delta",
            ),
            *sse(
                {
                    "type": "message_delta",
                    "delta": {},
                    "usage": {"output_tokens": 4},
                },
                "message_delta",
            ),
            *sse({"type": "message_stop"}, "message_stop"),
        ]
        second_lines = [
            *sse(
                {
                    "type": "message_start",
                    "message": {"content": [], "usage": {"input_tokens": 5}},
                },
                "message_start",
            ),
            *sse(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
                "content_block_start",
            ),
            *sse(
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "done"},
                },
                "content_block_delta",
            ),
            *sse({"type": "message_stop"}, "message_stop"),
        ]
        provider_type = AnthropicProvider
        config = anthropic_config
        expected_first_usage = TokenUsage(3, 4, None)

    client = SequentialMockHTTPClient(
        [MockResponse(first_lines), MockResponse(second_lines)]
    )
    provider = provider_type(config, http_client=client)
    registry = ToolRegistry()
    tools = [EchoTool("first"), EchoTool("second")]
    for tool in tools:
        registry.register(tool)
    session = AgentSession(
        provider,
        registry,
        ToolExecutor(registry, Workspace(tmp_path), secrets=(config.api_key,)),
    )

    events = [event async for event in await session.start("use both tools")]
    usage = [event for event in events if isinstance(event, UsageReported)]

    assert isinstance(events[-1], RunStopped)
    assert events[-1].reason is StopReason.COMPLETED
    assert [tool.executions for tool in tools] == [1, 1]
    assert [event.current for event in usage] == [
        expected_first_usage,
        TokenUsage(5, None, None),
    ]
    assert usage[-1].cumulative == TokenUsage(8, None, None)
    assert len(client.calls) == 2
    if protocol == "openai":
        assert client.calls[0][2]["json"]["instructions"] == (
            client.calls[1][2]["json"]["instructions"]
        )
    else:
        assert client.calls[0][2]["json"]["system"][0] == (
            client.calls[1][2]["json"]["system"][0]
        )
    replay_body = client.calls[1][2]["json"]
    replay_json = json.dumps(replay_body)
    assert "one" in replay_json and "two" in replay_json
    assert config.api_key not in replay_json
    tool_messages = [
        message for message in session.history if isinstance(message, ToolResultsMessage)
    ]
    assert len(tool_messages) == 1
    assert [feedback.call_id for feedback in tool_messages[0].results] == [
        "one",
        "two",
    ]
    assert isinstance(session.history[-1], AssistantMessage)
    assert session.history[-1].content == "done"
