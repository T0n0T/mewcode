"""Internal widgets for the MewCode terminal interface."""

from mewcode.tui.widgets.chrome import (
    ActivityIndicator,
    NewOutputIndicator,
    SessionHeader,
    WelcomeCard,
)
from mewcode.tui.widgets.composer import PromptComposer, PromptHistory
from mewcode.tui.widgets.confirmation import ConfirmationModal
from mewcode.tui.widgets.conversation import (
    AssistantMessageView,
    ConversationView,
    ErrorCard,
    ToolCard,
    UserMessageView,
)

__all__ = [
    "ActivityIndicator",
    "AssistantMessageView",
    "ConfirmationModal",
    "ConversationView",
    "ErrorCard",
    "NewOutputIndicator",
    "PromptHistory",
    "PromptComposer",
    "SessionHeader",
    "ToolCard",
    "UserMessageView",
    "WelcomeCard",
]
