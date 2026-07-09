import pytest

from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.providers import create_provider
from mewcode.providers.anthropic import AnthropicProvider
from mewcode.providers.base import ChatMessage
from mewcode.providers.openai import OpenAIProvider


class MockStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self.response

    def __exit__(self, exc_type, exc, traceback):
        return None


class MockResponse:
    def __init__(self, lines=None, status_code=200, text=""):
        self._lines = lines or []
        self.status_code = status_code
        self.text = text

    def iter_lines(self):
        yield from self._lines

    def read(self):
        return None


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


def test_factory_creates_openai_provider(openai_config):
    assert isinstance(create_provider(openai_config), OpenAIProvider)


def test_factory_creates_anthropic_provider(anthropic_config):
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


def test_openai_provider_builds_request_and_streams_text(openai_config):
    client = MockHTTPClient(
        MockResponse(
            [
                'data: {"type":"response.output_text.delta","delta":"Hel"}',
                "",
                'data: {"type":"response.output_text.delta","delta":"lo"}',
                "",
                "data: [DONE]",
                "",
            ]
        )
    )
    provider = OpenAIProvider(openai_config, http_client=client)

    chunks = list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))

    assert chunks == ["Hel", "lo"]
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == "https://api.openai.test/v1/responses"
    assert kwargs["headers"]["Authorization"] == "Bearer openai-secret"
    assert kwargs["json"] == {
        "model": "gpt-5-mini",
        "input": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }


def test_openai_provider_redaction_reports_errors_without_secret(openai_config):
    client = MockHTTPClient(MockResponse(status_code=401, text="bad openai-secret"))
    provider = OpenAIProvider(openai_config, http_client=client)

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))

    assert "openai-secret" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)


def test_openai_provider_handles_error_event(openai_config):
    client = MockHTTPClient(
        MockResponse(['event: error', 'data: {"error":{"message":"bad things"}}', ""])
    )
    provider = OpenAIProvider(openai_config, http_client=client)

    with pytest.raises(ProviderError, match="bad things"):
        list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))


def test_anthropic_provider_builds_request_with_thinking_and_streams_text(anthropic_config):
    client = MockHTTPClient(
        MockResponse(
            [
                'event: content_block_delta',
                'data: {"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hidden"}}',
                "",
                'event: content_block_delta',
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hi"}}',
                "",
                'event: content_block_delta',
                'data: {"type":"content_block_delta","delta":{"type":"signature_delta","signature":"sig"}}',
                "",
            ]
        )
    )
    provider = AnthropicProvider(anthropic_config, http_client=client)

    chunks = list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))

    assert chunks == ["Hi"]
    method, url, kwargs = client.calls[0]
    assert method == "POST"
    assert url == "https://api.anthropic.test/v1/messages"
    assert kwargs["headers"]["x-api-key"] == "anthropic-secret"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "Hi"}]
    assert kwargs["json"]["stream"] is True
    assert kwargs["json"]["thinking"]["type"] == "adaptive"
    assert kwargs["json"]["thinking"]["display"] == "omitted"


def test_anthropic_provider_omits_thinking_when_disabled(anthropic_config):
    config = LLMConfig(
        name=anthropic_config.name,
        protocol="anthropic",
        model=anthropic_config.model,
        base_url=anthropic_config.base_url,
        api_key=anthropic_config.api_key,
        thinking=False,
    )
    client = MockHTTPClient(MockResponse(["data: [DONE]", ""]))
    provider = AnthropicProvider(config, http_client=client)

    list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))

    assert "thinking" not in client.calls[0][2]["json"]


def test_anthropic_provider_redaction_reports_errors_without_secret(anthropic_config):
    client = MockHTTPClient(MockResponse(status_code=401, text="bad anthropic-secret"))
    provider = AnthropicProvider(anthropic_config, http_client=client)

    with pytest.raises(ProviderError) as exc_info:
        list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))

    assert "anthropic-secret" not in str(exc_info.value)
    assert "[redacted]" in str(exc_info.value)


def test_anthropic_provider_handles_error_event(anthropic_config):
    client = MockHTTPClient(
        MockResponse(['event: error', 'data: {"error":{"message":"rate limited"}}', ""])
    )
    provider = AnthropicProvider(anthropic_config, http_client=client)

    with pytest.raises(ProviderError, match="rate limited"):
        list(provider.stream_chat([ChatMessage(role="user", content="Hi")]))
