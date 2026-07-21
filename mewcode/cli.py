from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TextIO

from mewcode.agent import AgentSession
from mewcode.config import load_config
from mewcode.errors import MewCodeError
from mewcode.prompting import PromptBuilder, PromptOptions, capture_environment
from mewcode.providers import create_provider
from mewcode.tools import Workspace, create_default_registry
from mewcode.tools.defaults import DEFAULT_OUTPUT_LIMITS
from mewcode.tools.executor import ToolExecutor
from mewcode.tui import (
    CyberpunkChatApp,
    PlainChatApp,
    TerminalMode,
    build_session_metadata,
    detect_terminal_mode,
    supports_unicode,
)


async def async_main(
    config_path: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    config = load_config(config_path) if config_path is not None else load_config()
    provider = create_provider(config)
    registry = create_default_registry()
    workspace_path = Path.cwd()
    executor = ToolExecutor(
        registry,
        Workspace(workspace_path),
        limits=DEFAULT_OUTPUT_LIMITS,
        secrets=(config.api_key,),
    )
    prompt_builder = PromptBuilder()
    prompt_options = PromptOptions()
    session = AgentSession(
        provider,
        registry,
        executor,
        prompt_builder=prompt_builder,
        environment_factory=lambda: capture_environment(workspace_path),
        prompt_options=prompt_options,
    )
    input_stream = stdin if stdin is not None else sys.stdin
    output_stream = stdout if stdout is not None else sys.stdout

    try:
        terminal_mode = detect_terminal_mode(input_stream, output_stream)
        if terminal_mode is TerminalMode.FULLSCREEN:
            app = CyberpunkChatApp(
                session,
                build_session_metadata(config, workspace_path),
                unicode_output=supports_unicode(output_stream),
            )
            return await app.run_async() or 0
        return await PlainChatApp(
            session,
            config,
            input_stream=input_stream,
            output_stream=output_stream,
        ).run()
    finally:
        await session.close()


def main(
    config_path: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    error_stream = stderr or sys.stderr
    try:
        return asyncio.run(
            async_main(
                config_path=config_path,
                stdin=stdin,
                stdout=stdout,
            )
        )
    except MewCodeError as exc:
        error_stream.write(f"Error: {exc.user_message}\n")
        error_stream.flush()
        return 1
