from __future__ import annotations

from mewcode.tools.base import ToolOutputLimits
from mewcode.tools.command import RunCommandTool
from mewcode.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.search_tools import GlobFilesTool, SearchCodeTool

DEFAULT_OUTPUT_LIMITS = ToolOutputLimits()


def create_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        RunCommandTool(),
        GlobFilesTool(),
        SearchCodeTool(),
    ):
        registry.register(tool)
    return registry
