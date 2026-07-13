from pathlib import Path

from mewcode.providers.base import ToolCall
from mewcode.tools.base import ToolOutputLimits
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.search_tools import GlobFilesTool, SearchCodeTool
from mewcode.tools.workspace import Workspace


class Interaction:
    def tool_started(self, call):
        pass

    def confirm(self, preview):
        return True

    def tool_finished(self, call, result):
        pass

    def tool_budget_exhausted(self):
        pass


def executor(tmp_path: Path, tool, limits=None):
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(registry, Workspace(tmp_path), Interaction(), limits=limits)


def test_glob_files_basic_ignore_and_truncated(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("x", encoding="utf-8")

    result = executor(
        tmp_path,
        GlobFilesTool(),
        limits=ToolOutputLimits(paths=1),
    ).execute(ToolCall("1", "glob_files", {"pattern": "*.py"}))

    assert result.data["paths"] == ["a.py"]
    assert result.truncation.original == 2


def test_glob_files_rejects_escape_pattern(tmp_path: Path):
    result = executor(tmp_path, GlobFilesTool()).execute(
        ToolCall("1", "glob_files", {"pattern": "../*.py"})
    )

    assert result.error.code == "invalid_path_pattern"


def test_glob_path_segments_do_not_cross_directories(tmp_path: Path):
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "direct.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "nested" / "deep.py").write_text("x", encoding="utf-8")

    direct = executor(tmp_path, GlobFilesTool()).execute(
        ToolCall("1", "glob_files", {"pattern": "src/*.py"})
    )
    recursive = executor(tmp_path, GlobFilesTool()).execute(
        ToolCall("2", "glob_files", {"pattern": "src/**/*.py"})
    )

    assert direct.data["paths"] == ["src/direct.py"]
    assert recursive.data["paths"] == ["src/direct.py", "src/nested/deep.py"]


def test_search_code_literal_regex_skipped_and_truncated(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle\nother needle\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle", encoding="utf-8")
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    (tmp_path / "bin.txt").write_bytes(b"a\x00needle")

    literal = executor(
        tmp_path,
        SearchCodeTool(),
        limits=ToolOutputLimits(matches=1),
    ).execute(ToolCall("1", "search_code", {"query": "needle"}))
    assert literal.data["matches"] == [{"path": "a.txt", "line": 1, "content": "needle"}]
    assert literal.truncation.original == 2
    assert literal.data["skipped_binary"] == 1
    assert literal.data["skipped_encoding"] == 1

    regex = executor(tmp_path, SearchCodeTool()).execute(
        ToolCall("2", "search_code", {"query": "oth.*needle", "regex": True})
    )
    assert regex.data["matches"][0]["line"] == 2

    invalid = executor(tmp_path, SearchCodeTool()).execute(
        ToolCall("3", "search_code", {"query": "[", "regex": True})
    )
    assert invalid.error.code == "invalid_regex"
