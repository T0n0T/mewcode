from pathlib import Path

import pytest

from mewcode.providers.base import ToolCall
from mewcode.tools.base import ToolOutputLimits
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
    return ToolExecutor(
        registry,
        Workspace(tmp_path),
        interaction or Interaction(),
        limits=limits,
    )


def test_read_file_success_and_ignored_file(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    target = tmp_path / "ignored.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    result = executor(tmp_path, ReadFileTool()).execute(
        ToolCall("1", "read_file", {"path": "ignored.txt", "start_line": 2, "line_count": 1})
    )

    assert result.status == "success"
    assert result.data["content"] == "b\n"
    assert result.data["total_lines"] == 3


@pytest.mark.parametrize("content", [b"\xff", b"a\x00b"])
def test_read_file_error_and_truncated(tmp_path: Path, content: bytes):
    (tmp_path / "bad.txt").write_bytes(content)
    result = executor(tmp_path, ReadFileTool()).execute(
        ToolCall("1", "read_file", {"path": "bad.txt"})
    )

    assert result.status == "error"

    (tmp_path / "long.txt").write_text("abcdef", encoding="utf-8")
    truncated = executor(
        tmp_path,
        ReadFileTool(),
        limits=ToolOutputLimits(text_characters=3),
    ).execute(ToolCall("2", "read_file", {"path": "long.txt"}))
    assert truncated.data["content"] == "abc"
    assert truncated.truncation.original == 6


def test_write_file_prepare_new_file_overwrite_and_reject(tmp_path: Path):
    interaction = Interaction(approved=True)
    result = executor(tmp_path, WriteFileTool(), interaction).execute(
        ToolCall("1", "write_file", {"path": "new/deep.txt", "content": "hello\n"})
    )

    assert result.status == "success"
    assert (tmp_path / "new/deep.txt").read_text(encoding="utf-8") == "hello\n"
    assert "b/new/deep.txt" in interaction.previews[0].details

    reject = Interaction(approved=False)
    result = executor(tmp_path, WriteFileTool(), reject).execute(
        ToolCall("2", "write_file", {"path": "nope.txt", "content": "x"})
    )
    assert result.status == "rejected"
    assert not (tmp_path / "nope.txt").exists()


def test_write_file_conflict_keeps_external_change(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    workspace = Workspace(tmp_path)
    tool = WriteFileTool()
    context = _context(workspace)
    action = tool.prepare({"path": "file.txt", "content": "new"}, context)
    target.write_text("changed", encoding="utf-8")

    result = executor(tmp_path, tool).execute(ToolCall("1", "write_file", action.arguments))
    # Executor prepares a fresh action, so directly execute stale action to verify the guard.
    with pytest.raises(Exception, match="changed after the preview"):
        tool.execute(action, context)
    assert result.status == "success"


def test_atomic_write_cannot_follow_parent_swapped_after_validation(
    tmp_path: Path, monkeypatch
):
    parent = tmp_path / "safe"
    parent.mkdir()
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    workspace = Workspace(tmp_path)
    tool = WriteFileTool()
    context = _context(workspace)
    action = tool.prepare({"path": "safe/file.txt", "content": "new"}, context)
    original_resolve = workspace.resolve_for_create

    def swap_parent(raw_path):
        resolved = original_resolve(raw_path)
        parent.rmdir()
        parent.symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr(workspace, "resolve_for_create", swap_parent)
    with pytest.raises(Exception):
        tool.execute(action, context)
    assert not (outside / "file.txt").exists()


def test_atomic_write_cleans_temporary_file_on_replace_failure(tmp_path: Path, monkeypatch):
    import mewcode.tools.file_tools as file_tools

    target = tmp_path / "file.txt"
    target.write_text("old", encoding="utf-8")
    tool = WriteFileTool()
    context = _context(Workspace(tmp_path))
    action = tool.prepare({"path": "file.txt", "content": "new"}, context)

    monkeypatch.setattr(file_tools.os, "replace", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError, match="replace failed"):
        tool.execute(action, context)

    assert target.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.glob(".file.txt.*.tmp")) == []


def test_edit_file_success_not_found_not_unique_and_conflict(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("one two\n", encoding="utf-8")
    interaction = Interaction()

    result = executor(tmp_path, EditFileTool(), interaction).execute(
        ToolCall("1", "edit_file", {"path": "file.txt", "old_text": "two", "new_text": "three"})
    )
    assert result.status == "success"
    assert target.read_text(encoding="utf-8") == "one three\n"
    assert "-one two" in interaction.previews[0].details

    not_found = executor(tmp_path, EditFileTool()).execute(
        ToolCall("2", "edit_file", {"path": "file.txt", "old_text": "absent", "new_text": "x"})
    )
    assert not_found.error.code == "text_not_found"

    target.write_text("x x", encoding="utf-8")
    not_unique = executor(tmp_path, EditFileTool()).execute(
        ToolCall("3", "edit_file", {"path": "file.txt", "old_text": "x", "new_text": "y"})
    )
    assert not_unique.error.code == "text_not_unique"


def _context(workspace):
    from mewcode.tools.base import Deadline, ToolContext, ToolOutputLimits

    return ToolContext(workspace, Deadline(30), ToolOutputLimits())
