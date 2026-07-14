from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from mewcode.errors import ProviderError


@dataclass(frozen=True)
class SSEEvent:
    event: str | None
    data: dict[str, Any]


def stream_closer(response: Any) -> Callable[[], None]:
    closer = getattr(response, "close", None)
    return closer if callable(closer) else lambda: None


def iter_sse_events(response: Any) -> Iterator[SSEEvent]:
    event_name: str | None = None
    data_lines: list[str] = []

    def flush_event() -> SSEEvent | None:
        nonlocal event_name, data_lines
        if not data_lines:
            event_name = None
            return None

        data_text = "\n".join(data_lines)
        event = event_name
        event_name = None
        data_lines = []

        if data_text == "[DONE]":
            raise StopIteration

        try:
            data = json.loads(data_text)
        except json.JSONDecodeError as exc:
            raise ProviderError(f"Invalid SSE data: {exc.msg}") from exc

        if not isinstance(data, dict):
            raise ProviderError("Invalid SSE data: expected a JSON object.")
        return SSEEvent(event=event, data=data)

    try:
        for raw_line in response.iter_lines():
            line = _to_text(raw_line)
            if line == "":
                try:
                    event = flush_event()
                except StopIteration:
                    return
                if event is not None:
                    yield event
                continue

            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event_name = line[len("event:") :].lstrip(" ")
                continue
            if line.startswith("data:"):
                data_lines.append(line[len("data:") :].lstrip(" "))
                continue

        try:
            event = flush_event()
        except StopIteration:
            return
        if event is not None:
            yield event
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Failed to read SSE stream: {exc}") from exc


def _to_text(raw_line: str | bytes) -> str:
    if isinstance(raw_line, bytes):
        line = raw_line.decode("utf-8")
    else:
        line = raw_line
    return line.rstrip("\r")
