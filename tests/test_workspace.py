from pathlib import Path

import pytest

from mewcode.errors import DeadlineExceeded, WorkspacePathError
from mewcode.tools.base import Deadline
from mewcode.tools.workspace import Workspace


def test_existing_path_resolves_inside_workspace(tmp_path: Path):
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("ok", encoding="utf-8")

    workspace = Workspace(tmp_path)

    assert workspace.resolve_existing("src/app.py") == target


def test_existing_path_rejects_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)
    workspace = Workspace(tmp_path)

    for raw_path in (str(outside), "../outside.txt", "link.txt"):
        with pytest.raises(WorkspacePathError):
            workspace.resolve_existing(raw_path)


def test_existing_path_reports_missing_file(tmp_path: Path):
    with pytest.raises(WorkspacePathError) as exc_info:
        Workspace(tmp_path).resolve_existing("missing.txt")

    assert exc_info.value.code == "not_found"
    assert "missing.txt" in exc_info.value.message
    assert str(tmp_path) not in exc_info.value.message


def test_create_path_allows_missing_parents_and_rejects_symlink_escape(tmp_path: Path):
    workspace = Workspace(tmp_path)
    assert workspace.resolve_for_create("new/deep/file.txt") == tmp_path / "new/deep/file.txt"

    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(WorkspacePathError):
        workspace.resolve_for_create("escape/file.txt")


def test_ignore_rules_and_explicit_paths(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored/\n*.log\n!keep.log\n", encoding="utf-8")
    (tmp_path / "ignored").mkdir()
    ignored = tmp_path / "ignored" / "known.txt"
    ignored.write_text("ok", encoding="utf-8")
    workspace = Workspace(tmp_path)

    assert workspace.is_ignored(".git/config")
    assert workspace.is_ignored("ignored/known.txt")
    assert workspace.is_ignored("drop.log")
    assert not workspace.is_ignored("keep.log")
    assert workspace.resolve_existing("ignored/known.txt") == ignored


def test_walk_is_sorted_ignored_and_interruptible(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("x", encoding="utf-8")
    workspace = Workspace(tmp_path)

    paths = [workspace.relative(path) for path in workspace.walk_files(Deadline(10))]
    assert paths == [".gitignore", "a.txt", "b.txt"]

    now = [0.0]
    deadline = Deadline(1.0, clock=lambda: now[0])
    now[0] = 1.0
    with pytest.raises(DeadlineExceeded):
        list(workspace.walk_files(deadline))
