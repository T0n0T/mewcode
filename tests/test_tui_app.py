from concurrent.futures import Future
from dataclasses import FrozenInstanceError
from pathlib import Path
from threading import Event

import pytest
from textual.css.query import NoMatches
from textual.widgets import Markdown, Static

from mewcode.errors import MewCodeError
from mewcode.providers.base import ToolCall
from mewcode.tools.base import ConfirmationPreview, ToolResult
from mewcode.tui.events import (
    ActivityState,
    ConfirmationPayload,
    ConfirmationRequestedMessage,
    ToolStartedMessage,
    ToolStartedPayload,
    TurnPhaseMessage,
    TurnPhasePayload,
    TurnTextMessage,
    TurnTextPayload,
)
from mewcode.tui.app import CyberpunkChatApp
from mewcode.tui.interaction import TuiEventBridge, TuiToolInteraction
from mewcode.tui.metadata import SessionMetadata
from mewcode.tui.widgets import (
    ActivityIndicator,
    AssistantMessageView,
    ConfirmationModal,
    ErrorCard,
    PromptComposer,
    SessionHeader,
    ToolCard,
    UserMessageView,
    WelcomeCard,
)
from mewcode.turns import (
    TurnCompleted,
    TurnPhase,
    TurnPhaseChanged,
    TurnTextDelta,
)


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
        assert app.query_one(SessionHeader)
        assert app.query_one(WelcomeCard)
        assert app.query_one(PromptComposer).has_focus is True


def metadata(tmp_path):
    return SessionMetadata("test", "openai", "gpt-cyber", tmp_path, "main")


def snapshot_metadata():
    return SessionMetadata(
        "demo",
        "openai",
        "gpt-cyber",
        Path("/workspace/mewcode"),
        "main",
    )


class FakeRuntime:
    def __init__(self, events):
        self.events = list(events)
        self.calls = []

    def stream_turn(self, prompt, cancellation):
        self.calls.append(prompt)
        for event in self.events:
            cancellation.raise_if_cancelled()
            yield event


async def wait_for(pilot, predicate, *, attempts=100):
    for _ in range(attempts):
        if predicate():
            return
        await pilot.pause(0.01)
    assert predicate()


@pytest.mark.asyncio
async def test_normal_turn_streams_markdown_and_restores_prompt(tmp_path):
    runtime = FakeRuntime(
        [
            TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE),
            TurnTextDelta("Hel"),
            TurnTextDelta("lo"),
            TurnCompleted(),
        ]
    )
    app = CyberpunkChatApp(runtime, metadata(tmp_path), TuiEventBridge())  # type: ignore[arg-type]

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("Hi")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)

        assert runtime.calls == ["Hi"]
        assert app.query_one(UserMessageView).render().plain == "› Hi"
        assistant = app.query_one(AssistantMessageView)
        assert assistant.query_one(Markdown).source == "Hello"
        assert composer.text == ""
        assert composer.busy is False
        assert composer.has_focus is True


class BlockingRuntime:
    def __init__(self, *, partial=False):
        self.started = Event()
        self.release = Event()
        self.calls = []
        self.partial = partial

    def stream_turn(self, prompt, cancellation):
        self.calls.append(prompt)
        yield TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
        if self.partial:
            yield TurnTextDelta("partial")
        self.started.set()
        while not self.release.wait(timeout=0.01):
            cancellation.raise_if_cancelled()
        cancellation.raise_if_cancelled()
        yield TurnTextDelta("done")
        yield TurnCompleted()


@pytest.mark.asyncio
async def test_first_token_wait_shows_uplinking_then_transforms(tmp_path):
    runtime = BlockingRuntime()
    app = CyberpunkChatApp(runtime, metadata(tmp_path), TuiEventBridge())  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("wait")
        await pilot.press("enter")
        assert runtime.started.wait(timeout=1)
        await pilot.pause()

        indicator = app.query_one(ActivityIndicator)
        assert "UPLINKING gpt-cyber" in indicator.render().plain

        runtime.release.set()
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)
        with pytest.raises(NoMatches):
            app.query_one(ActivityIndicator)
        assert app.query_one(AssistantMessageView).query_one(Markdown).source == "done"


@pytest.mark.asyncio
async def test_rapid_chunks_are_batched_without_loss(tmp_path):
    text = "".join(str(index % 10) for index in range(500))
    runtime = FakeRuntime(
        [
            TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE),
            *(TurnTextDelta(character) for character in text),
            TurnCompleted(),
        ]
    )
    messages = []
    app = CyberpunkChatApp(runtime, metadata(tmp_path), TuiEventBridge())  # type: ignore[arg-type]

    async with app.run_test(message_hook=messages.append) as pilot:
        app.query_one(PromptComposer).load_text("rapid")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)

        assert app.query_one(AssistantMessageView).query_one(Markdown).source == text
        text_messages = [
            message for message in messages if isinstance(message, TurnTextMessage)
        ]
        assert len(text_messages) < len(text) // 10


class ToolRuntime:
    def __init__(self, interaction, *, confirm=False, fail=False):
        self.interaction = interaction
        self.confirm = confirm
        self.fail = fail
        self.approved = None

    def stream_turn(self, prompt, cancellation):
        yield TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
        call = ToolCall("call-1", "read_file", {"path": "README.md"})
        self.interaction.tool_started(call)
        if self.confirm:
            self.approved = self.interaction.confirm(
                ConfirmationPreview(
                    "command",
                    "Run command",
                    "echo safe",
                )
            )
        result = ToolResult(
            status="error" if self.fail else ("success" if self.approved is not False else "rejected"),
            duration_ms=12,
        )
        self.interaction.tool_finished(call, result)
        yield TurnPhaseChanged(TurnPhase.FINAL_RESPONSE)
        yield TurnTextDelta("final answer")
        yield TurnCompleted()


@pytest.mark.asyncio
async def test_tool_turn_updates_card_and_synthesizes_final_response(tmp_path):
    bridge = TuiEventBridge()
    interaction = TuiToolInteraction(bridge)
    runtime = ToolRuntime(interaction)
    app = CyberpunkChatApp(runtime, metadata(tmp_path), bridge)  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        app.query_one(PromptComposer).load_text("read")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)

        card = app.query_one(ToolCard)
        assert "SUCCESS read_file · 12ms" in str(card.title)
        assistants = list(app.query(AssistantMessageView))
        assert assistants[-1].query_one(Markdown).source == "final answer"


@pytest.mark.asyncio
async def test_confirmation_modal_rejects_and_unblocks_tool_worker(tmp_path):
    bridge = TuiEventBridge()
    interaction = TuiToolInteraction(bridge)
    runtime = ToolRuntime(interaction, confirm=True)
    app = CyberpunkChatApp(runtime, metadata(tmp_path), bridge)  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        app.query_one(PromptComposer).load_text("confirm")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmationModal))
        await pilot.press("escape")
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)

        assert runtime.approved is False
        assert "REJECTED" in str(app.query_one(ToolCard).title)


class FailingRuntime:
    def stream_turn(self, prompt, cancellation):
        yield TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
        yield TurnTextDelta("partial")
        raise MewCodeError("temporary failure")


@pytest.mark.asyncio
async def test_error_card_preserves_partial_output_and_restores_input(tmp_path):
    app = CyberpunkChatApp(
        FailingRuntime(),  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        app.query_one(PromptComposer).load_text("fail")
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(list(app.query(ErrorCard))))

        assert app.query_one(AssistantMessageView).query_one(Markdown).source == "partial"
        assert "temporary failure" in str(app.query_one(ErrorCard).title)
        assert app.activity_state is ActivityState.READY
        assert app.query_one(PromptComposer).busy is False


class UnexpectedFailingRuntime:
    def stream_turn(self, prompt, cancellation):
        yield TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE)
        raise RuntimeError("internal implementation detail")


@pytest.mark.asyncio
async def test_unexpected_error_is_sanitized_and_restores_ready(tmp_path):
    app = CyberpunkChatApp(
        UnexpectedFailingRuntime(),  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        app.query_one(PromptComposer).load_text("fail unexpectedly")
        await pilot.press("enter")
        await wait_for(pilot, lambda: bool(list(app.query(ErrorCard))))

        card = app.query_one(ErrorCard)
        assert "Internal turn worker failure." in str(card.title)
        assert "internal implementation detail" not in str(card.render())
        assert app.activity_state is ActivityState.READY
        assert app.query_one(PromptComposer).busy is False


@pytest.mark.asyncio
async def test_interrupt_marks_partial_and_ignores_stale_events(tmp_path):
    runtime = BlockingRuntime(partial=True)
    app = CyberpunkChatApp(runtime, metadata(tmp_path), TuiEventBridge())  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("interrupt")
        await pilot.press("enter")
        assert runtime.started.wait(timeout=1)
        await wait_for(
            pilot,
            lambda: bool(list(app.query(AssistantMessageView))),
        )
        await pilot.press("escape")
        await wait_for(
            pilot,
            lambda: app._active_generation is None,
        )

        assistant = app.query_one(AssistantMessageView)
        assert assistant.query_one(".interrupted").render().plain == "INTERRUPTED"
        assert app.activity_state is ActivityState.INTERRUPTED
        source = assistant.query_one(Markdown).source

        app.post_message(TurnTextMessage(TurnTextPayload(1, "late")))
        await pilot.pause()
        assert assistant.query_one(Markdown).source == source


@pytest.mark.asyncio
async def test_busy_composer_keeps_next_draft_without_second_turn(tmp_path):
    runtime = BlockingRuntime()
    app = CyberpunkChatApp(runtime, metadata(tmp_path), TuiEventBridge())  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        assert runtime.started.wait(timeout=1)
        composer.load_text("next")
        await pilot.press("enter")
        assert runtime.calls == ["first"]
        assert composer.text == "next"

        await pilot.press("escape")
        await wait_for(pilot, lambda: app._active_generation is None)
        assert composer.text == "next"


@pytest.mark.asyncio
async def test_ctrl_c_clears_draft_and_resets_exit_arming(tmp_path):
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("draft")
        await pilot.press("ctrl+c")
        assert composer.text == ""

        await pilot.press("ctrl+c")
        assert "Press Ctrl+C again" in app.query_one(
            "#exit-hint", Static
        ).render().plain

        composer.load_text("new draft")
        await pilot.press("ctrl+c")
        assert composer.text == ""
        assert app._exit_armed_until == 0.0
        assert app.query_one("#exit-hint", Static).render().plain == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["exit", "quit"])
async def test_exit_commands_close_without_starting_a_turn(tmp_path, command):
    runtime = FakeRuntime([])
    app = CyberpunkChatApp(
        runtime,  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        app.query_one(PromptComposer).load_text(command)
        await pilot.press("enter")
        await pilot.pause()

    assert app.return_value == 0
    assert runtime.calls == []


@pytest.mark.asyncio
async def test_ctrl_d_on_empty_composer_exits(tmp_path):
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        await pilot.press("ctrl+d")
        await pilot.pause()

    assert app.return_value == 0


@pytest.mark.asyncio
async def test_second_ctrl_c_within_window_exits(tmp_path):
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
    )

    async with app.run_test() as pilot:
        await pilot.press("ctrl+c")
        await pilot.press("ctrl+c")
        await pilot.pause()

    assert app.return_value == 0


@pytest.mark.asyncio
async def test_interrupt_closes_confirmation_and_ignores_late_completion(tmp_path):
    bridge = TuiEventBridge()
    runtime = ToolRuntime(TuiToolInteraction(bridge), confirm=True)
    app = CyberpunkChatApp(runtime, metadata(tmp_path), bridge)  # type: ignore[arg-type]

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("confirm")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmationModal))
        composer.load_text("next draft")

        await pilot.press("ctrl+c")
        await wait_for(pilot, lambda: app._active_generation is None)

        assert not isinstance(app.screen, ConfirmationModal)
        assert app.activity_state is ActivityState.INTERRUPTED
        assert composer.text == "next draft"
        assert composer.busy is False
        assert not list(app.query(AssistantMessageView))


@pytest.mark.asyncio
async def test_responsive_classes_and_ascii_messages(tmp_path):
    runtime = FakeRuntime(
        [
            TurnPhaseChanged(TurnPhase.INITIAL_RESPONSE),
            TurnCompleted(),
        ]
    )
    app = CyberpunkChatApp(
        runtime,  # type: ignore[arg-type]
        metadata(tmp_path),
        TuiEventBridge(),
        unicode_output=False,
    )

    async with app.run_test(size=(120, 36)) as pilot:
        assert "wide" in app.screen.classes
        await pilot.resize_terminal(80, 24)
        assert "compact" in app.screen.classes
        await pilot.resize_terminal(60, 18)
        assert "narrow" in app.screen.classes
        await pilot.resize_terminal(40, 10)
        assert "too-small" in app.screen.classes
        await pilot.resize_terminal(80, 24)

        composer = app.query_one(PromptComposer)
        assert app.query_one("#brand", Static).render().plain == "* MEWCODE"
        assert composer.placeholder == "Describe a task..."
        assert "48x14" in app.query_one("#size-warning", Static).render().plain
        composer.load_text("ascii")
        await pilot.press("enter")
        await wait_for(pilot, lambda: runtime.calls == ["ascii"])
        await wait_for(pilot, lambda: app.activity_state is ActivityState.READY)
        assert app.query_one(UserMessageView).render().plain == "> ascii"


def test_snapshot_wide_welcome(snap_compare, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        snapshot_metadata(),
        TuiEventBridge(),
    )

    assert snap_compare(app, terminal_size=(120, 36))


def test_snapshot_tool_turn_at_eighty_columns(snap_compare, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    bridge = TuiEventBridge()
    runtime = ToolRuntime(TuiToolInteraction(bridge))
    app = CyberpunkChatApp(
        runtime,  # type: ignore[arg-type]
        snapshot_metadata(),
        bridge,
    )

    async def complete_tool_turn(pilot):
        app.query_one(PromptComposer).load_text("Inspect README")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app.activity_state is ActivityState.READY,
        )

    assert snap_compare(
        app,
        terminal_size=(80, 24),
        run_before=complete_tool_turn,
    )


def test_snapshot_narrow_welcome(snap_compare, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        snapshot_metadata(),
        TuiEventBridge(),
    )

    assert snap_compare(app, terminal_size=(60, 18))


def test_snapshot_no_color_welcome(snap_compare, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = CyberpunkChatApp(
        None,  # type: ignore[arg-type]
        snapshot_metadata(),
        TuiEventBridge(),
    )

    assert snap_compare(app, terminal_size=(80, 24))
