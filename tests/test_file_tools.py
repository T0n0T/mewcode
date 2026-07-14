import asyncio
import threading
from pathlib import Path

import pytest

from mewcode.cancellation import CancellationToken
from mewcode.tools.base import ToolCall, ToolOutputLimits
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class Interaction:
    def __init__(self, approved=True):
        self.approved = approved
        self.previews = []

    def tool_started(self, call):
        pass

    def confirm(self, preview):
        self.previews.append(preview)
        return self.approved

    def tool_finished(self, call, result):
        pass

    def tool_budget_exhausted(self):
        pass


def executor(tmp_path: Path, tool, interaction=None, limits=None):
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(registry, Workspace(tmp_path), limits=limits)


async def execute(tmp_path: Path, tool, call: ToolCall, interaction=None, limits=None):
    async def confirm(_call, preview):
        if interaction is None:
            return True
        interaction.previews.append(preview)
        return interaction.approved

    return await executor(tmp_path, tool, interaction, limits).execute(
        call,
        cancellation=CancellationToken(),
        confirm=confirm,
    )


@pytest.mark.asyncio
async def test_read_file_success_and_ignored_file(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    target = tmp_path / "ignored.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    result = await execute(
        tmp_path,
        ReadFileTool(),
        ToolCall(
            "1", "read_file", {"path": "ignored.txt", "start_line": 2, "line_count": 1}
        ),
    )

    assert result.status == "success"
    assert result.data["content"] == "b\n"
    assert result.data["total_lines"] == 3


@pytest.mark.parametrize("content", [b"\xff", b"a\x00b"])
@pytest.mark.asyncio
async def test_read_file_error_and_truncated(tmp_path: Path, content: bytes):
    (tmp_path / "bad.txt").write_bytes(content)
    result = await execute(
        tmp_path, ReadFileTool(), ToolCall("1", "read_file", {"path": "bad.txt"})
    )

    assert result.status == "error"

    (tmp_path / "long.txt").write_text("abcdef", encoding="utf-8")
    truncated = await execute(
        tmp_path,
        ReadFileTool(),
        ToolCall("2", "read_file", {"path": "long.txt"}),
        limits=ToolOutputLimits(text_characters=3),
    )
    assert truncated.data["content"] == "abc"
    assert truncated.truncation.original == 6


@pytest.mark.asyncio
async def test_read_file_checks_cancellation_between_chunks(tmp_path: Path):
    target = tmp_path / "large.txt"
    target.write_text("x" * 200_000, encoding="utf-8")

    class CancelDuringRead(CancellationToken):
        def __init__(self):
            super().__init__()
            self.checks = 0

        def raise_if_cancelled(self):
            self.checks += 1
            if self.checks == 5:
                self.cancel()
            super().raise_if_cancelled()

    token = CancelDuringRead()
    tool = ReadFileTool()
    context = _context(Workspace(tmp_path), token)
    action = await tool.prepare({"path": "large.txt"}, context)

    with pytest.raises(asyncio.CancelledError):
        await tool.execute(action, context)

    assert token.checks >= 5


@pytest.mark.asyncio
async def test_write_file_prepare_new_file_overwrite_and_reject(tmp_path: Path):
    interaction = Interaction(approved=True)
    result = await execute(
        tmp_path,
        WriteFileTool(),
        ToolCall("1", "write_file", {"path": "new/deep.txt", "content": "hello\n"}),
        interaction,
    )

    assert result.status == "success"
    assert (tmp_path / "new/deep.txt").read_text(encoding="utf-8") == "hello\n"
    assert "b/new/deep.txt" in interaction.previews[0].details

    reject = Interaction(approved=False)
    result = await execute(
        tmp_path,
        WriteFileTool(),
        ToolCall("2", "write_file", {"path": "nope.txt", "content": "x"}),
        reject,
    )
    assert result.status == "rejected"
    assert not (tmp_path / "nope.txt").exists()


@pytest.mark.asyncio
async def test_write_file_conflict_keeps_external_change(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    workspace = Workspace(tmp_path)
    tool = WriteFileTool()
    context = _context(workspace)
    action = await tool.prepare({"path": "file.txt", "content": "new"}, context)
    target.write_text("changed", encoding="utf-8")

    result = await execute(
        tmp_path, tool, ToolCall("1", "write_file", action.arguments)
    )
    # Executor prepares a fresh action, so directly execute stale action to verify the guard.
    with pytest.raises(Exception, match="changed after the preview"):
        await tool.execute(action, context)
    assert result.status == "success"


@pytest.mark.asyncio
async def test_write_file_prepare_cancellation_has_no_side_effect(tmp_path: Path):
    token = CancellationToken()
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await WriteFileTool().prepare(
            {"path": "new/deep.txt", "content": "hello"},
            _context(Workspace(tmp_path), token),
        )

    assert not (tmp_path / "new").exists()


@pytest.mark.asyncio
async def test_atomic_write_cannot_follow_parent_swapped_after_validation(
    tmp_path: Path, monkeypatch
):
    parent = tmp_path / "safe"
    parent.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    workspace = Workspace(tmp_path)
    tool = WriteFileTool()
    context = _context(workspace)
    action = await tool.prepare({"path": "safe/file.txt", "content": "new"}, context)
    original_resolve = workspace.resolve_for_create

    def swap_parent(raw_path):
        resolved = original_resolve(raw_path)
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr(workspace, "resolve_for_create", swap_parent)
    with pytest.raises(Exception):
        await tool.execute(action, context)
    assert not (outside / "file.txt").exists()


@pytest.mark.asyncio
async def test_atomic_write_cleans_temporary_file_on_replace_failure(
    tmp_path: Path, monkeypatch
):
    import mewcode.tools.file_tools as file_tools

    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    tool = WriteFileTool()
    context = _context(Workspace(tmp_path))
    action = await tool.prepare({"path": "file.txt", "content": "new"}, context)

    monkeypatch.setattr(
        file_tools.os,
        "replace",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace failed")),
    )
    with pytest.raises(OSError, match="replace failed"):
        await tool.execute(action, context)

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".file.txt.*.tmp")) == []


@pytest.mark.asyncio
async def test_write_file_cancellation_leaves_old_or_complete_new_content(
    tmp_path: Path, monkeypatch
):
    import mewcode.tools.file_tools as file_tools

    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    token = CancellationToken()
    tool = WriteFileTool()
    context = _context(Workspace(tmp_path), token)
    new_content = "new" * 100_000
    action = await tool.prepare({"path": "file.txt", "content": new_content}, context)
    replace_started = threading.Event()
    allow_replace = threading.Event()
    original_replace = file_tools.os.replace

    def controlled_replace(*args, **kwargs):
        replace_started.set()
        if not allow_replace.wait(timeout=5):
            raise TimeoutError("test did not release atomic replace")
        return original_replace(*args, **kwargs)

    monkeypatch.setattr(file_tools.os, "replace", controlled_replace)

    task = asyncio.create_task(tool.execute(action, context))
    assert await asyncio.to_thread(replace_started.wait, 5)
    try:
        token.cancel()
        task.cancel()
        await asyncio.sleep(0)

        assert not task.done()
        assert target.read_text(encoding="utf-8") == "old"
    finally:
        allow_replace.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert target.read_text(encoding="utf-8") == new_content
    assert list(tmp_path.glob(".file.txt.*.tmp")) == []


@pytest.mark.asyncio
async def test_edit_file_success_not_found_not_unique_and_conflict(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("one two\n", encoding="utf-8")
    interaction = Interaction()

    result = await execute(
        tmp_path,
        EditFileTool(),
        ToolCall(
            "1",
            "edit_file",
            {"path": "file.txt", "old_text": "two", "new_text": "three"},
        ),
        interaction,
    )
    assert result.status == "success"
    assert target.read_text(encoding="utf-8") == "one three\n"
    assert "-one two" in interaction.previews[0].details

    not_found = await execute(
        tmp_path,
        EditFileTool(),
        ToolCall(
            "2",
            "edit_file",
            {"path": "file.txt", "old_text": "absent", "new_text": "x"},
        ),
    )
    assert not_found.error.code == "text_not_found"

    target.write_text("x x", encoding="utf-8")
    not_unique = await execute(
        tmp_path,
        EditFileTool(),
        ToolCall(
            "3", "edit_file", {"path": "file.txt", "old_text": "x", "new_text": "y"}
        ),
    )
    assert not_unique.error.code == "text_not_unique"


def _context(workspace, cancellation=None):
    from mewcode.tools.base import Deadline, ToolContext, ToolOutputLimits

    return ToolContext(
        workspace,
        Deadline(30),
        ToolOutputLimits(),
        cancellation or CancellationToken(),
    )
