from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Sequence
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


class OpenAIProvider:
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
        url = f"{self.config.base_url}/responses"
        prompt = request.prompt
        body: dict[str, Any] = {
            "model": self.config.model,
            "input": [
                {"role": "system", "content": prompt.system_supplement},
                *_serialize_history(request.history),
            ],
            "instructions": prompt.stable_instructions,
            "prompt_cache_key": prompt.cache_identity,
            "stream": True,
        }
        if prompt.tools:
            body["tools"] = [_serialize_tool(tool) for tool in prompt.tools]
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        completed = False
        fallback_used = False
        request_body = body
        try:
            while True:
                try:
                    async with self._http_client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json=request_body,
                    ) as response:
                        cancellation.raise_if_cancelled()
                        await self._raise_for_status(response)
                        async for event in iter_sse_events(response):
                            cancellation.raise_if_cancelled()
                            for provider_event in _events_from_response(
                                event.data,
                                event.event,
                            ):
                                cancellation.raise_if_cancelled()
                                if isinstance(
                                    provider_event,
                                    ProviderResponseCompleted,
                                ):
                                    if completed:
                                        raise ProviderError(
                                            "OpenAI response emitted more than one "
                                            "completed event."
                                        )
                                    completed = True
                                elif completed:
                                    raise ProviderError(
                                        "OpenAI response emitted an event after completion."
                                    )
                                yield provider_event
                    break
                except _HTTPStatusError as exc:
                    cancellation.raise_if_cancelled()
                    if not fallback_used and is_unsupported_cache_hint(
                        exc.status_code,
                        exc.error_body,
                        "prompt_cache_key",
                    ):
                        fallback_used = True
                        request_body = dict(body)
                        request_body.pop("prompt_cache_key", None)
                        continue
                    raise ProviderError(
                        f"OpenAI API returned HTTP {exc.status_code}: "
                        f"{exc.response_text}"
                    ) from exc
        except ProviderError as exc:
            cancellation.raise_if_cancelled()
            raise ProviderError(
                redact_secrets(exc.user_message, [self.config.api_key])
            ) from exc
        except httpx.HTTPError as exc:
            cancellation.raise_if_cancelled()
            message = redact_secrets(str(exc), [self.config.api_key])
            raise ProviderError(
                f"OpenAI request failed for {url}: {message}. Check that base_url is "
                "correct and the provider service is running."
            ) from exc

        cancellation.raise_if_cancelled()
        if not completed:
            raise ProviderError("OpenAI response ended without a completed event.")

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
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": deepcopy(tool.input_schema),
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


def _events_from_response(
    data: dict[str, Any], event_name: str | None
) -> Iterator[ProviderEvent]:
    event_type = str(data.get("type") or event_name or "")
    if event_name == "error" or event_type == "error" or "error" in data:
        raise ProviderError(f"OpenAI API error: {_extract_error_message(data)}")
    if event_type == "response.failed":
        raise ProviderError(f"OpenAI response failed: {_extract_error_message(data)}")

    if event_type in {
        "response.output_text.delta",
        "response.text.delta",
    } or event_type.endswith(".output_text.delta"):
        delta = data.get("delta")
        if isinstance(delta, str):
            yield ProviderTextDelta(delta)
        return
    if event_type == "response.output_item.added":
        item = data.get("item")
        slot = data.get("output_index")
        if (
            isinstance(item, dict)
            and item.get("type") == "function_call"
            and isinstance(slot, int)
        ):
            call_id = item.get("call_id")
            name = item.get("name")
            yield ProviderToolCallDelta(
                slot,
                call_id_delta=call_id if isinstance(call_id, str) else "",
                name_delta=name if isinstance(name, str) else "",
            )
        return
    if event_type == "response.function_call_arguments.delta":
        slot = data.get("output_index")
        delta = data.get("delta")
        if isinstance(slot, int) and isinstance(delta, str):
            yield ProviderToolCallDelta(slot, arguments_delta=delta)
        return
    if event_type == "response.completed":
        response = data.get("response")
        output = response.get("output") if isinstance(response, dict) else None
        if not isinstance(output, list):
            raise ProviderError(
                "OpenAI completed response did not include an output list."
            )
        usage = response.get("usage", {}) if isinstance(response, dict) else {}
        yield ProviderResponseCompleted(output, _normalize_usage(usage))


def _normalize_usage(value: Any) -> TokenUsage:
    if isinstance(value, dict):
        usage = value
    else:
        raise ProviderError("OpenAI response usage must be an object.")
    details = _optional_usage_details(usage)
    return TokenUsage(
        _optional_non_negative_int(usage, "input_tokens"),
        _optional_non_negative_int(usage, "output_tokens"),
        _optional_non_negative_int(usage, "total_tokens"),
        _optional_non_negative_int(details, "cached_tokens"),
        _optional_non_negative_int(details, "cache_write_tokens"),
    )


def _optional_usage_details(usage: dict[str, Any]) -> dict[str, Any]:
    if "input_tokens_details" not in usage:
        return {}
    details = usage["input_tokens_details"]
    if not isinstance(details, dict):
        raise ProviderError(
            "OpenAI response usage field 'input_tokens_details' must be an object."
        )
    return details


def _optional_non_negative_int(
    values: dict[str, Any],
    field_name: str,
) -> int | None:
    if field_name not in values:
        return None
    value = values[field_name]
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    raise ProviderError(
        f"OpenAI response usage field '{field_name}' must be a non-negative integer."
    )


def _structured_error_body(response_text: str) -> object:
    try:
        return json.loads(response_text)
    except (json.JSONDecodeError, TypeError):
        return None


async def _response_text(response: Any) -> str:
    try:
        read = getattr(response, "aread", None)
        if callable(read):
            await read()
        return str(getattr(response, "text", ""))
    except Exception:
        return ""


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
