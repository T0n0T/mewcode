from io import StringIO
from threading import Event, Thread

import pytest

from mewcode.providers.base import ToolCall
from mewcode.tools.base import (
    ConfirmationPreview,
    ToolErrorInfo,
    ToolResult,
    TruncationInfo,
)
from mewcode.tui.events import (
    ConfirmationRequestedMessage,
    ToolBudgetMessage,
    ToolFinishedMessage,
    ToolStartedMessage,
)
from mewcode.tui.interaction import TuiEventBridge, TuiToolInteraction


class FakeTarget:
    def __init__(self):
        self.messages = []
        self.message_posted = Event()

    def call_from_thread(self, callback, *args, **kwargs):
        return callback(*args, **kwargs)

    def post_message(self, message):
        self.messages.append(message)
        self.message_posted.set()
        return True


def test_bridge_binds_once_and_delivers_messages():
    bridge = TuiEventBridge()
    target = FakeTarget()
    message = ToolBudgetMessage.__new__(ToolBudgetMessage)

    with pytest.raises(RuntimeError, match="not bound"):
        bridge.emit(message)

    bridge.bind(target)
    assert bridge.emit(message) is True
    assert target.messages == [message]

    with pytest.raises(RuntimeError, match="already bound"):
        bridge.bind(FakeTarget())


def test_closed_bridge_rejects_messages_and_new_bindings():
    bridge = TuiEventBridge()
    bridge.bind(FakeTarget())
    bridge.close()
    bridge.close()

    assert bridge.emit(ToolBudgetMessage.__new__(ToolBudgetMessage)) is False
    with pytest.raises(RuntimeError, match="closed"):
        bridge.bind(FakeTarget())
    with pytest.raises(RuntimeError, match="closed"):
        bridge.begin_generation(2)


def test_tool_events_include_safe_presentation_data_only():
    bridge = TuiEventBridge()
    target = FakeTarget()
    bridge.bind(target)
    bridge.begin_generation(9)
    interaction = TuiToolInteraction(
        bridge,
        secrets=("secret",),
        clock=lambda: 12.5,
    )
    call = ToolCall(
        "call-1",
        "read_file",
        {"path": "secret/notes.txt", "content": "hidden body"},
    )

    interaction.tool_started(call)
    interaction.tool_finished(
        call,
        ToolResult(
            status="error",
            data={"content": "full result must stay hidden"},
            error=ToolErrorInfo("failure", "bad secret", False),
            truncation=TruncationInfo(
                "characters",
                original=100,
                returned=10,
                hint="retry without secret",
                field="content",
            ),
            duration_ms=7,
        ),
    )
    interaction.tool_budget_exhausted()

    started = target.messages[0]
    finished = target.messages[1]
    assert isinstance(started, ToolStartedMessage)
    assert started.payload.generation_id == 9
    assert started.payload.started_at == 12.5
    assert "[redacted]/notes.txt" in started.payload.argument_summary
    assert isinstance(finished, ToolFinishedMessage)
    assert finished.payload.duration_ms == 7
    assert finished.payload.error_message == "bad [redacted]"
    assert finished.payload.truncation.hint == "retry without [redacted]"
    assert "full result must stay hidden" not in repr(finished.payload)
    assert isinstance(target.messages[2], ToolBudgetMessage)


def test_confirmation_waits_for_explicit_decision_and_is_redacted():
    bridge = TuiEventBridge()
    target = FakeTarget()
    bridge.bind(target)
    bridge.begin_generation(4)
    interaction = TuiToolInteraction(bridge, secrets=("secret",))
    result = []

    thread = Thread(
        target=lambda: result.append(
            interaction.confirm(
                ConfirmationPreview(
                    "command",
                    "Run secret command",
                    "echo secret",
                )
            )
        )
    )
    thread.start()
    assert target.message_posted.wait(timeout=1)
    message = target.messages[0]
    assert isinstance(message, ConfirmationRequestedMessage)
    assert message.payload.generation_id == 4
    assert "secret" not in message.payload.preview.title
    assert "secret" not in message.payload.preview.details

    bridge.resolve_confirmation(message.payload.decision, True)
    bridge.resolve_confirmation(message.payload.decision, False)
    thread.join(timeout=1)

    assert thread.is_alive() is False
    assert result == [True]


def test_bridge_close_rejects_pending_and_future_confirmations():
    bridge = TuiEventBridge()
    target = FakeTarget()
    bridge.bind(target)
    interaction = TuiToolInteraction(bridge)
    result = []

    thread = Thread(
        target=lambda: result.append(
            interaction.confirm(
                ConfirmationPreview("command", "Run command", "echo ok")
            )
        )
    )
    thread.start()
    assert target.message_posted.wait(timeout=1)

    bridge.close()
    thread.join(timeout=1)

    assert result == [False]
    assert interaction.confirm(
        ConfirmationPreview("command", "Run command", "echo ok")
    ) is False
