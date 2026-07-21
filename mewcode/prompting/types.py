from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path

from mewcode.tools.base import ToolDefinition


class PromptChannel(StrEnum):
    CACHEABLE = "cacheable"
    SUPPLEMENTAL = "supplemental"


@dataclass(frozen=True)
class PromptSection:
    name: str
    priority: int
    channel: PromptChannel
    content: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        content = self.content.strip()
        if not name:
            raise ValueError("Prompt section name must not be empty.")
        if not content:
            raise ValueError("Prompt section content must not be empty.")
        if (
            not isinstance(self.priority, int)
            or isinstance(self.priority, bool)
            or self.priority <= 0
        ):
            raise ValueError("Prompt section priority must be a positive integer.")
        if not isinstance(self.channel, PromptChannel):
            raise ValueError("Prompt section channel is invalid.")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True)
class EnvironmentSnapshot:
    working_directory: Path
    platform: str
    shell: str
    current_date: date
    timezone: str


@dataclass(frozen=True)
class PromptOptions:
    custom_instructions: str | None = None
    active_skills: tuple[str, ...] = ()
    long_term_memory: str | None = None


@dataclass(frozen=True)
class PromptPackage:
    stable_instructions: str
    system_supplement: str
    tools: tuple[ToolDefinition, ...]
    cache_identity: str
