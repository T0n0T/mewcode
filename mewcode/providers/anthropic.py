from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from typing import Any

import httpx

from mewcode.config import LLMConfig
from mewcode.errors import ProviderError, redact_secrets
from mewcode.providers.base import ChatMessage
from mewcode.providers.sse import iter_sse_events

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider:
    def __init__(self, config: LLMConfig, http_client: Any | None = None):
        self.config = config
        self._http_client = http_client

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": message.role, "content": message.content} for message in messages],
            "stream": True,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if self.config.thinking:
            body["thinking"] = {
                "type": "adaptive",
                "display": "omitted",
            }

        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        try:
            with self._stream("POST", f"{self.config.base_url}/messages", headers=headers, json=body) as response:
                self._raise_for_status(response)
                for event in iter_sse_events(response):
                    yield from self._text_chunks_from_event(event.data, event.event)
        except ProviderError as exc:
            raise ProviderError(redact_secrets(exc.user_message, [self.config.api_key])) from exc
        except httpx.HTTPError as exc:
            message = redact_secrets(str(exc), [self.config.api_key])
            raise ProviderError(f"Anthropic request failed: {message}") from exc

    def _stream(self, method: str, url: str, **kwargs: Any) -> AbstractContextManager[Any]:
        if self._http_client is not None:
            return self._http_client.stream(method, url, **kwargs)
        client = httpx.Client(timeout=None)
        return _ClosingStreamContext(client, client.stream(method, url, **kwargs))

    def _raise_for_status(self, response: Any) -> None:
        status_code = getattr(response, "status_code", 200)
        if status_code < 400:
            return
        body = _response_text(response)
        raise ProviderError(f"Anthropic API returned HTTP {status_code}: {body}")

    def _text_chunks_from_event(self, data: dict[str, Any], event_name: str | None) -> Iterator[str]:
        event_type = str(data.get("type") or event_name or "")
        if event_name == "error" or event_type == "error":
            raise ProviderError(f"Anthropic API error: {_extract_error_message(data)}")

        if event_type != "content_block_delta":
            return
        delta = data.get("delta")
        if not isinstance(delta, dict) or delta.get("type") != "text_delta":
            return
        text = delta.get("text")
        if isinstance(text, str):
            yield text


def _extract_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    return str(data)


class _ClosingStreamContext:
    def __init__(self, client: httpx.Client, stream_context: AbstractContextManager[Any]):
        self._client = client
        self._stream_context = stream_context

    def __enter__(self) -> Any:
        return self._stream_context.__enter__()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool | None:
        try:
            return self._stream_context.__exit__(exc_type, exc, traceback)
        finally:
            self._client.close()


def _response_text(response: Any) -> str:
    try:
        read = getattr(response, "read", None)
        if callable(read):
            read()
        text = getattr(response, "text", "")
        return str(text)
    except Exception:
        return ""
