from pathlib import Path

import pytest

from mewcode.config import LLMConfig, load_config
from mewcode.errors import ConfigError


def write_config(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_reads_valid_yaml(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: openai-main
protocol: openai
model: gpt-5-mini
base_url: https://api.openai.com/v1/
api_key: sk-test
thinking: false
""",
    )

    config = load_config(path)

    assert config == LLMConfig(
        name="openai-main",
        protocol="openai",
        model="gpt-5-mini",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        thinking=False,
    )
    assert "sk-test" not in repr(config)


def test_load_config_defaults_thinking_to_false(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: claude-main
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: secret-key
""",
    )

    assert load_config(path).thinking is False


def test_load_config_rejects_missing_required_field(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: missing-model
protocol: openai
base_url: https://api.openai.com/v1
api_key: secret-key
""",
    )

    with pytest.raises(ConfigError, match="model"):
        load_config(path)


def test_load_config_rejects_unknown_protocol(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: bad-protocol
protocol: other
model: demo
base_url: https://example.com
api_key: secret-key
""",
    )

    with pytest.raises(ConfigError, match="Unsupported protocol"):
        load_config(path)


def test_load_config_rejects_non_boolean_thinking(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: bad-thinking
protocol: anthropic
model: claude-sonnet-4-5
base_url: https://api.anthropic.com/v1
api_key: secret-key
thinking: yes please
""",
    )

    with pytest.raises(ConfigError, match="thinking"):
        load_config(path)


def test_load_config_redaction_does_not_leak_api_key(tmp_path: Path):
    path = write_config(
        tmp_path / "config.yaml",
        """
name: secret-leak-check
protocol: openai
model: demo
base_url: https://example.com
api_key: secret-token
thinking: no thanks
""",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert "secret-token" not in str(exc_info.value)


def test_load_config_reports_missing_file(tmp_path: Path):
    path = tmp_path / "missing.yaml"

    with pytest.raises(ConfigError) as exc_info:
        load_config(path)

    assert str(path) in str(exc_info.value)
