from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mewcode.tools.base import ToolFeedback


@dataclass(frozen=True)
class UserMessage:
    content: str


@dataclass(frozen=True)
class AssistantMessage:
    content: str
    provider_state: object = field(repr=False)


@dataclass(frozen=True)
class ToolResultsMessage:
    results: tuple[ToolFeedback, ...]


ConversationMessage = UserMessage | AssistantMessage | ToolResultsMessage
