from __future__ import annotations

import asyncio
import fnmatch
import re
from collections.abc import Mapping

from mewcode.errors import ToolInputError
from mewcode.tools.base import (
    JSONValue,
    PreparedToolAction,
    ToolContext,
    ToolDefinition,
    ToolAccess,
    ToolExecutionPolicy,
    ToolResult,
)


def _schema(properties: dict[str, JSONValue], required: list[str]) -> dict[str, JSONValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _validate_pattern(pattern: str) -> None:
    if not pattern or pattern.startswith("/") or ".." in pattern.replace("\\", "/").split("/"):
        raise ToolInputError(
            "invalid_path_pattern",
            "Path patterns must be non-empty workspace-relative patterns without '..'.",
        )


class GlobFilesTool:
    definition = ToolDefinition(
        name="glob_files",
        description="Find workspace files matching a relative glob pattern.",
        input_schema=_schema(
            {"pattern": {"type": "string", "minLength": 1}},
            ["pattern"],
        ),
    )
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False
    manages_own_timeout = False

    async def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
        context.cancellation.raise_if_cancelled()
        context.deadline.check()
        pattern = str(arguments["pattern"])
        _validate_pattern(pattern)
        return PreparedToolAction(dict(arguments), None, pattern)

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        pattern = str(action.state)
        paths: list[str] = []
        async for path in context.workspace.walk_files(
            context.deadline, context.cancellation
        ):
            context.cancellation.raise_if_cancelled()
            relative = context.workspace.relative(path)
            if _glob_match(relative, pattern):
                paths.append(relative)
        return ToolResult(
            status="success",
            data={"pattern": pattern, "paths": paths, "count": len(paths)},
        )


class SearchCodeTool:
    definition = ToolDefinition(
        name="search_code",
        description="Search text files in the workspace for a literal string or regular expression.",
        input_schema=_schema(
            {
                "query": {"type": "string", "minLength": 1},
                "path_pattern": {"type": "string", "minLength": 1},
                "regex": {"type": "boolean"},
            },
            ["query"],
        ),
    )
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False
    manages_own_timeout = False

    async def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
        context.cancellation.raise_if_cancelled()
        context.deadline.check()
        query = str(arguments["query"])
        path_pattern = arguments.get("path_pattern")
        if path_pattern is not None:
            _validate_pattern(str(path_pattern))
        compiled = None
        if bool(arguments.get("regex", False)):
            try:
                compiled = re.compile(query)
            except re.error as exc:
                raise ToolInputError("invalid_regex", f"Invalid regular expression: {exc}") from exc
        return PreparedToolAction(dict(arguments), None, compiled)

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        query = str(action.arguments["query"])
        path_pattern_value = action.arguments.get("path_pattern")
        path_pattern = str(path_pattern_value) if path_pattern_value is not None else None
        compiled = action.state if isinstance(action.state, re.Pattern) else None
        matches: list[dict[str, JSONValue]] = []
        skipped_binary = 0
        skipped_encoding = 0
        searched_files = 0

        async for path in context.workspace.walk_files(
            context.deadline, context.cancellation
        ):
            context.cancellation.raise_if_cancelled()
            relative = context.workspace.relative(path)
            if path_pattern is not None and not _glob_match(relative, path_pattern):
                continue
            try:
                raw = await asyncio.to_thread(path.read_bytes)
            except OSError:
                continue
            context.deadline.check()
            context.cancellation.raise_if_cancelled()
            if b"\x00" in raw:
                skipped_binary += 1
                continue
            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                skipped_encoding += 1
                continue
            searched_files += 1
            for line_number, line in enumerate(text.splitlines(), start=1):
                context.deadline.check()
                context.cancellation.raise_if_cancelled()
                found = compiled.search(line) is not None if compiled is not None else query in line
                if found:
                    matches.append(
                        {"path": relative, "line": line_number, "content": line}
                    )

        return ToolResult(
            status="success",
            data={
                "query": query,
                "matches": matches,
                "count": len(matches),
                "searched_files": searched_files,
                "skipped_binary": skipped_binary,
                "skipped_encoding": skipped_encoding,
            },
        )


def _glob_match(relative: str, pattern: str) -> bool:
    path = relative.replace("\\", "/")
    normalized = pattern.replace("\\", "/")
    if "/" not in normalized:
        return fnmatch.fnmatch(path.rsplit("/", 1)[-1], normalized)
    return _match_segments(path.split("/"), normalized.split("/"))


def _match_segments(path: list[str], pattern: list[str]) -> bool:
    if not pattern:
        return not path
    if pattern[0] == "**":
        return _match_segments(path, pattern[1:]) or (
            bool(path) and _match_segments(path[1:], pattern)
        )
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _match_segments(
        path[1:], pattern[1:]
    )
