from concurrent.futures import Future
from dataclasses import FrozenInstanceError

import pytest

from mewcode.tools.base import ConfirmationPreview
from mewcode.tui.events import (
    ActivityState,
    ConfirmationPayload,
    ConfirmationRequestedMessage,
    ToolStartedMessage,
    ToolStartedPayload,
    TurnPhaseMessage,
    TurnPhasePayload,
)
from mewcode.tui.app import CyberpunkChatApp
from mewcode.tui.interaction import TuiEventBridge
from mewcode.tui.metadata import SessionMetadata
from mewcode.turns import TurnPhase


def test_presentation_messages_hold_immutable_payloads():
    phase_payload = TurnPhasePayload(7, TurnPhase.INITIAL_RESPONSE)
    message = TurnPhaseMessage(phase_payload)

    assert message.payload == phase_payload
    with pytest.raises(FrozenInstanceError):
        phase_payload.generation_id = 8  # type: ignore[misc]


def test_tool_and_confirmation_messages_include_generation_and_call_identity():
    tool = ToolStartedMessage(
        ToolStartedPayload(3, "call-1", "read_file", "path=README.md", 1.5)
    )
    future: Future[bool] = Future()
    confirmation = ConfirmationRequestedMessage(
        ConfirmationPayload(
            3,
            ConfirmationPreview("command", "Run command", "echo ok"),
            future,
        )
    )

    assert tool.payload.generation_id == 3
    assert tool.payload.call_id == "call-1"
    assert confirmation.payload.generation_id == 3
    assert confirmation.payload.decision is future


def test_activity_state_values_are_stable():
    assert ActivityState.UPLINKING.value == "uplinking"
    assert ActivityState.SYNTHESIZING.value == "synthesizing"
    assert ActivityState.INTERRUPTED.value == "interrupted"


@pytest.mark.asyncio
async def test_css_resource_loads_in_headless_app(tmp_path):
    metadata = SessionMetadata("test", "openai", "model", tmp_path, "main")
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        metadata,
        TuiEventBridge(),
    )

    async with app.run_test(size=(80, 24)):
        assert app.query_one("#app-placeholder").render().plain == "MEWCODE"
