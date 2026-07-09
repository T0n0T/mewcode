from collections.abc import Iterable


class MewCodeError(Exception):
    """Base class for errors that can be shown directly to users."""

    def __init__(self, user_message: str):
        self.user_message = user_message
        super().__init__(user_message)


class ConfigError(MewCodeError):
    pass


class ProviderError(MewCodeError):
    pass


def redact_secrets(message: str, secrets: Iterable[str]) -> str:
    redacted = message
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
