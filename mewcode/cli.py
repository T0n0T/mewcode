from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from mewcode.config import load_config
from mewcode.errors import MewCodeError
from mewcode.providers import create_provider
from mewcode.runtime import ChatRuntime
from mewcode.tools import Workspace, create_default_registry
from mewcode.tools.defaults import DEFAULT_OUTPUT_LIMITS
from mewcode.tools.executor import ToolExecutor
from mewcode.tui import (
    CyberpunkChatApp,
    PlainChatApp,
    PlainToolInteraction,
    TerminalMode,
    TuiEventBridge,
    TuiToolInteraction,
    build_session_metadata,
    detect_terminal_mode,
    supports_unicode,
)


def main(
    config_path: Path | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    error_stream = stderr or sys.stderr
    try:
        config = load_config(config_path) if config_path is not None else load_config()
        provider = create_provider(config)
        registry = create_default_registry()
        input_stream = stdin if stdin is not None else sys.stdin
        output_stream = stdout if stdout is not None else sys.stdout
        terminal_mode = detect_terminal_mode(input_stream, output_stream)
        bridge: TuiEventBridge | None = None
        if terminal_mode is TerminalMode.FULLSCREEN:
            bridge = TuiEventBridge()
            interaction = TuiToolInteraction(
                bridge,
                secrets=(config.api_key,),
            )
        else:
            interaction = PlainToolInteraction(
                input_stream,
                output_stream,
                secrets=(config.api_key,),
            )
        workspace_path = Path.cwd()
        executor = ToolExecutor(
            registry,
            Workspace(workspace_path),
            interaction,
            limits=DEFAULT_OUTPUT_LIMITS,
            secrets=(config.api_key,),
        )
        runtime = ChatRuntime(provider, registry, executor)
        if terminal_mode is TerminalMode.FULLSCREEN:
            assert bridge is not None
            app = CyberpunkChatApp(
                runtime,
                build_session_metadata(config, workspace_path),
                bridge,
                unicode_output=supports_unicode(output_stream),
            )
            return app.run() or 0
        return PlainChatApp(
            runtime,
            config,
            input_stream=input_stream,
            output_stream=output_stream,
        ).run()
    except MewCodeError as exc:
        error_stream.write(f"Error: {exc.user_message}\n")
        error_stream.flush()
        return 1
