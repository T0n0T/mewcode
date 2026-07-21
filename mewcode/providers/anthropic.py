from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

import httpx

from mewcode.cancellation import CancellationToken
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError, redact_secrets
from mewcode.messages import (
    AssistantMessage,
    ConversationMessage,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.providers.base import (
    ProviderEvent,
    ProviderRequest,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)
from mewcode.providers.cache import is_unsupported_cache_hint
from mewcode.providers.sse import iter_sse_events
from mewcode.tools.base import ToolDefinition

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider:
    def __init__(self, config: LLMConfig, http_client: Any | None = None):
        self.config = config
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(timeout=None)
        self._closed = False

    async def stream_response(
        self,
        request: ProviderRequest,
        *,
        cancellation: CancellationToken,
    ) -> AsyncIterator[ProviderEvent]:
        cancellation.raise_if_cancelled()
        prompt = request.prompt
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": _serialize_history(request.history),
            "system": [
                {
                    "type": "text",
                    "text": prompt.stable_instructions,
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": prompt.system_supplement,
                },
            ],
            "stream": True,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if prompt.tools:
            serialized_tools = [_serialize_tool(tool) for tool in prompt.tools]
            serialized_tools[-1]["cache_control"] = {"type": "ephemeral"}
            body["tools"] = serialized_tools
        if self.config.thinking:
            body["thinking"] = {"type": "adaptive", "display": "omitted"}
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        blocks: dict[int, dict[str, Any]] = {}
        argument_parts: dict[int, list[str]] = {}
        input_tokens: int | None = None
        output_tokens: int | None = None
        cache_read_input_tokens: int | None = None
        cache_write_input_tokens: int | None = None
        completed = False
        url = f"{self.config.base_url}/messages"

        try:
            async with self._stream_with_cache_fallback(
                url,
                headers,
                body,
                cancellation,
            ) as response:
                async for event in iter_sse_events(response):
                    cancellation.raise_if_cancelled()
                    data = event.data
                    event_type = str(data.get("type") or event.event or "")
                    if completed:
                        raise ProviderError(
                            "Anthropic response emitted an event after completion."
                        )
                    if event.event == "error" or event_type == "error":
                        raise ProviderError(
                            f"Anthropic API error: {_extract_error_message(data)}"
                        )
                    if event_type == "message_start":
                        message = data.get("message")
                        usage = _optional_usage(
                            message,
                            context="message_start",
                        )
                        if usage is not None:
                            input_tokens = _merge_non_negative_int(
                                input_tokens,
                                usage,
                                "input_tokens",
                            )
                            cache_read_input_tokens = _merge_non_negative_int(
                                cache_read_input_tokens,
                                usage,
                                "cache_read_input_tokens",
                            )
                            cache_write_input_tokens = _merge_non_negative_int(
                                cache_write_input_tokens,
                                usage,
                                "cache_creation_input_tokens",
                            )
                        continue
                    if event_type == "message_delta":
                        usage = _optional_usage(
                            data,
                            context="message_delta",
                        )
                        if usage is not None:
                            output_tokens = _merge_non_negative_int(
                                output_tokens,
                                usage,
                                "output_tokens",
                            )
                        continue
                    if event_type == "content_block_start":
                        index = data.get("index")
                        block = data.get("content_block")
                        if isinstance(index, int) and isinstance(block, dict):
                            blocks[index] = dict(block)
                            if block.get("type") == "tool_use":
                                call_id = block.get("id")
                                name = block.get("name")
                                argument_parts[index] = []
                                yield ProviderToolCallDelta(
                                    index,
                                    call_id_delta=call_id if isinstance(call_id, str) else "",
                                    name_delta=name if isinstance(name, str) else "",
                                )
                        continue
                    if event_type == "content_block_delta":
                        index = data.get("index")
                        delta = data.get("delta")
                        if not isinstance(index, int) or not isinstance(delta, dict):
                            continue
                        block = blocks.get(index)
                        delta_type = delta.get("type")
                        if delta_type == "text_delta" and isinstance(delta.get("text"), str):
                            text = delta["text"]
                            if block is not None:
                                block["text"] = str(block.get("text", "")) + text
                            yield ProviderTextDelta(text)
                        elif delta_type == "thinking_delta" and isinstance(
                            delta.get("thinking"), str
                        ):
                            if block is not None:
                                block["thinking"] = str(block.get("thinking", "")) + delta["thinking"]
                        elif delta_type == "signature_delta" and isinstance(
                            delta.get("signature"), str
                        ):
                            if block is not None:
                                block["signature"] = str(block.get("signature", "")) + delta["signature"]
                        elif delta_type == "input_json_delta" and isinstance(
                            delta.get("partial_json"), str
                        ):
                            part = delta["partial_json"]
                            argument_parts.setdefault(index, []).append(part)
                            yield ProviderToolCallDelta(index, arguments_delta=part)
                        continue
                    if event_type == "message_stop":
                        for index, parts in argument_parts.items():
                            if index in blocks and parts:
                                try:
                                    blocks[index]["input"] = json.loads("".join(parts))
                                except json.JSONDecodeError:
                                    blocks[index]["input"] = {}
                        completed = True
                        yield ProviderResponseCompleted(
                            [blocks[index] for index in sorted(blocks)],
                            TokenUsage(
                                input_tokens,
                                output_tokens,
                                None,
                                cache_read_input_tokens,
                                cache_write_input_tokens,
                            ),
                        )
        except ProviderError as exc:
            cancellation.raise_if_cancelled()
            raise ProviderError(
                redact_secrets(exc.user_message, [self.config.api_key])
            ) from exc
        except httpx.HTTPError as exc:
            cancellation.raise_if_cancelled()
            message = redact_secrets(str(exc), [self.config.api_key])
            raise ProviderError(
                f"Anthropic request failed for {url}: {message}. Check that base_url is "
                "correct and the provider service is running."
            ) from exc

        cancellation.raise_if_cancelled()
        if not completed:
            raise ProviderError("Anthropic response ended without a completed event.")

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._http_client.aclose()

    async def _raise_for_status(self, response: Any) -> None:
        status_code = getattr(response, "status_code", 200)
        if status_code < 400:
            return
        response_text = await _response_text(response)
        raise _HTTPStatusError(
            status_code,
            _structured_error_body(response_text),
            response_text,
        )

    @asynccontextmanager
    async def _stream_with_cache_fallback(
        self,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        cancellation: CancellationToken,
    ):
        fallback_used = False
        request_body = body
        while True:
            async with self._http_client.stream(
                "POST",
                url,
                headers=headers,
                json=request_body,
            ) as response:
                cancellation.raise_if_cancelled()
                try:
                    await self._raise_for_status(response)
                except _HTTPStatusError as exc:
                    cancellation.raise_if_cancelled()
                    if not fallback_used and is_unsupported_cache_hint(
                        exc.status_code,
                        exc.error_body,
                        "cache_control",
                    ):
                        fallback_used = True
                        request_body = _without_cache_control(body)
                        continue
                    raise ProviderError(
                        f"Anthropic API returned HTTP {exc.status_code}: "
                        f"{exc.response_text}"
                    ) from exc
                yield response
                return


class _HTTPStatusError(Exception):
    def __init__(
        self,
        status_code: int,
        error_body: object,
        response_text: str,
    ) -> None:
        self.status_code = status_code
        self.error_body = error_body
        self.response_text = response_text
        super().__init__(f"HTTP {status_code}")


def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": deepcopy(tool.input_schema),
    }


def _serialize_history(history: Sequence[ConversationMessage]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in history:
        if isinstance(message, UserMessage):
            _append_message(messages, "user", message.content)
        elif isinstance(message, AssistantMessage):
            if not isinstance(message.provider_state, list):
                raise ProviderError("Anthropic assistant protocol state is invalid.")
            _append_message(messages, "assistant", message.provider_state)
        elif isinstance(message, ToolResultsMessage):
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": feedback.call_id,
                    "content": json.dumps(
                        feedback.result.to_model_payload(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                }
                for feedback in message.results
            ]
            _append_message(messages, "user", content)
    return messages


def _append_message(
    messages: list[dict[str, Any]],
    role: str,
    content: str | list[dict[str, Any]],
) -> None:
    if not messages or messages[-1]["role"] != role:
        messages.append({"role": role, "content": content})
        return
    previous = messages[-1]["content"]
    if isinstance(previous, str):
        previous = [{"type": "text", "text": previous}]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    messages[-1]["content"] = [*previous, *content]


def _optional_usage(
    container: object,
    *,
    context: str,
) -> dict[str, Any] | None:
    if not isinstance(container, dict) or "usage" not in container:
        return None
    usage = container["usage"]
    if not isinstance(usage, dict):
        raise ProviderError(
            f"Anthropic {context} usage must be an object."
        )
    return usage


def _merge_non_negative_int(
    current: int | None,
    values: dict[str, Any],
    field_name: str,
) -> int | None:
    if field_name not in values:
        return current
    value = values[field_name]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ProviderError(
        f"Anthropic usage field '{field_name}' must be a non-negative integer."
    )


def _without_cache_control(body: dict[str, Any]) -> dict[str, Any]:
    fallback = deepcopy(body)
    system = fallback.get("system")
    if isinstance(system, list):
        for block in system:
            if isinstance(block, dict):
                block.pop("cache_control", None)
    tools = fallback.get("tools")
    if isinstance(tools, list):
        for tool in tools:
            if isinstance(tool, dict):
                tool.pop("cache_control", None)
    return fallback


def _structured_error_body(response_text: str) -> object:
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    return str(data)


async def _response_text(response: Any) -> str:
    try:
        read = getattr(response, "aread", None)
        if callable(read):
            await read()
        return str(getattr(response, "text", ""))
    except Exception:
        return ""
