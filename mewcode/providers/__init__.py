from __future__ import annotations

from mewcode.errors import ProviderError
from mewcode.providers.base import (
    LLMProvider,
    ProviderEvent,
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mewcode.config import LLMConfig


def create_provider(config: LLMConfig) -> LLMProvider:
    if config.protocol == "openai":
        from mewcode.providers.openai import OpenAIProvider

        return OpenAIProvider(config)
    if config.protocol == "anthropic":
        from mewcode.providers.anthropic import AnthropicProvider

        return AnthropicProvider(config)
    raise ProviderError(f"Unsupported protocol '{config.protocol}'. Use 'openai' or 'anthropic'.")


__all__ = [
    "LLMProvider",
    "ProviderEvent",
    "ProviderResponseCompleted",
    "ProviderTextDelta",
    "ProviderToolCallDelta",
    "TokenUsage",
    "create_provider",
]
