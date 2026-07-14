import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mewcode.config import LLMConfig
from mewcode.tui.metadata import build_session_metadata, detect_git_branch


def config():
    return LLMConfig(
        name="test",
        protocol="openai",
        model="model",
        base_url="https://example.com/v1",
        api_key="metadata-secret",
    )


def test_detect_git_branch_in_repository(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "cyber-test", str(tmp_path)],
        check=True,
        capture_output=True,
    )

    assert detect_git_branch(tmp_path) == "cyber-test"


def test_detect_git_branch_returns_none_outside_repository(tmp_path):
    assert detect_git_branch(tmp_path) is None


def test_detect_git_branch_returns_none_for_detached_or_failed_query(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "mewcode.tui.metadata.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="\n"),
    )
    assert detect_git_branch(tmp_path) is None

    monkeypatch.setattr(
        "mewcode.tui.metadata.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="main\n"),
    )
    assert detect_git_branch(tmp_path) is None


@pytest.mark.parametrize(
    "error",
    [FileNotFoundError("git missing"), subprocess.TimeoutExpired("git", 0.5)],
)
def test_detect_git_branch_errors_do_not_escape(monkeypatch, tmp_path, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("mewcode.tui.metadata.subprocess.run", fail)

    assert detect_git_branch(tmp_path) is None


def test_session_metadata_excludes_api_key(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "mewcode.tui.metadata.detect_git_branch",
        lambda workspace: "main",
    )

    metadata = build_session_metadata(config(), tmp_path)

    assert metadata.config_name == "test"
    assert metadata.provider == "openai"
    assert metadata.model == "model"
    assert metadata.workspace == tmp_path
    assert metadata.git_branch == "main"
    assert "metadata-secret" not in repr(metadata)
