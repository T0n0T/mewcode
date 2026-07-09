from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

from .errors import ConfigError, redact_secrets
from .providers.base import ProviderProtocol

LOCAL_CONFIG_PATH = Path(".mewcode") / "config.yaml"
CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
REQUIRED_FIELDS = ("name", "protocol", "model", "base_url", "api_key")


@dataclass(frozen=True)
class LLMConfig:
    name: str
    protocol: ProviderProtocol
    model: str
    base_url: str
    api_key: str = field(repr=False)
    thinking: bool = False


def load_config(path: Path | None = None) -> LLMConfig:
    config_path = _resolve_config_path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(
            f"Config file not found: {config_path}. Create it with name, protocol, model, base_url, api_key, and optional thinking."
        ) from exc
    except OSError as exc:
        raise ConfigError(f"Could not read config file {config_path}: {exc}") from exc

    try:
        raw_data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file {config_path}: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ConfigError(f"Config file {config_path} must contain a YAML mapping.")

    data = cast(dict[str, Any], raw_data)
    api_key_for_redaction = data.get("api_key") if isinstance(data.get("api_key"), str) else ""

    try:
        for field_name in REQUIRED_FIELDS:
            if field_name not in data:
                raise ConfigError(f"Missing required config field '{field_name}' in {config_path}.")

        name = _required_string(data, "name", config_path)
        protocol_value = _required_string(data, "protocol", config_path).lower()
        model = _required_string(data, "model", config_path)
        base_url = _required_string(data, "base_url", config_path).rstrip("/")
        api_key = _required_string(data, "api_key", config_path)
        thinking = _optional_bool(data, "thinking", config_path)

        if protocol_value not in ("openai", "anthropic"):
            raise ConfigError(
                f"Unsupported protocol '{protocol_value}' in {config_path}. Use 'openai' or 'anthropic'."
            )

        return LLMConfig(
            name=name,
            protocol=cast(ProviderProtocol, protocol_value),
            model=model,
            base_url=base_url,
            api_key=api_key,
            thinking=thinking,
        )
    except ConfigError as exc:
        raise ConfigError(redact_secrets(exc.user_message, [api_key_for_redaction])) from exc


def _resolve_config_path(path: Path | None) -> Path:
    if path is not None:
        return path.expanduser()

    candidates = (LOCAL_CONFIG_PATH, Path.home() / ".mewcode" / "config.yaml")
    for candidate in candidates:
        config_path = candidate.expanduser()
        if config_path.is_file():
            return config_path

    looked_in = ", ".join(str(candidate.expanduser()) for candidate in candidates)
    raise ConfigError(
        f"Config file not found. Looked in: {looked_in}. Create it with name, protocol, model, base_url, api_key, and optional thinking."
    )


def _required_string(data: dict[str, Any], field_name: str, path: Path) -> str:
    value = data.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Config field '{field_name}' in {path} must be a non-empty string.")
    return value.strip()


def _optional_bool(data: dict[str, Any], field_name: str, path: Path) -> bool:
    if field_name not in data:
        return False
    value = data[field_name]
    if not isinstance(value, bool):
        raise ConfigError(f"Config field '{field_name}' in {path} must be true or false.")
    return value
