import asyncio
from pathlib import Path

import pytest

from mewcode.cancellation import CancellationToken
from mewcode.tools.base import ToolCall, ToolOutputLimits
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.search_tools import GlobFilesTool, SearchCodeTool
from mewcode.tools.workspace import Workspace


def executor(tmp_path: Path, tool, limits=None):
    registry = ToolRegistry()
    registry.register(tool)
    return ToolExecutor(registry, Workspace(tmp_path), limits=limits)


async def execute(tmp_path: Path, tool, call: ToolCall, limits=None):
    async def unexpected_confirm(*_args):
        raise AssertionError("Read-only tools must not request confirmation.")

    return await executor(tmp_path, tool, limits).execute(
        call,
        cancellation=CancellationToken(),
        confirm=unexpected_confirm,
    )


@pytest.mark.asyncio
async def test_glob_files_basic_ignore_and_truncated(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("x", encoding="utf-8")

    result = await execute(
        tmp_path,
        GlobFilesTool(),
        ToolCall("1", "glob_files", {"pattern": "*.py"}),
        limits=ToolOutputLimits(paths=1),
    )

    assert result.data["paths"] == ["a.py"]
    assert result.truncation.original == 2


@pytest.mark.asyncio
async def test_glob_files_rejects_escape_pattern(tmp_path: Path):
    result = await execute(
        tmp_path,
        GlobFilesTool(),
        ToolCall("1", "glob_files", {"pattern": "../*.py"})
    )

    assert result.error.code == "invalid_path_pattern"


@pytest.mark.asyncio
async def test_glob_path_segments_do_not_cross_directories(tmp_path: Path):
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "src" / "direct.py").write_text("x", encoding="utf-8")
    (tmp_path / "src" / "nested" / "deep.py").write_text("x", encoding="utf-8")

    direct = await execute(
        tmp_path,
        GlobFilesTool(),
        ToolCall("1", "glob_files", {"pattern": "src/*.py"})
    )
    recursive = await execute(
        tmp_path,
        GlobFilesTool(),
        ToolCall("2", "glob_files", {"pattern": "src/**/*.py"})
    )

    assert direct.data["paths"] == ["src/direct.py"]
    assert recursive.data["paths"] == ["src/direct.py", "src/nested/deep.py"]


@pytest.mark.asyncio
async def test_search_code_literal_regex_skipped_and_truncated(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("needle\nother needle\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("needle", encoding="utf-8")
    (tmp_path / "bad.txt").write_bytes(b"\xff")
    (tmp_path / "bin.txt").write_bytes(b"a\x00needle")

    literal = await execute(
        tmp_path,
        SearchCodeTool(),
        ToolCall("1", "search_code", {"query": "needle"}),
        limits=ToolOutputLimits(matches=1),
    )
    assert literal.data["matches"] == [{"path": "a.txt", "line": 1, "content": "needle"}]
    assert literal.truncation.original == 2
    assert literal.data["skipped_binary"] == 1
    assert literal.data["skipped_encoding"] == 1

    regex = await execute(
        tmp_path,
        SearchCodeTool(),
        ToolCall("2", "search_code", {"query": "oth.*needle", "regex": True})
    )
    assert regex.data["matches"][0]["line"] == 2

    invalid = await execute(
        tmp_path,
        SearchCodeTool(),
        ToolCall("3", "search_code", {"query": "[", "regex": True})
    )
    assert invalid.error.code == "invalid_regex"


@pytest.mark.asyncio
async def test_read_only_search_tools_can_overlap_without_shared_results(tmp_path: Path):
    (tmp_path / "a.py").write_text("first", encoding="utf-8")
    (tmp_path / "b.txt").write_text("second", encoding="utf-8")

    python_files, text_files = await asyncio.gather(
        execute(tmp_path, GlobFilesTool(), ToolCall("1", "glob_files", {"pattern": "*.py"})),
        execute(tmp_path, GlobFilesTool(), ToolCall("2", "glob_files", {"pattern": "*.txt"})),
    )

    assert python_files.data["paths"] == ["a.py"]
    assert text_files.data["paths"] == ["b.txt"]


@pytest.mark.asyncio
async def test_search_code_cancellation_stops_before_later_files(tmp_path: Path):
    for index in range(20):
        (tmp_path / f"{index:02}.txt").write_text("needle\n" * 100, encoding="utf-8")
    token = CancellationToken()
    tool = SearchCodeTool()
    workspace = Workspace(tmp_path)
    from mewcode.tools.base import Deadline, ToolContext

    context = ToolContext(workspace, Deadline(30), ToolOutputLimits(), token)
    action = await tool.prepare({"query": "needle"}, context)
    task = asyncio.create_task(tool.execute(action, context))
    await asyncio.sleep(0)
    token.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
