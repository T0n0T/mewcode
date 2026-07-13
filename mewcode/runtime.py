from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from mewcode.errors import ProviderError
from mewcode.providers.base import (
    AssistantMessage,
    ConversationMessage,
    LLMProvider,
    ResponseCompleted,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolFeedback,
    ToolResultsMessage,
    UserMessage,
)
from mewcode.tools.base import ToolErrorInfo, ToolResult
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry


@dataclass(frozen=True)
class _RawToolCall:
    slot: int
    call_id: str
    name: str
    arguments_text: str


@dataclass(frozen=True)
class _CollectedResponse:
    text: str
    provider_state: object
    calls: tuple[_RawToolCall, ...]


class ChatRuntime:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
    ):
        self._provider = provider
        self._registry = registry
        self._executor = executor
        self._history: list[ConversationMessage] = []

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._history)

    def stream_turn(self, user_text: str) -> Iterator[str]:
        self._history.append(UserMessage(user_text))
        first = yield from self._collect(self._registry.definitions())
        self._history.append(AssistantMessage(first.text, first.provider_state))
        if not first.calls:
            return

        feedback = self._feedback_for(first.calls)
        self._history.append(ToolResultsMessage(feedback))

        final = yield from self._collect(())
        if final.calls:
            self._executor.interaction.tool_budget_exhausted()
            return
        self._history.append(AssistantMessage(final.text, final.provider_state))

    def _collect(self, tools: Sequence) -> Iterator[str]:
        text_parts: list[str] = []
        calls: dict[int, list[str]] = {}
        provider_state: object | None = None
        completed = False

        for event in self._provider.stream_response(tuple(self._history), tools):
            if isinstance(event, TextDelta):
                text_parts.append(event.text)
                yield event.text
            elif isinstance(event, ToolCallDelta):
                parts = calls.setdefault(event.slot, ["", "", ""])
                parts[0] += event.call_id_delta
                parts[1] += event.name_delta
                parts[2] += event.arguments_delta
            elif isinstance(event, ResponseCompleted):
                if completed:
                    raise ProviderError("Provider emitted more than one completed event.")
                completed = True
                provider_state = event.provider_state

        if not completed:
            raise ProviderError("Provider response ended without a completed event.")
        raw_calls = tuple(
            _RawToolCall(slot, parts[0], parts[1], parts[2])
            for slot, parts in sorted(calls.items())
        )
        return _CollectedResponse("".join(text_parts), provider_state, raw_calls)

    def _feedback_for(self, calls: tuple[_RawToolCall, ...]) -> tuple[ToolFeedback, ...]:
        if len(calls) > 1:
            return tuple(
                ToolFeedback(
                    call.call_id or f"slot-{call.slot}",
                    call.name,
                    _error_result(
                        "multiple_tool_calls",
                        "Only one tool call is allowed per turn; no tools were executed.",
                    ),
                )
                for call in calls
            )

        raw = calls[0]
        try:
            arguments = json.loads(raw.arguments_text)
        except json.JSONDecodeError as exc:
            return (_invalid_arguments(raw, f"Tool arguments are not valid JSON: {exc.msg}."),)
        if not isinstance(arguments, dict):
            return (_invalid_arguments(raw, "Tool arguments must be a JSON object."),)

        call = ToolCall(raw.call_id or f"slot-{raw.slot}", raw.name, arguments)
        return (ToolFeedback(call.call_id, call.name, self._executor.execute(call)),)


def _invalid_arguments(raw: _RawToolCall, message: str) -> ToolFeedback:
    return ToolFeedback(
        raw.call_id or f"slot-{raw.slot}",
        raw.name,
        _error_result("invalid_tool_arguments", message),
    )


def _error_result(code: str, message: str) -> ToolResult:
    return ToolResult(
        status="error",
        error=ToolErrorInfo(code=code, message=message, retryable=True),
    )
