from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from mewcode.tui.events import ActivityState
from mewcode.tui.metadata import SessionMetadata
from mewcode.tui.widgets.chrome import (
    ActivityIndicator,
    NewOutputIndicator,
    SessionHeader,
    WelcomeCard,
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


def test_new_output_indicator_tracks_visibility_and_count():
    indicator = NewOutputIndicator()

    assert indicator.display is False
    indicator.set_count(3)
    assert indicator.display is True
    assert str(indicator.label) == "NEW OUTPUT (3) ↓"
    indicator.set_count(0)
    assert indicator.display is False
