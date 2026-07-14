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


class OpenAIProvider:
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
        url = f"{self.config.base_url}/responses"
        body: dict[str, Any] = {
            "model": self.config.model,
            "input": _serialize_history(history),
            "stream": True,
        }
        if tools:
            body["tools"] = [_serialize_tool(tool) for tool in tools]
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        completed = False
        try:
            with self._stream("POST", url, headers=headers, json=body) as response:
                with cancellation.bind_stream_closer(_stream_closer(response)):
                    cancellation.raise_if_cancelled()
                    self._raise_for_status(response)
                    for event in iter_sse_events(response):
                        cancellation.raise_if_cancelled()
                        for provider_event in _events_from_response(event.data, event.event):
                            cancellation.raise_if_cancelled()
                            if isinstance(provider_event, ResponseCompleted):
                                if completed:
                                    raise ProviderError("OpenAI response emitted more than one completed event.")
                                completed = True
                            yield provider_event
        except TurnInterrupted:
            raise
        except ProviderError as exc:
            cancellation.raise_if_cancelled()
            raise ProviderError(redact_secrets(exc.user_message, [self.config.api_key])) from exc
        except httpx.HTTPError as exc:
            cancellation.raise_if_cancelled()
            message = redact_secrets(str(exc), [self.config.api_key])
            raise ProviderError(
                f"OpenAI request failed for {url}: {message}. Check that base_url is correct and the provider service is running."
            ) from exc

        cancellation.raise_if_cancelled()
        if not completed:
            raise ProviderError("OpenAI response ended without a completed event.")

    def _stream(self, method: str, url: str, **kwargs: Any) -> AbstractContextManager[Any]:
        if self._http_client is not None:
            return self._http_client.stream(method, url, **kwargs)
        client = httpx.Client(timeout=None)
        return _ClosingStreamContext(client, client.stream(method, url, **kwargs))

    def _raise_for_status(self, response: Any) -> None:
        status_code = getattr(response, "status_code", 200)
        if status_code < 400:
            return
        raise ProviderError(f"OpenAI API returned HTTP {status_code}: {_response_text(response)}")


def _serialize_tool(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


def _serialize_history(history: Sequence[ConversationMessage]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in history:
        if isinstance(message, UserMessage):
            items.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            if not isinstance(message.provider_state, list):
                raise ProviderError("OpenAI assistant protocol state is invalid.")
            items.extend(message.provider_state)
        elif isinstance(message, ToolResultsMessage):
            for feedback in message.results:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": feedback.call_id,
                        "output": json.dumps(
                            feedback.result.to_model_payload(),
                            ensure_ascii=False,
                            separators=(",", ":"),
                            sort_keys=True,
                        ),
                    }
                )
    return items


def _events_from_response(data: dict[str, Any], event_name: str | None) -> Iterator[ProviderEvent]:
    event_type = str(data.get("type") or event_name or "")
    if event_name == "error" or event_type == "error" or "error" in data:
        raise ProviderError(f"OpenAI API error: {_extract_error_message(data)}")
    if event_type == "response.failed":
        raise ProviderError(f"OpenAI response failed: {_extract_error_message(data)}")

    if event_type in {"response.output_text.delta", "response.text.delta"} or event_type.endswith(
        ".output_text.delta"
    ):
        delta = data.get("delta")
        if isinstance(delta, str):
            yield TextDelta(delta)
        return

    if event_type == "response.output_item.added":
        item = data.get("item")
        slot = data.get("output_index")
        if isinstance(item, dict) and item.get("type") == "function_call" and isinstance(slot, int):
            call_id = item.get("call_id")
            name = item.get("name")
            yield ToolCallDelta(
                slot,
                call_id_delta=call_id if isinstance(call_id, str) else "",
                name_delta=name if isinstance(name, str) else "",
            )
        return

    if event_type == "response.function_call_arguments.delta":
        slot = data.get("output_index")
        delta = data.get("delta")
        if isinstance(slot, int) and isinstance(delta, str):
            yield ToolCallDelta(slot, arguments_delta=delta)
        return

    if event_type == "response.completed":
        response = data.get("response")
        output = response.get("output") if isinstance(response, dict) else None
        if not isinstance(output, list):
            raise ProviderError("OpenAI completed response did not include an output list.")
        yield ResponseCompleted(output)


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


def _extract_error_message(data: dict[str, Any]) -> str:
    error = data.get("error")
    if isinstance(error, dict) and isinstance(error.get("message"), str):
        return error["message"]
    if isinstance(error, str):
        return error
    response = data.get("response")
    if isinstance(response, dict):
        nested = response.get("error")
        if isinstance(nested, dict) and isinstance(nested.get("message"), str):
            return nested["message"]
    return str(data)
