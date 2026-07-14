from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from mewcode.errors import ProviderError


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: dict[str, Any]


async def iter_sse_events(response: Any) -> AsyncIterator[SSEEvent]:
    event_name: str | None = None
    data_lines: list[str] = []

    def flush_event() -> tuple[SSEEvent | None, bool]:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None, False

        data_text = "\n".join(data_lines)
        event = event_name
        event_name = None
        data_lines = []
        if data_text == "[DONE]":
            return None, True
        try:
            data = json.loads(data_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Invalid SSE data: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ProviderError("Invalid SSE data: expected a JSON object.")
        return SSEEvent(event=event, data=data), False

    try:
        async for raw_line in response.aiter_lines():
            line = _to_text(raw_line)
            if line == "":
                event, done = flush_event()
                if done:
                    return
                if event is not None:
                    yield event
                continue
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].lstrip(" ")
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip(" "))

        event, done = flush_event()
        if not done and event is not None:
            yield event
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Failed to read SSE stream: {exc}") from exc


def _to_text(raw_line: str | bytes) -> str:
    if isinstance(raw_line, bytes):
        return raw_line.decode("utf-8").rstrip("\r")
    return raw_line.rstrip("\r")
