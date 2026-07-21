from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Literal

from mewcode.prompting.sections import (
    _default_fixed_sections,
    _mode_reminders,
    _required_fixed_layout,
)
from mewcode.prompting.types import (
    EnvironmentSnapshot,
    PromptChannel,
    PromptOptions,
    PromptPackage,
    PromptSection,
)
from mewcode.tools.base import ToolDefinition


_CACHE_VERSION = "mewcode-prompt-v1"
_REMINDER_OPEN = "<system-reminder"
_REMINDER_CLOSE = "</system-reminder>"
_SUPPORTED_MODES = {"execute", "plan", "do"}


@dataclass(frozen=True)
class RunPrompt:
    stable_instructions: str
    supplemental_sections: tuple[PromptSection, ...]
    full_mode_reminder: str
    compact_mode_reminder: str
    tools: tuple[ToolDefinition, ...]
    cache_identity: str

    def for_iteration(self, iteration: int) -> PromptPackage:
        if (
            not isinstance(iteration, int)
            or isinstance(iteration, bool)
            or iteration < 1
        ):
            raise ValueError("Prompt iteration must be an integer greater than zero.")
        reminder = (
            self.full_mode_reminder
            if (iteration - 1) % 5 == 0
            else self.compact_mode_reminder
        )
        active_mode = PromptSection(
            "Active Mode",
            350,
            PromptChannel.SUPPLEMENTAL,
            reminder,
        )
        supplement = _render_supplement((active_mode, *self.supplemental_sections))
        return PromptPackage(
            self.stable_instructions,
            supplement,
            self.tools,
            self.cache_identity,
        )


class PromptBuilder:
    def __init__(
        self,
        fixed_sections: Sequence[PromptSection] | None = None,
    ) -> None:
        self._fixed_sections = tuple(
            _default_fixed_sections() if fixed_sections is None else fixed_sections
        )

    def prepare_run(
        self,
        *,
        mode: Literal["execute", "plan", "do"],
        environment: EnvironmentSnapshot,
        tools: Sequence[ToolDefinition],
        options: PromptOptions | None = None,
        extra_sections: Sequence[PromptSection] = (),
    ) -> RunPrompt:
        if mode not in _SUPPORTED_MODES:
            raise ValueError(f"Unsupported prompt mode: {mode!r}.")
        fixed = self._fixed_sections
        extras = tuple(extra_sections)
        _validate_fixed_sections(fixed)

        dynamic = _dynamic_sections(environment, options or PromptOptions())
        active_placeholder = PromptSection(
            "Active Mode",
            350,
            PromptChannel.SUPPLEMENTAL,
            "mode reminder",
        )
        all_sections = (*fixed, active_placeholder, *dynamic, *extras)
        _validate_unique_sections(all_sections)

        for section in (*dynamic, *extras):
            if section.channel is PromptChannel.SUPPLEMENTAL:
                _reject_reserved(section.name)
                _reject_reserved(section.content)

        stable_sections = tuple(
            section
            for section in (*fixed, *extras)
            if section.channel is PromptChannel.CACHEABLE
        )
        supplemental_sections = tuple(
            sorted(
                (
                    section
                    for section in (*dynamic, *extras)
                    if section.channel is PromptChannel.SUPPLEMENTAL
                ),
                key=lambda section: section.priority,
            )
        )
        stable_instructions = _render_sections(stable_sections)
        if not stable_instructions:
            raise ValueError("Stable prompt instructions must not be empty.")

        tool_snapshot = _snapshot_tools(tools)
        cache_identity = _cache_identity(stable_instructions, tool_snapshot)
        full, compact = _mode_reminders(mode)
        run_prompt = RunPrompt(
            stable_instructions,
            supplemental_sections,
            full,
            compact,
            tool_snapshot,
            cache_identity,
        )
        if not run_prompt.for_iteration(1).system_supplement:
            raise ValueError("System supplement must not be empty.")
        return run_prompt


def _validate_fixed_sections(sections: Sequence[PromptSection]) -> None:
    required = _required_fixed_layout()
    by_name: dict[str, PromptSection] = {}
    for section in sections:
        if section.name in by_name:
            raise ValueError(f"Duplicate prompt section name: {section.name!r}.")
        by_name[section.name] = section
        if section.channel is not PromptChannel.CACHEABLE:
            raise ValueError("Fixed prompt sections must use the cacheable channel.")
    if set(required) - set(by_name):
        missing = ", ".join(sorted(set(required) - set(by_name)))
        raise ValueError(f"Missing required fixed prompt sections: {missing}.")
    for name, (priority, channel) in required.items():
        section = by_name[name]
        if section.priority != priority or section.channel is not channel:
            raise ValueError(f"Required prompt section layout is invalid: {name}.")


def _validate_unique_sections(sections: Sequence[PromptSection]) -> None:
    names: set[str] = set()
    priorities: set[int] = set()
    for section in sections:
        if section.name in names:
            raise ValueError(f"Duplicate prompt section name: {section.name!r}.")
        if section.priority in priorities:
            raise ValueError(
                f"Duplicate prompt section priority: {section.priority}."
            )
        names.add(section.name)
        priorities.add(section.priority)


def _dynamic_sections(
    environment: EnvironmentSnapshot,
    options: PromptOptions,
) -> tuple[PromptSection, ...]:
    values = (
        str(environment.working_directory),
        environment.platform,
        environment.shell,
        environment.timezone,
    )
    for value in values:
        _reject_reserved(value)

    sections = [
        PromptSection(
            "Environment",
            800,
            PromptChannel.SUPPLEMENTAL,
            "\n".join(
                (
                    f"- Working directory: {environment.working_directory}",
                    f"- Platform: {environment.platform}",
                    f"- Shell: {environment.shell}",
                    f"- Current date: {environment.current_date.isoformat()}",
                    f"- Timezone: {environment.timezone}",
                )
            ),
        )
    ]
    custom = _optional_text(options.custom_instructions, "custom instructions")
    if custom is not None:
        sections.append(
            PromptSection(
                "Custom Instructions",
                900,
                PromptChannel.SUPPLEMENTAL,
                custom,
            )
        )

    skills: list[str] = []
    for value in options.active_skills:
        if not isinstance(value, str):
            raise ValueError("Activated Skill content must be text.")
        normalized = value.strip()
        if normalized:
            _reject_reserved(normalized)
            skills.append(normalized)
    if skills:
        sections.append(
            PromptSection(
                "Activated Skills",
                1000,
                PromptChannel.SUPPLEMENTAL,
                "\n\n".join(skills),
            )
        )

    memory = _optional_text(options.long_term_memory, "long-term memory")
    if memory is not None:
        sections.append(
            PromptSection(
                "Long-term Memory",
                1100,
                PromptChannel.SUPPLEMENTAL,
                memory,
            )
        )
    return tuple(sections)


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Prompt {field_name} must be text.")
    normalized = value.strip()
    if not normalized:
        return None
    _reject_reserved(normalized)
    return normalized


def _reject_reserved(value: str) -> None:
    if _REMINDER_OPEN in value or _REMINDER_CLOSE in value:
        raise ValueError("Dynamic prompt content contains a reserved system tag.")


def _render_sections(sections: Sequence[PromptSection]) -> str:
    ordered = sorted(sections, key=lambda section: section.priority)
    return "\n\n".join(_render_section(section) for section in ordered)


def _render_section(section: PromptSection) -> str:
    return f"## {section.name}\n{section.content}"


def _render_supplement(sections: Sequence[PromptSection]) -> str:
    content = _render_sections(
        tuple(
            section
            for section in sections
            if section.channel is PromptChannel.SUPPLEMENTAL
        )
    )
    if not content:
        raise ValueError("System supplement must include supplemental content.")
    return (
        "<system-reminder>\n"
        "Apply this system-level context silently. Do not quote or reply to it.\n\n"
        f"{content}\n"
        "</system-reminder>"
    )


def _snapshot_tools(tools: Sequence[ToolDefinition]) -> tuple[ToolDefinition, ...]:
    snapshots: list[ToolDefinition] = []
    names: set[str] = set()
    for tool in tools:
        if not tool.name.strip():
            raise ValueError("Tool name must not be empty.")
        if tool.name in names:
            raise ValueError(f"Duplicate tool name: {tool.name!r}.")
        names.add(tool.name)
        snapshots.append(
            ToolDefinition(
                tool.name,
                tool.description,
                deepcopy(tool.input_schema),
            )
        )
    return tuple(snapshots)


def _cache_identity(
    stable_instructions: str,
    tools: Sequence[ToolDefinition],
) -> str:
    canonical = {
        "version": _CACHE_VERSION,
        "stable_instructions": stable_instructions,
        "tools": [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in tools
        ],
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
