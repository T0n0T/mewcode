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


class ToolFailure(Exception):
    """Expected tool failure converted to a structured result by the executor."""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class InvalidToolArguments(ToolFailure):
    def __init__(self, message: str):
        super().__init__("invalid_arguments", message, retryable=True)


class WorkspacePathError(ToolFailure):
    def __init__(self, message: str, *, code: str = "path_outside_workspace"):
        super().__init__(code, message, retryable=True)


class ToolEncodingError(ToolFailure):
    def __init__(self, message: str):
        super().__init__("invalid_encoding", message, retryable=True)


class FileConflictError(ToolFailure):
    def __init__(self, message: str):
        super().__init__("file_conflict", message, retryable=True)


class ToolInputError(ToolFailure):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, retryable=True)


class DeadlineExceeded(ToolFailure):
    def __init__(self, message: str = "Tool execution exceeded its time limit."):
        super().__init__("timeout", message, retryable=True)


def redact_secrets(message: str, secrets: Iterable[str]) -> str:
    redacted = message
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[redacted]")
    return redacted
