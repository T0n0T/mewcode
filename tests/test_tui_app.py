import asyncio
from io import StringIO
from pathlib import Path

import pytest
from textual.geometry import Spacing
from textual.widgets import Markdown, Static

from mewcode.agent import AgentSession, RunStopped, StopReason
from mewcode.config import LLMConfig
from mewcode.errors import ProviderError
from mewcode.messages import AssistantMessage, ToolResultsMessage, UserMessage
from mewcode.providers.base import (
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
    TokenUsage,
)
from mewcode.tools.base import (
    ConfirmationPreview,
    PreparedToolAction,
    ToolAccess,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace
from mewcode.tui.app import CyberpunkChatApp
from mewcode.tui.metadata import SessionMetadata
from mewcode.tui.plain import PlainChatApp
from mewcode.tui.presentation import ActivityState
from mewcode.tui.widgets import (
    AssistantMessageView,
    ConfirmationModal,
    ConversationView,
    ErrorCard,
    NewOutputIndicator,
    PromptComposer,
    SessionFooter,
    ToolCard,
    UserMessageView,
    WelcomeCard,
)


class ScriptedProvider:
    def __init__(self, scripts=()) -> None:
        self.scripts = iter(scripts)
        self.calls = []
        self.close_calls = 0

    async def stream_response(
        self, history, tools, *, instructions, cancellation
    ):
        self.calls.append((tuple(history), tuple(tools), instructions))
        for event in next(self.scripts):
            cancellation.raise_if_cancelled()
            if isinstance(event, BaseException):
                raise event
            yield event

    async def aclose(self):
        self.close_calls += 1


class RecoveringProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.histories = []
        self.first_text_sent = asyncio.Event()
        self.cancelled = False
        self.close_calls = 0

    async def stream_response(
        self, history, tools, *, instructions, cancellation
    ):
        self.calls += 1
        self.histories.append(tuple(history))
        if self.calls == 1:
            yield ProviderTextDelta("partial")
            self.first_text_sent.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        else:
            yield ProviderTextDelta("recovered")
            yield ProviderResponseCompleted({"response": self.calls})

    async def aclose(self):
        self.close_calls += 1


class ConfirmingTool:
    manages_own_timeout = False
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True
    definition = ToolDefinition(
        "write_test",
        "write test data",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )

    def __init__(self) -> None:
        self.executed = False

    async def prepare(self, arguments, context):
        return PreparedToolAction(
            {},
            ConfirmationPreview("write", "Write safe file", "safe diff"),
        )

    async def execute(self, action, context):
        self.executed = True
        return ToolResult(status="success", data={"full": "hidden result"})


class ReadTool:
    manages_own_timeout = False
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False
    definition = ToolDefinition(
        "read_test",
        "read test data",
        {"type": "object", "properties": {}, "additionalProperties": False},
    )

    def __init__(self) -> None:
        self.executions = 0

    async def prepare(self, arguments, context):
        return PreparedToolAction({}, None)

    async def execute(self, action, context):
        self.executions += 1
        return ToolResult(status="success", data={"content": "hidden result"})


class BlockingReadTool:
    manages_own_timeout = False
    access = ToolAccess.READ_ONLY
    execution_policy = ToolExecutionPolicy.PARALLEL_SAFE
    requires_confirmation = False

    def __init__(self, name, started, both_started, cancelled) -> None:
        self.definition = ToolDefinition(
            name,
            name,
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.started = started
        self.both_started = both_started
        self.cancelled = cancelled

    async def prepare(self, arguments, context):
        return PreparedToolAction({}, None)

    async def execute(self, action, context):
        name = self.definition.name
        self.started.add(name)
        if len(self.started) == 2:
            self.both_started.set()
        await self.both_started.wait()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.add(name)
            raise


class BlockingSideEffectTool:
    manages_own_timeout = False
    access = ToolAccess.MUTATING
    execution_policy = ToolExecutionPolicy.SERIAL
    requires_confirmation = True

    def __init__(self, name="run_command") -> None:
        self.definition = ToolDefinition(
            name,
            name,
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.started = asyncio.Event()
        self.cancelled = False

    async def prepare(self, arguments, context):
        return PreparedToolAction(
            {},
            ConfirmationPreview("command", "Run test command", "safe command"),
        )

    async def execute(self, action, context):
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


class DummySession:
    def __init__(self) -> None:
        self.close_calls = 0

    async def start(self, prompt):
        raise AssertionError("snapshot session must not be started")

    async def close(self):
        self.close_calls += 1


def metadata(tmp_path: Path | None = None):
    return SessionMetadata(
        "test",
        "openai",
        "model",
        tmp_path or Path("/workspace/mewcode"),
        "main",
    )


def completed(*chunks: str, usage: TokenUsage | None = None):
    return [
        *(ProviderTextDelta(chunk) for chunk in chunks),
        ProviderResponseCompleted(
            {"text": "".join(chunks)},
            usage or TokenUsage(None, None, None),
        ),
    ]


def build_session(tmp_path: Path, provider, *, tool=None, tools=()):
    registry = ToolRegistry()
    if tool is not None:
        registry.register(tool)
    for current in tools:
        registry.register(current)
    executor = ToolExecutor(registry, Workspace(tmp_path))
    return AgentSession(provider, registry, executor)


async def wait_for(pilot, predicate, *, attempts: int = 100):
    for _ in range(attempts):
        if predicate():
            return
        await pilot.pause()
    assert predicate()


@pytest.mark.asyncio
async def test_css_resource_loads_in_headless_app(tmp_path: Path):
    app = CyberpunkChatApp(DummySession(), metadata(tmp_path))

    async with app.run_test(size=(80, 24)):
        assert app.query_one(SessionFooter)
        assert app.query_one(WelcomeCard)
        assert app.query_one(PromptComposer).has_focus is True


@pytest.mark.asyncio
async def test_compose_order_places_status_below_composer(tmp_path: Path):
    app = CyberpunkChatApp(DummySession(), metadata(tmp_path))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        children = list(app.screen.children)

        assert isinstance(children[0], ConversationView)
        assert isinstance(children[1], NewOutputIndicator)
        assert children[2].id == "composer-shell"
        assert isinstance(children[3], SessionFooter)
        assert children[4].id == "size-warning"
        assert children[2].region.bottom == children[3].region.y


@pytest.mark.asyncio
async def test_screen_padding_keeps_content_one_cell_from_terminal_edges(
    tmp_path: Path,
):
    app = CyberpunkChatApp(DummySession(), metadata(tmp_path))

    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.screen.styles.padding == Spacing(1, 1, 1, 1)
        assert app.query_one(ConversationView).region.x == 1
        assert app.query_one(SessionFooter).region.right == 79


@pytest.mark.asyncio
async def test_async_worker_normal_turn_streams_markdown_and_restores_prompt(
    tmp_path: Path,
):
    provider = ScriptedProvider([completed("Hello ", "**world**")])
    app = CyberpunkChatApp(
        build_session(tmp_path, provider),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("Hi")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app.activity_state is ActivityState.READY
            and app._active_run is None,
        )

        assert app.query_one(UserMessageView).render().plain == "› Hi"
        markdown = app.query_one(AssistantMessageView).query_one(Markdown)
        assert markdown.source == "Hello **world**"
        assert composer.busy is False
        assert composer.has_focus is True
        source = Path(__file__).parents[1] / "mewcode/tui/app.py"
        text = source.read_text(encoding="utf-8")
        assert "thread" + "=True" not in text
        assert "call_from" + "_thread" not in text


@pytest.mark.asyncio
async def test_rapid_chunks_are_batched_without_loss(
    tmp_path: Path,
    monkeypatch,
):
    chunks = [str(index % 10) for index in range(200)]
    provider = ScriptedProvider([completed(*chunks)])
    app = CyberpunkChatApp(
        build_session(tmp_path, provider),
        metadata(tmp_path),
    )
    writes = 0
    original = AssistantMessageView.append_markdown

    async def tracking_write(self, fragment):
        nonlocal writes
        writes += 1
        await original(self, fragment)

    monkeypatch.setattr(AssistantMessageView, "append_markdown", tracking_write)

    async with app.run_test(size=(80, 24)) as pilot:
        app.query_one(PromptComposer).load_text("rapid")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app._active_run is None)

        markdown = app.query_one(AssistantMessageView).query_one(Markdown)
        assert markdown.source == "".join(chunks)
        assert writes < len(chunks) / 4


@pytest.mark.asyncio
async def test_tool_usage_confirmation_and_progress_share_run_events(tmp_path: Path):
    tool = ConfirmingTool()
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-1",
                    name_delta="write_test",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}, TokenUsage(1, 2, 3)),
            ],
            completed("done", usage=TokenUsage(4, 5, 9)),
        ]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider, tool=tool),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        app.query_one(PromptComposer).load_text("write")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmationModal))
        assert app.activity_state is ActivityState.CONFIRMING
        await pilot.press("y")
        await wait_for(pilot, lambda: app._active_run is None)

        card = app.query_one(ToolCard)
        assert "SUCCESS write_test" in str(card.title)
        assert tool.executed is True
        usage = [item.render().plain for item in app.query(".usage")]
        assert any("total:3" in line for line in usage)
        assert any("total:12" in line for line in usage)
        assert "hidden result" not in card._details.render().plain


@pytest.mark.asyncio
async def test_e2e_cancel_recovery_from_partial_model_allows_follow_up(
    tmp_path: Path,
):
    provider = RecoveringProvider()
    app = CyberpunkChatApp(
        build_session(tmp_path, provider),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await provider.first_text_sent.wait()
        await wait_for(
            pilot,
            lambda: bool(app.query(AssistantMessageView)),
        )
        await pilot.press("escape")
        await wait_for(pilot, lambda: app._active_run is None)

        assert provider.cancelled is True
        first = app.query(AssistantMessageView).first()
        assert first.query_one(".interrupted", Static).render().plain == "INTERRUPTED"
        composer.load_text("second")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        replies = list(app.query(AssistantMessageView))
        assert replies[-1].query_one(Markdown).source == "recovered"
        assert provider.histories[1] == (
            UserMessage("first"),
            UserMessage("second"),
        )


@pytest.mark.asyncio
async def test_e2e_cancel_recovery_from_parallel_tools_allows_follow_up(
    tmp_path: Path,
):
    started = set()
    both_started = asyncio.Event()
    cancelled = set()
    tools = [
        BlockingReadTool("read_a", started, both_started, cancelled),
        BlockingReadTool("read_b", started, both_started, cancelled),
    ]
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    index,
                    call_id_delta=f"call-{name}",
                    name_delta=name,
                    arguments_delta="{}",
                )
                for index, name in enumerate(("read_a", "read_b"))
            ]
            + [ProviderResponseCompleted({})],
            completed("recovered"),
        ]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider, tools=tools),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await both_started.wait()
        await pilot.press("escape")
        await wait_for(pilot, lambda: app._active_run is None)

        assert cancelled == {"read_a", "read_b"}
        composer.load_text("second")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        assert list(app.query(AssistantMessageView))[-1].query_one(
            Markdown
        ).source == "recovered"
        assert provider.calls[1][0] == (
            UserMessage("first"),
            UserMessage("second"),
        )


@pytest.mark.asyncio
async def test_e2e_cancel_recovery_from_confirmation_allows_follow_up(
    tmp_path: Path,
):
    tool = BlockingSideEffectTool("write_wait")
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-write",
                    name_delta="write_wait",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}),
            ],
            completed("recovered"),
        ]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider, tool=tool),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmationModal))
        await pilot.press("ctrl+c")
        await wait_for(pilot, lambda: app._active_run is None)

        assert tool.started.is_set() is False
        composer.load_text("second")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        assert list(app.query(AssistantMessageView))[-1].query_one(
            Markdown
        ).source == "recovered"
        assert provider.calls[1][0] == (
            UserMessage("first"),
            UserMessage("second"),
        )


@pytest.mark.asyncio
async def test_e2e_cancel_recovery_from_active_command_allows_follow_up(
    tmp_path: Path,
):
    tool = BlockingSideEffectTool()
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-command",
                    name_delta="run_command",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}),
            ],
            completed("recovered"),
        ]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider, tool=tool),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await wait_for(pilot, lambda: isinstance(app.screen, ConfirmationModal))
        await pilot.press("y")
        await tool.started.wait()
        await pilot.press("escape")
        await wait_for(pilot, lambda: app._active_run is None)

        assert tool.cancelled is True
        composer.load_text("second")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        assert list(app.query(AssistantMessageView))[-1].query_one(
            Markdown
        ).source == "recovered"
        assert provider.calls[1][0] == (
            UserMessage("first"),
            UserMessage("second"),
        )


@pytest.mark.asyncio
async def test_error_card_allows_a_successful_follow_up_turn(tmp_path: Path):
    provider = ScriptedProvider(
        [[ProviderError("temporary failure")], completed("recovered")]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider),
        metadata(tmp_path),
    )

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("fail")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app._active_run is None)
        assert "The model provider stopped because of an error." in str(
            app.query_one(ErrorCard).title
        )
        assert "temporary failure" not in str(app.query_one(ErrorCard).title)

        composer.load_text("again")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        assert list(app.query(AssistantMessageView))[-1].query_one(
            Markdown
        ).source == "recovered"


@pytest.mark.asyncio
async def test_interface_consumer_failure_cancels_run_and_allows_follow_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    provider = RecoveringProvider()
    app = CyberpunkChatApp(
        build_session(tmp_path, provider),
        metadata(tmp_path),
    )
    original_queue_text = app._queue_text
    fail_next_delta = True

    def failing_once(event) -> None:
        nonlocal fail_next_delta
        if fail_next_delta:
            fail_next_delta = False
            raise RuntimeError("simulated interface consumer failure")
        original_queue_text(event)

    monkeypatch.setattr(app, "_queue_text", failing_once)

    async with app.run_test(size=(80, 24)) as pilot:
        composer = app.query_one(PromptComposer)
        composer.load_text("first")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app._active_run is None)

        assert provider.cancelled is True
        assert "Internal interface worker failure" in str(
            app.query_one(ErrorCard).title
        )

        composer.load_text("second")
        await pilot.press("enter")
        await wait_for(
            pilot,
            lambda: app._active_run is None
            and app.activity_state is ActivityState.READY,
        )
        assert list(app.query(AssistantMessageView))[-1].query_one(
            Markdown
        ).source == "recovered"


@pytest.mark.asyncio
async def test_e2e_consumer_equivalence_preserves_requests_history_and_result(
    tmp_path: Path,
):
    def scripts():
        return [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-read",
                    name_delta="read_test",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({"round": 1}),
            ],
            completed("same final answer"),
        ]

    def normalize_history(history):
        normalized = []
        for message in history:
            if isinstance(message, UserMessage):
                normalized.append(("user", message.content))
            elif isinstance(message, AssistantMessage):
                normalized.append(("assistant", message.content))
            elif isinstance(message, ToolResultsMessage):
                normalized.append(
                    (
                        "tools",
                        tuple(
                            (
                                feedback.call_id,
                                feedback.name,
                                feedback.result.status,
                            )
                            for feedback in message.results
                        ),
                    )
                )
        return tuple(normalized)

    def provider_trace(provider):
        return [
            (
                normalize_history(history),
                tuple(definition.name for definition in definitions),
                instructions,
            )
            for history, definitions, instructions in provider.calls
        ]

    direct_root = tmp_path / "direct"
    plain_root = tmp_path / "plain"
    fullscreen_root = tmp_path / "fullscreen"
    for root in (direct_root, plain_root, fullscreen_root):
        root.mkdir()

    direct_provider = ScriptedProvider(scripts())
    direct_tool = ReadTool()
    direct_session = build_session(
        direct_root,
        direct_provider,
        tool=direct_tool,
    )
    direct_events = [event async for event in await direct_session.start("inspect")]

    plain_provider = ScriptedProvider(scripts())
    plain_tool = ReadTool()
    plain_session = build_session(
        plain_root,
        plain_provider,
        tool=plain_tool,
    )
    plain_output = StringIO()
    plain = PlainChatApp(
        plain_session,
        LLMConfig(
            "test",
            "openai",
            "model",
            "https://example.test/v1",
            "safe-key",
        ),
        input_stream=StringIO("inspect\nexit\n"),
        output_stream=plain_output,
    )
    assert await plain.run() == 0

    fullscreen_provider = ScriptedProvider(scripts())
    fullscreen_tool = ReadTool()
    fullscreen_session = build_session(
        fullscreen_root,
        fullscreen_provider,
        tool=fullscreen_tool,
    )
    fullscreen = CyberpunkChatApp(
        fullscreen_session,
        metadata(fullscreen_root),
    )
    async with fullscreen.run_test(size=(80, 24)) as pilot:
        fullscreen.query_one(PromptComposer).load_text("inspect")
        await pilot.press("enter")
        await wait_for(pilot, lambda: fullscreen._active_run is None)

    assert isinstance(direct_events[-1], RunStopped)
    assert direct_events[-1].reason is StopReason.COMPLETED
    assert "[COMPLETED]" in plain_output.getvalue()
    assert fullscreen.activity_state is ActivityState.READY
    assert [direct_tool.executions, plain_tool.executions, fullscreen_tool.executions] == [
        1,
        1,
        1,
    ]
    assert provider_trace(direct_provider) == provider_trace(plain_provider)
    assert provider_trace(direct_provider) == provider_trace(fullscreen_provider)
    assert normalize_history(direct_session.history) == normalize_history(
        plain_session.history
    )
    assert normalize_history(direct_session.history) == normalize_history(
        fullscreen_session.history
    )


@pytest.mark.asyncio
async def test_exit_command_closes_session_and_provider(tmp_path: Path):
    provider = ScriptedProvider()
    session = build_session(tmp_path, provider)
    app = CyberpunkChatApp(session, metadata(tmp_path))

    async with app.run_test(size=(80, 24)) as pilot:
        app.query_one(PromptComposer).load_text("exit")
        await pilot.press("enter")
        await pilot.pause()

    assert provider.close_calls == 1


def snapshot_metadata():
    return SessionMetadata(
        "snapshot",
        "openai",
        "gpt-cyber",
        Path("/workspace/mewcode"),
        "main",
    )


def test_snapshot_wide_welcome(snap_compare, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = CyberpunkChatApp(DummySession(), snapshot_metadata())

    assert snap_compare(app, terminal_size=(120, 36))


def test_snapshot_tool_turn_at_eighty_columns(snap_compare, monkeypatch, tmp_path):
    monkeypatch.delenv("NO_COLOR", raising=False)
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-1",
                    name_delta="read_test",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}, TokenUsage(12, 3, 15)),
            ],
            completed("final answer", usage=TokenUsage(20, 4, 24)),
        ]
    )
    app = CyberpunkChatApp(
        build_session(tmp_path, provider, tool=ReadTool()),
        snapshot_metadata(),
    )

    async def complete_turn(pilot):
        app.query_one(PromptComposer).load_text("Inspect README")
        await pilot.press("enter")
        await wait_for(pilot, lambda: app._active_run is None)

    assert snap_compare(
        app,
        terminal_size=(80, 24),
        run_before=complete_turn,
    )


def test_snapshot_narrow_welcome(snap_compare, monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    app = CyberpunkChatApp(DummySession(), snapshot_metadata())

    assert snap_compare(app, terminal_size=(60, 18))


def test_snapshot_no_color_welcome(snap_compare, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = CyberpunkChatApp(DummySession(), snapshot_metadata())

    assert snap_compare(app, terminal_size=(80, 24))
