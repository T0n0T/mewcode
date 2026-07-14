from __future__ import annotations

import asyncio
import difflib
import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mewcode.errors import (
    FileConflictError,
    ToolEncodingError,
    ToolInputError,
    WorkspacePathError,
)
from mewcode.tools.base import (
    ConfirmationPreview,
    JSONValue,
    PreparedToolAction,
    ToolContext,
    ToolDefinition,
    ToolAccess,
    ToolExecutionPolicy,
    ToolResult,
)


def _object_schema(
    properties: dict[str, JSONValue], required: list[str]
) -> dict[str, JSONValue]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


@dataclass(frozen=True)
class _FileState:
    path: Path
    original: str | None
    fingerprint: str | None
    new_content: str


class ReadFileTool:
    definition = ToolDefinition(
        name="read_file",
        description="Read a UTF-8 text file from the workspace, optionally by line range.",
        input_schema=_object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "start_line": {"type": "integer", "minimum": 1},
                "line_count": {"type": "integer", "minimum": 1},
            },
            ["path"],
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
        path = context.workspace.resolve_existing(str(arguments["path"]))
        return PreparedToolAction(dict(arguments), None, path)

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        path = action.state
        assert isinstance(path, Path)
        content = await _read_utf8(path, context)
        lines = content.splitlines(keepends=True)
        total_lines = len(lines)
        start_line = int(action.arguments.get("start_line", 1))
        line_count_value = action.arguments.get("line_count")
        if start_line > max(total_lines, 1):
            raise ToolInputError(
                "invalid_line_range",
                f"start_line {start_line} is beyond the file's {total_lines} lines.",
            )
        end_index = total_lines if line_count_value is None else start_line - 1 + int(line_count_value)
        selected = lines[start_line - 1 : end_index]
        end_line = start_line + len(selected) - 1 if selected else 0
        return ToolResult(
            status="success",
            data={
                "path": context.workspace.relative(path),
                "content": "".join(selected),
                "total_lines": total_lines,
                "start_line": start_line,
                "end_line": end_line,
            },
        )


class WriteFileTool:
    definition = ToolDefinition(
        name="write_file",
        description="Create or completely replace a UTF-8 text file in the workspace.",
        input_schema=_object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "content": {"type": "string"},
            },
            ["path", "content"],
        ),
    )
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True
    manages_own_timeout = False

    async def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
        context.cancellation.raise_if_cancelled()
        context.deadline.check()
        path = context.workspace.resolve_for_create(str(arguments["path"]))
        original = await _read_optional_utf8(path, context)
        context.cancellation.raise_if_cancelled()
        context.deadline.check()
        new_content = str(arguments["content"])
        relative = context.workspace.relative(path)
        preview = ConfirmationPreview(
            kind="write",
            title=f"Write {relative}",
            details=_unified_diff(relative, original or "", new_content, is_new=original is None),
        )
        state = _FileState(path, original, _fingerprint(original), new_content)
        return PreparedToolAction(dict(arguments), preview, state)

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        state = _file_state(action)
        relative = context.workspace.relative(state.path)
        path = context.workspace.resolve_for_create(relative)
        current = await _read_optional_utf8_safely(context, relative)
        if _fingerprint(current) != state.fingerprint:
            raise FileConflictError("File changed after the preview was generated.")
        await _atomic_write(path, state.new_content, context)
        return ToolResult(
            status="success",
            data={
                "path": context.workspace.relative(path),
                "characters_written": len(state.new_content),
                "created": state.original is None,
            },
        )


class EditFileTool:
    definition = ToolDefinition(
        name="edit_file",
        description="Replace one exact, unique text occurrence in a workspace UTF-8 file.",
        input_schema=_object_schema(
            {
                "path": {"type": "string", "minLength": 1},
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
            },
            ["path", "old_text", "new_text"],
        ),
    )
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True
    manages_own_timeout = False

    async def prepare(
        self, arguments: Mapping[str, JSONValue], context: ToolContext
    ) -> PreparedToolAction:
        context.cancellation.raise_if_cancelled()
        context.deadline.check()
        path = context.workspace.resolve_existing(str(arguments["path"]))
        original = await _read_utf8(path, context)
        old_text = str(arguments["old_text"])
        count = original.count(old_text)
        if count == 0:
            raise ToolInputError("text_not_found", "old_text was not found in the file.")
        if count != 1:
            raise ToolInputError(
                "text_not_unique",
                f"old_text appears {count} times; it must appear exactly once.",
            )
        new_content = original.replace(old_text, str(arguments["new_text"]), 1)
        relative = context.workspace.relative(path)
        preview = ConfirmationPreview(
            kind="edit",
            title=f"Edit {relative}",
            details=_unified_diff(relative, original, new_content),
        )
        return PreparedToolAction(
            dict(arguments),
            preview,
            _FileState(path, original, _fingerprint(original), new_content),
        )

    async def execute(
        self, action: PreparedToolAction, context: ToolContext
    ) -> ToolResult:
        state = _file_state(action)
        relative = context.workspace.relative(state.path)
        path = context.workspace.resolve_existing(relative)
        current = await _read_optional_utf8_safely(context, relative)
        assert current is not None
        if _fingerprint(current) != state.fingerprint:
            raise FileConflictError("File changed after the preview was generated.")
        await _atomic_write(path, state.new_content, context)
        return ToolResult(
            status="success",
            data={"path": relative, "replacements": 1},
        )


def _file_state(action: PreparedToolAction) -> _FileState:
    if not isinstance(action.state, _FileState):
        raise RuntimeError("Invalid prepared file state.")
    return action.state


async def _read_utf8(path: Path, context: ToolContext) -> str:
    return await asyncio.to_thread(_read_utf8_sync, path, context)


def _read_utf8_sync(path: Path, context: ToolContext) -> str:
    chunks: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="strict") as handle:
            while True:
                context.deadline.check()
                context.cancellation.raise_if_cancelled()
                chunk = handle.read(65_536)
                context.deadline.check()
                context.cancellation.raise_if_cancelled()
                if not chunk:
                    break
                if "\x00" in chunk:
                    raise ToolEncodingError(f"File is binary text: {path.name}")
                chunks.append(chunk)
            return "".join(chunks)
    except UnicodeDecodeError as exc:
        raise ToolEncodingError(f"File is not valid UTF-8: {path.name}") from exc
    except IsADirectoryError as exc:
        raise WorkspacePathError(
            f"Path is not a regular file: {path}", code="not_a_file"
        ) from exc


async def _read_optional_utf8(path: Path, context: ToolContext) -> str | None:
    return await asyncio.to_thread(_read_optional_utf8_sync, path, context)


def _read_optional_utf8_sync(path: Path, context: ToolContext) -> str | None:
    context.cancellation.raise_if_cancelled()
    context.deadline.check()
    if not path.exists():
        return None
    if not path.is_file():
        raise WorkspacePathError(f"Path is not a regular file: {path}", code="not_a_file")
    return _read_utf8_sync(path, context)


async def _read_optional_utf8_safely(
    context: ToolContext, relative: str
) -> str | None:
    return await asyncio.to_thread(_read_optional_utf8_safely_sync, context, relative)


def _read_optional_utf8_safely_sync(
    context: ToolContext, relative: str
) -> str | None:
    context.cancellation.raise_if_cancelled()
    context.deadline.check()
    parts = Path(relative).parts
    try:
        parent_fd = _open_parent_directory(context.workspace.root, parts[:-1], create=False)
    except FileNotFoundError:
        return None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(parts[-1], flags, dir_fd=parent_fd)
        except FileNotFoundError:
            return None
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 65_536):
                context.deadline.check()
                context.cancellation.raise_if_cancelled()
                chunks.append(chunk)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent_fd)
    raw = b"".join(chunks)
    if b"\x00" in raw:
        raise ToolEncodingError(f"File is binary text: {parts[-1]}")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ToolEncodingError(f"File is not valid UTF-8: {parts[-1]}") from exc


def _fingerprint(content: str | None) -> str | None:
    if content is None:
        return None
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _unified_diff(relative: str, old: str, new: str, *, is_new: bool = False) -> str:
    before = "/dev/null" if is_new else f"a/{relative}"
    after = f"b/{relative}"
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=before,
            tofile=after,
        )
    )


async def _atomic_write(path: Path, content: str, context: ToolContext) -> None:
    task = asyncio.create_task(asyncio.to_thread(_atomic_write_sync, path, content, context))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(task)
        finally:
            raise


def _atomic_write_sync(path: Path, content: str, context: ToolContext) -> None:
    context.deadline.check()
    context.cancellation.raise_if_cancelled()
    parent_fd = _open_parent_directory(
        context.workspace.root,
        Path(context.workspace.relative(path)).parts[:-1],
        create=True,
    )
    temporary_name = f".{path.name}.{os.urandom(8).hex()}.tmp"
    try:
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", errors="strict") as handle:
            for offset in range(0, len(content), 65_536):
                context.deadline.check()
                context.cancellation.raise_if_cancelled()
                handle.write(content[offset : offset + 65_536])
            handle.flush()
            os.fsync(handle.fileno())
        context.deadline.check()
        context.cancellation.raise_if_cancelled()
        os.replace(
            temporary_name,
            path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        temporary_name = ""
    finally:
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)


def _open_parent_directory(root: Path, parts: tuple[str, ...], *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(root, flags)
    try:
        for part in parts:
            try:
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, dir_fd=descriptor)
                next_descriptor = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        os.close(descriptor)
        raise
