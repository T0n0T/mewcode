from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mewcode.config import LLMConfig


@dataclass(frozen=True)
class SessionMetadata:
    config_name: str
    provider: str
    model: str
    workspace: Path
    git_branch: str | None


def build_session_metadata(
    config: LLMConfig,
    workspace: Path,
) -> SessionMetadata:
    return SessionMetadata(
        config_name=config.name,
        provider=config.protocol,
        model=config.model,
        workspace=workspace,
        git_branch=detect_git_branch(workspace),
    )


def detect_git_branch(workspace: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch or None
