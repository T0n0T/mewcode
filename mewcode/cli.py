from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO

from mewcode.config import load_config
from mewcode.errors import MewCodeError
from mewcode.providers import create_provider
from mewcode.runtime import ChatRuntime
from mewcode.tui import ChatApp


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
        runtime = ChatRuntime(provider)
        app = ChatApp(runtime, config, input_stream=stdin, output_stream=stdout)
        return app.run()
    except MewCodeError as exc:
        error_stream.write(f"Error: {exc.user_message}\n")
        error_stream.flush()
        return 1
