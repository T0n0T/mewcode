from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from contextlib import AbstractContextManager
from typing import Any

import httpx

from mewcode.config import LLMConfig
from mewcode.errors import ProviderError, redact_secrets
from mewcode.providers.base import (
    AssistantMessage,
    ConversationMessage,
    ProviderEvent,
    ResponseCompleted,
    TextDelta,
    ToolCallDelta,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.providers.sse import iter_sse_events
from mewcode.tools.base import ToolDefinition
from mewcode.turns import TurnCancellation, TurnInterrupted

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider:
    def __init__(self, config: LLMConfig, http_client: Any | None = None):
        self.config = config
        self._http_client = http_client

    def stream_response(
        self,
        history: Sequence[ConversationMessage],
        tools: Sequence[ToolDefinition],
        cancellation: TurnCancellation,
    ) -> Iterator[ProviderEvent]:
        cancellation.raise_if_cancelled()
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": _serialize_history(history),
            "stream": True,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        if tools:
            body["tools"] = [_serialize_tool(tool) for tool in tools]
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
        completed = False
        url = f"{self.config.base_url}/messages"

        try:
            with self._stream("POST", url, headers=headers, json=body) as response:
                with cancellation.bind_stream_closer(_stream_closer(response)):
                    cancellation.raise_if_cancelled()
                    self._raise_for_status(response)
                    for event in iter_sse_events(response):
                        cancellation.raise_if_cancelled()
                        data = event.data
                        event_type = str(data.get("type") or event.event or "")
                        if event.event == "error" or event_type == "error":
                            raise ProviderError(f"Anthropic API error: {_extract_error_message(data)}")

                        if event_type == "content_block_start":
                            index = data.get("index")
                            block = data.get("content_block")
                            if isinstance(index, int) and isinstance(block, dict):
                                blocks[index] = dict(block)
                                if block.get("type") == "tool_use":
                                    call_id = block.get("id")
                                    name = block.get("name")
                                    argument_parts[index] = []
                                    yield ToolCallDelta(
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
                                yield TextDelta(text)
                            elif delta_type == "thinking_delta" and isinstance(delta.get("thinking"), str):
                                if block is not None:
                                    block["thinking"] = str(block.get("thinking", "")) + delta["thinking"]
                            elif delta_type == "signature_delta" and isinstance(delta.get("signature"), str):
                                if block is not None:
                                    block["signature"] = str(block.get("signature", "")) + delta["signature"]
                            elif delta_type == "input_json_delta" and isinstance(delta.get("partial_json"), str):
                                part = delta["partial_json"]
                                argument_parts.setdefault(index, []).append(part)
                                yield ToolCallDelta(index, arguments_delta=part)
                            continue

                        if event_type == "message_stop":
                            if completed:
                                raise ProviderError("Anthropic response emitted more than one completed event.")
                            for index, parts in argument_parts.items():
                                if index in blocks and parts:
                                    try:
                                        blocks[index]["input"] = json.loads("".join(parts))
                                    except json.JSONDecodeError:
                                        blocks[index]["input"] = {}
                            completed = True
                            yield ResponseCompleted([blocks[index] for index in sorted(blocks)])
        except TurnInterrupted:
            raise
        except ProviderError as exc:
            cancellation.raise_if_cancelled()
            raise ProviderError(redact_secrets(exc.user_message, [self.config.api_key])) from exc
        except httpx.HTTPError as exc:
            cancellation.raise_if_cancelled()
            message = redact_secrets(str(exc), [self.config.api_key])
            raise ProviderError(f"Anthropic request failed: {message}") from exc

        cancellation.raise_if_cancelled()
        if not completed:
            raise ProviderError("Anthropic response ended without a completed event.")

    def _stream(self, method: str, url: str, **kwargs: Any) -> AbstractContextManager[Any]:
        if self._http_client is not None:
            return self._http_client.stream(method, url, **kwargs)
        client = httpx.Client(timeout=None)
        return _ClosingStreamContext(client, client.stream(method, url, **kwargs))

    def _raise_for_status(self, response: Any) -> None:
        status_code = getattr(response, "status_code", 200)
        if status_code < 400:
            return
        raise ProviderError(f"Anthropic API returned HTTP {status_code}: {_response_text(response)}")


def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
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


def _append_message(messages: list[dict[str, Any]], role: str, content: str | list[dict[str, Any]]) -> None:
    if not messages or messages[-1]["role"] != role:
        messages.append({"role": role, "content": content})
        return
    previous = messages[-1]["content"]
    if isinstance(previous, str):
        previous = [{"type": "text", "text": previous}]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    messages[-1]["content"] = [*previous, *content]


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
        return str(getattr(response, "text", ""))
    except Exception:
        return ""


def _stream_closer(response: Any) -> Any:
    closer = getattr(response, "close", None)
    return closer if callable(closer) else lambda: None
