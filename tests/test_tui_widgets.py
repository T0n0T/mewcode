from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Markdown, Static

from mewcode.tools.base import ConfirmationPreview
from mewcode.tui.events import (
    ActivityState,
    ToolFinishedPayload,
    ToolStartedPayload,
    TruncationPresentation,
    TurnErrorPayload,
)
from mewcode.tui.metadata import SessionMetadata
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


def metadata(branch="main"):
    return SessionMetadata(
        config_name="test",
        provider="openai",
        model="gpt-cyber",
        workspace=Path("/workspace/project"),
        git_branch=branch,
    )


class ChromeApp(App[None]):
    def __init__(self, branch="main"):
        super().__init__()
        self.branch = branch

    def compose(self) -> ComposeResult:
        yield SessionHeader(metadata(self.branch))
        yield WelcomeCard(metadata(self.branch))


@pytest.mark.asyncio
async def test_header_renders_session_fields_and_updates_activity():
    app = ChromeApp()

    async with app.run_test():
        header = app.query_one(SessionHeader)
        assert "MEWCODE" in header.query_one("#brand", Static).render().plain
        assert "gpt-cyber" in header.query_one("#header-model", Static).render().plain
        assert "/workspace/project" in header.query_one(
            "#header-workspace", Static
        ).render().plain
        assert "git:main" in header.query_one("#header-branch", Static).render().plain

        header.set_activity(ActivityState.UPLINKING, "gpt-cyber")
        assert header.query_one("#connection-status", Static).render().plain == (
            "UPLINKING:gpt-cyber"
        )


@pytest.mark.asyncio
async def test_header_and_welcome_degrade_without_branch_or_secret():
    app = ChromeApp(branch=None)

    async with app.run_test():
        assert app.query_one("#header-branch", Static).render().plain == ""
        welcome = app.query_one(WelcomeCard).render().plain
        assert "MEWCODE // CYBER TERMINAL" in welcome
        assert "gpt-cyber" in welcome
        assert "metadata-secret" not in welcome


def test_activity_indicator_renders_each_state_and_elapsed_time():
    now = [10.0]
    indicator = ActivityIndicator(clock=lambda: now[0])

    indicator.set_activity(ActivityState.UPLINKING, "gpt-cyber")
    now[0] = 11.25
    indicator._tick()
    text = indicator.render().plain
    assert "UPLINKING gpt-cyber" in text
    assert "1.2s" in text

    indicator.set_activity(ActivityState.EXECUTING, "read_file")
    assert "EXECUTING read_file" in indicator.render().plain
    indicator.set_activity(ActivityState.SYNTHESIZING)
    assert "SYNTHESIZING" in indicator.render().plain
    indicator.set_activity(ActivityState.INTERRUPTED)
    assert indicator.render().plain == "◆ INTERRUPTED"


def test_activity_indicator_only_ticks_while_activity_is_running():
    now = [20.0]
    indicator = ActivityIndicator(clock=lambda: now[0])
    indicator.set_activity(ActivityState.READY)
    ready = indicator.render().plain
    now[0] = 21.0
    indicator._tick()
    assert indicator.render().plain == ready

    indicator.set_activity(ActivityState.UPLINKING, "model")
    active = indicator.render().plain
    now[0] = 22.0
    indicator._tick()
    assert indicator.render().plain != active


def test_new_output_indicator_tracks_visibility_and_count():
    indicator = NewOutputIndicator()

    assert indicator.display is False
    indicator.set_count(3)
    assert indicator.display is True
    assert str(indicator.label) == "NEW OUTPUT (3) ↓"
    indicator.set_count(0)
    assert indicator.display is False


def test_ascii_widget_variants_use_only_ascii_presentation_glyphs():
    indicator = ActivityIndicator(clock=lambda: 1.0, unicode=False)
    indicator.set_activity(ActivityState.UPLINKING, "model")
    new_output = NewOutputIndicator(unicode=False)
    new_output.set_count(2)
    tool = ToolCard(
        ToolStartedPayload(1, "call-1", "read_file", "path=README.md", 1.0),
        unicode=False,
    )
    tool.finish(
        ToolFinishedPayload(
            1,
            "call-1",
            "read_file",
            "success",
            9,
            None,
            None,
        )
    )
    error = ErrorCard(
        TurnErrorPayload(1, "Network unavailable"),
        unicode=False,
    )

    values = (
        indicator.render().plain,
        str(new_output.label),
        str(tool.title),
        str(error.title),
        PromptComposer(unicode=False).placeholder,
    )
    for value in values:
        value.encode("ascii")


def test_prompt_history_preserves_draft_and_navigation_boundaries():
    history = PromptHistory()
    history.record("first")
    history.record("second\nline")

    assert history.previous("current draft") == "second\nline"
    assert history.previous("ignored") == "first"
    assert history.previous("ignored") == "first"
    assert history.next() == "second\nline"
    assert history.next() == "current draft"
    assert history.next() == "current draft"


def test_prompt_history_ignores_blank_and_allows_repeated_entries():
    history = PromptHistory()
    history.record("   ")
    history.record("same")
    history.record("same")

    assert history.entries == ("same", "same")
    assert history.previous("draft") == "same"
    history.reset_navigation()
    assert history.next() == ""


class ComposerApp(App[None]):
    def __init__(self):
        super().__init__()
        self.submissions = []

    def compose(self) -> ComposeResult:
        yield PromptComposer()

    def on_prompt_composer_submitted(
        self,
        event: PromptComposer.Submitted,
    ) -> None:
        self.submissions.append(event.prompt)


@pytest.mark.asyncio
async def test_composer_submits_and_keeps_multiline_input_as_one_prompt():
    app = ComposerApp()

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.focus()
        await pilot.press("h", "i", "shift+enter", "x")
        assert composer.text == "hi\nx"
        await pilot.press("enter")
        await pilot.pause()

        assert app.submissions == ["hi\nx"]


@pytest.mark.asyncio
async def test_composer_busy_state_preserves_draft_and_suppresses_submit():
    app = ComposerApp()

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.focus()
        composer.insert("next task\nwith details")
        composer.set_busy(True)
        await pilot.press("enter")
        await pilot.pause()

        assert app.submissions == []
        assert composer.text == "next task\nwith details"
        assert composer.styles.height.value == 2


@pytest.mark.asyncio
async def test_composer_navigates_history_only_from_empty_or_history_state():
    app = ComposerApp()

    async with app.run_test() as pilot:
        composer = app.query_one(PromptComposer)
        composer.prompt_history.record("first")
        composer.prompt_history.record("second")
        composer.focus()

        await pilot.press("up")
        assert composer.text == "second"
        await pilot.press("up")
        assert composer.text == "first"
        await pilot.press("down")
        assert composer.text == "second"
        await pilot.press("down")
        assert composer.text == ""


class ConversationWidgetsApp(App[None]):
    def compose(self) -> ComposeResult:
        yield UserMessageView("hello")
        yield UserMessageView("ascii", unicode=False)
        yield AssistantMessageView()


@pytest.mark.asyncio
async def test_message_views_use_visual_anchors_without_role_label():
    app = ConversationWidgetsApp()

    async with app.run_test():
        users = list(app.query(UserMessageView))
        assistant = app.query_one(AssistantMessageView)
        assert users[0].render().plain == "› hello"
        assert users[1].render().plain == "> ascii"
        assert assistant.query_one(".message-marker", Static).render().plain == "◆"
        assert "assistant" not in app.export_screenshot().lower()


@pytest.mark.asyncio
async def test_assistant_message_streams_markdown_and_marks_interruption():
    app = ConversationWidgetsApp()

    async with app.run_test() as pilot:
        assistant = app.query_one(AssistantMessageView)
        await assistant.append_markdown("# Head")
        await assistant.append_markdown(
            "ing\n\n- item\n\n```python\nprint('x')\n```"
        )
        await pilot.pause()
        markdown = assistant.query_one(Markdown)
        assert markdown.source == (
            "# Heading\n\n- item\n\n```python\nprint('x')\n```"
        )

        await assistant.mark_interrupted()
        await pilot.pause()
        assert assistant.query_one(".interrupted", Static).render().plain == "INTERRUPTED"


class ScrollApp(App[None]):
    def compose(self) -> ComposeResult:
        yield ConversationView()


@pytest.mark.asyncio
async def test_conversation_freezes_and_restores_output_following():
    app = ScrollApp()

    async with app.run_test(size=(40, 8)):
        conversation = app.query_one(ConversationView)
        for index in range(20):
            await conversation.append_widget(Static(f"line {index}"))

        conversation.freeze_following()
        previous_offset = conversation.scroll_y
        await conversation.append_widget(Static("new line"))
        assert conversation.follow_output is False
        assert conversation.unread_output == 1
        assert conversation.scroll_y == previous_offset

        conversation.return_to_bottom()
        assert conversation.follow_output is True
        assert conversation.unread_output == 0


@pytest.mark.asyncio
async def test_frozen_conversation_stays_frozen_across_resize():
    app = ScrollApp()

    async with app.run_test(size=(40, 8)) as pilot:
        conversation = app.query_one(ConversationView)
        for index in range(30):
            await conversation.append_widget(Static(f"line {index}"))
        await pilot.pause()
        conversation.freeze_following()
        conversation.scroll_to(y=5, animate=False, force=True)
        await pilot.pause()
        previous_offset = conversation.scroll_y

        await pilot.resize_terminal(44, 8)
        await conversation.append_widget(Static("new line"))
        await pilot.pause()

        assert conversation.follow_output is False
        assert conversation.scroll_y == previous_offset
        assert conversation.unread_output == 1


class CardsApp(App[None]):
    def compose(self) -> ComposeResult:
        yield ToolCard(
            ToolStartedPayload(
                1,
                "call-1",
                "read_file",
                "path=README.md",
                1.0,
            )
        )
        yield ErrorCard(
            TurnErrorPayload(1, "Network unavailable", "safe technical detail")
        )


@pytest.mark.asyncio
async def test_tool_card_updates_in_place_and_error_details_stay_collapsed():
    app = CardsApp()

    async with app.run_test():
        card = app.query_one(ToolCard)
        assert card.collapsed is True
        assert "EXECUTING read_file" in str(card.title)

        card.finish(
            ToolFinishedPayload(
                1,
                "call-1",
                "read_file",
                "error",
                9,
                "file missing",
                TruncationPresentation(
                    "characters",
                    100,
                    10,
                    "narrow the read",
                ),
            )
        )
        assert "ERROR read_file · 9ms" in str(card.title)
        assert "status-error" in card.classes
        assert app.query_one(ErrorCard).collapsed is True
        assert "Network unavailable" in str(app.query_one(ErrorCard).title)


class ModalApp(App[None]):
    def __init__(self):
        super().__init__()
        self.result: bool | None = None

    def on_mount(self) -> None:
        self.push_screen(
            ConfirmationModal(
                ConfirmationPreview(
                    "command",
                    "Run command",
                    "echo hello",
                )
            ),
            self._record,
        )

    def _record(self, result: bool) -> None:
        self.result = result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [("escape", False), ("n", False), ("y", True)],
)
async def test_confirmation_modal_has_safe_keyboard_decisions(key, expected):
    app = ModalApp()

    async with app.run_test() as pilot:
        await pilot.pause()
        if expected is False:
            assert app.screen.query_one("#reject").has_focus is True
        await pilot.press(key)
        await pilot.pause()
        assert app.result is expected
