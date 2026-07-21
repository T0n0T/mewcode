import ast
import asyncio
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest

import mewcode.agent as agent_api
from mewcode.agent.events import RunStarted, RunStopped
from mewcode.agent.session import AgentSession
from mewcode.agent.types import (
    AgentRequest,
    PlanStatus,
    RunMode,
    RunPhase,
    StopReason,
    StoredPlan,
)
from mewcode.errors import MewCodeError, ProviderError
from mewcode.messages import AssistantMessage, ToolResultsMessage, UserMessage
from mewcode.prompting import (
    EnvironmentSnapshot,
    PromptBuilder,
    PromptOptions,
)
from mewcode.providers.base import (
    ProviderResponseCompleted,
    ProviderTextDelta,
    ProviderToolCallDelta,
)
from mewcode.tools.base import (
    PreparedToolAction,
    ToolAccess,
    ToolDefinition,
    ToolExecutionPolicy,
    ToolResult,
)
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry
from mewcode.tools.workspace import Workspace


class ScriptedProvider:
    def __init__(self, scripts=()) -> None:
        self.scripts = iter(scripts)
        self.calls = []
        self.close_calls = 0

    async def stream_response(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        for event in next(self.scripts):
            cancellation.raise_if_cancelled()
            if isinstance(event, BaseException):
                raise event
            yield event

    async def aclose(self):
        self.close_calls += 1


class BlockingProvider(ScriptedProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()

    async def stream_response(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        self.entered.set()
        await asyncio.Event().wait()
        if False:
            yield ProviderTextDelta("")


class CompletingThenBlockingProvider(ScriptedProvider):
    def __init__(self, first_text: str, retry_text: str | None = None) -> None:
        super().__init__()
        self.first_text = first_text
        self.retry_text = retry_text
        self.entered = asyncio.Event()

    async def stream_response(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        if len(self.calls) == 1:
            yield ProviderTextDelta(self.first_text)
            yield ProviderResponseCompleted({"text": self.first_text})
            return
        if len(self.calls) == 2:
            self.entered.set()
            await asyncio.Event().wait()
            if False:
                yield ProviderTextDelta("")
            return
        assert self.retry_text is not None
        yield ProviderTextDelta(self.retry_text)
        yield ProviderResponseCompleted({"text": self.retry_text})


class CancellableThenCompletingProvider(ScriptedProvider):
    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def stream_response(self, request, *, cancellation):
        self.calls.append((request, cancellation))
        if len(self.calls) == 1:
            self.entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            if False:
                yield ProviderTextDelta("")
            return
        yield ProviderTextDelta("follow-up complete")
        yield ProviderResponseCompleted({"text": "follow-up complete"})


class FakeTool:
    manages_own_timeout = False
    requires_confirmation = False

    def __init__(self, name: str, access: ToolAccess) -> None:
        self.definition = ToolDefinition(
            name,
            name,
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.access = access
        self.execution_policy = (
            ToolExecutionPolicy.PARALLEL_SAFE
            if access is ToolAccess.READ_ONLY
            else ToolExecutionPolicy.SERIAL
        )
        self.executions = 0

    async def prepare(self, arguments, context):
        return PreparedToolAction({}, None)

    async def execute(self, action, context):
        self.executions += 1
        return ToolResult(status="success")


def build_session(tmp_path: Path, provider, **kwargs):
    registry = ToolRegistry()
    registry.register(FakeTool("read", ToolAccess.READ_ONLY))
    registry.register(FakeTool("write", ToolAccess.MUTATING))
    executor = ToolExecutor(registry, Workspace(tmp_path))
    return AgentSession(provider, registry, executor, **kwargs)


def completed(text: str):
    return [ProviderTextDelta(text), ProviderResponseCompleted({"text": text})]


def tool_completed(call_id: str, name: str):
    return [
        ProviderToolCallDelta(
            0,
            call_id_delta=call_id,
            name_delta=name,
            arguments_delta="{}",
        ),
        ProviderResponseCompleted({"call": call_id}),
    ]


async def consume(run):
    return [event async for event in run]


def test_agent_types_have_stable_values():
    assert [mode.value for mode in RunMode] == ["execute", "plan", "do"]
    assert [phase.value for phase in RunPhase] == [
        "waiting_model",
        "streaming_model",
        "executing_tools",
        "waiting_confirmation",
        "feeding_back",
        "stopping",
    ]
    assert [reason.value for reason in StopReason] == [
        "completed",
        "iteration_limit",
        "cancelled",
        "unknown_tool_limit",
        "provider_error",
        "invalid_request",
        "internal_error",
    ]
    assert [status.value for status in PlanStatus] == ["ready", "completed"]


def test_agent_request_distinguishes_all_modes_and_is_frozen():
    execute = AgentRequest(RunMode.EXECUTE, "task", "all")
    plan = AgentRequest(RunMode.PLAN, "task", "read_only")
    do = AgentRequest(RunMode.DO, "saved plan", "all", "plan-1")

    assert (execute.mode, execute.tool_scope) == (RunMode.EXECUTE, "all")
    assert (plan.mode, plan.tool_scope) == (RunMode.PLAN, "read_only")
    assert (do.mode, do.source_plan_id) == (RunMode.DO, "plan-1")
    assert not hasattr(execute, "instructions")
    with pytest.raises(FrozenInstanceError):
        execute.user_content = "changed"


def test_stored_plan_is_an_immutable_snapshot():
    stored = StoredPlan("plan-1", "run-1", "Inspect then edit", PlanStatus.READY)

    assert stored.status is PlanStatus.READY
    with pytest.raises(FrozenInstanceError):
        stored.content = "changed"


@pytest.mark.asyncio
async def test_command_parser_selects_execute_and_read_only_plan_modes(tmp_path: Path):
    provider = ScriptedProvider([completed("answer"), completed("plan")])
    session = build_session(tmp_path, provider)

    execute = await session.start("hello")
    await consume(execute)
    plan = await session.start("/plan inspect the project")
    await consume(plan)

    assert execute.mode is RunMode.EXECUTE
    assert plan.mode is RunMode.PLAN
    assert [
        definition.name for definition in provider.calls[0][0].prompt.tools
    ] == [
        "read",
        "write",
    ]
    assert [
        definition.name for definition in provider.calls[1][0].prompt.tools
    ] == ["read"]
    assert (
        provider.calls[0][0].prompt.system_supplement
        != provider.calls[1][0].prompt.system_supplement
    )
    assert session.history == (
        UserMessage("hello"),
        AssistantMessage("answer", {"text": "answer"}),
        UserMessage("inspect the project"),
        AssistantMessage("plan", {"text": "plan"}),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_input", "code"),
    [
        ("/plan", "empty_plan_task"),
        ("/plan   ", "empty_plan_task"),
        ("/do", "no_plan"),
        ("/do extra", "do_takes_no_arguments"),
    ],
)
async def test_command_parser_invalid_requests_do_not_call_provider_or_change_history(
    tmp_path: Path, user_input: str, code: str
):
    provider = ScriptedProvider()
    session = build_session(tmp_path, provider)

    events = await consume(await session.start(user_input))

    assert [type(event) for event in events] == [RunStarted, RunStopped]
    assert events[-1].reason is StopReason.INVALID_REQUEST
    assert events[-1].code == code
    assert provider.calls == []
    assert session.history == ()


@pytest.mark.asyncio
async def test_invalid_request_short_circuits_prompt_dependencies(
    monkeypatch, tmp_path: Path
):
    provider = ScriptedProvider()

    class UnusedPromptBuilder:
        def prepare_run(self, **kwargs):
            raise AssertionError("prompt builder must not run")

    def unused_environment():
        raise AssertionError("environment factory must not run")

    session = build_session(
        tmp_path,
        provider,
        prompt_builder=UnusedPromptBuilder(),
        environment_factory=unused_environment,
    )
    monkeypatch.setattr(
        session._registry,
        "definitions",
        lambda _scope: (_ for _ in ()).throw(
            AssertionError("tool definitions must not be queried")
        ),
    )

    events = await consume(await session.start("/plan"))

    assert events[-1].reason is StopReason.INVALID_REQUEST
    assert provider.calls == []
    assert session.history == ()


@pytest.mark.asyncio
async def test_prompt_failure_does_not_commit_history_or_activate_run(tmp_path: Path):
    provider = ScriptedProvider()
    environment_calls = 0
    environment = EnvironmentSnapshot(
        tmp_path,
        "TestOS",
        "/bin/test-shell",
        date(2026, 7, 21),
        "UTC",
    )

    def capture_once():
        nonlocal environment_calls
        environment_calls += 1
        return environment

    session = build_session(
        tmp_path,
        provider,
        environment_factory=capture_once,
        prompt_options=PromptOptions(
            custom_instructions="<system-reminder secret-marker>"
        ),
    )

    with pytest.raises(ValueError) as error:
        await session.start("task")

    assert environment_calls == 1
    assert "secret-marker" not in str(error.value)
    assert session.history == ()
    assert session._active_run is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_environment_factory_failure_precedes_history_and_provider(tmp_path: Path):
    provider = ScriptedProvider()

    def failed_environment():
        raise RuntimeError("environment unavailable")

    session = build_session(
        tmp_path,
        provider,
        environment_factory=failed_environment,
    )

    with pytest.raises(RuntimeError, match="environment unavailable"):
        await session.start("task")

    assert session.history == ()
    assert session._active_run is None
    assert provider.calls == []


@pytest.mark.asyncio
async def test_prompt_snapshot_captures_environment_mode_and_tool_scope_once(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        [
            completed("answer"),
            completed("saved plan"),
            completed("done"),
        ]
    )
    environment = EnvironmentSnapshot(
        tmp_path.resolve(),
        "TestOS",
        "/bin/test-shell",
        date(2026, 7, 21),
        "UTC",
    )
    environment_calls = 0

    def environment_factory():
        nonlocal environment_calls
        environment_calls += 1
        return environment

    class RecordingPromptBuilder:
        def __init__(self):
            self.calls = []
            self.delegate = PromptBuilder()

        def prepare_run(self, **kwargs):
            self.calls.append(kwargs)
            return self.delegate.prepare_run(**kwargs)

    builder = RecordingPromptBuilder()
    options = PromptOptions(custom_instructions="caller supplied")
    session = build_session(
        tmp_path,
        provider,
        prompt_builder=builder,
        environment_factory=environment_factory,
        prompt_options=options,
    )

    await consume(await session.start("hello"))
    await consume(await session.start("/plan inspect"))
    await consume(await session.start("/do"))

    assert environment_calls == 3
    assert [call["mode"] for call in builder.calls] == [
        "execute",
        "plan",
        "do",
    ]
    assert all(call["environment"] is environment for call in builder.calls)
    assert all(call["options"] is options for call in builder.calls)
    assert [definition.name for definition in builder.calls[0]["tools"]] == [
        "read",
        "write",
    ]
    assert [definition.name for definition in builder.calls[1]["tools"]] == [
        "read"
    ]
    assert [definition.name for definition in builder.calls[2]["tools"]] == [
        "read",
        "write",
    ]
    assert all(
        request.prompt.system_supplement.count("caller supplied") == 1
        for request, _cancellation in provider.calls
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("user_input", ["/PLAN task", "/DO", " /plan task"])
async def test_command_parser_only_recognizes_exact_lowercase_prefix(
    tmp_path: Path, user_input: str
):
    provider = ScriptedProvider([completed("answer")])
    session = build_session(tmp_path, provider)

    run = await session.start(user_input)
    await consume(run)

    assert run.mode is RunMode.EXECUTE
    assert session.history[0] == UserMessage(user_input)


@pytest.mark.asyncio
async def test_single_run_rejects_overlap_then_preserves_history(tmp_path: Path):
    provider = BlockingProvider()
    session = build_session(tmp_path, provider)
    first = await session.start("first")
    await provider.entered.wait()

    with pytest.raises(MewCodeError, match="already running"):
        await session.start("second")

    await first.cancel()
    assert session.history == (UserMessage("first"),)


@pytest.mark.asyncio
async def test_immediate_cancel_emits_terminal_and_releases_session(
    tmp_path: Path,
):
    provider = ScriptedProvider([completed("follow-up complete")])
    session = build_session(tmp_path, provider)
    run = await session.start("cancel immediately")

    await run.cancel()
    async with asyncio.timeout(0.1):
        events = await consume(run)

    assert isinstance(events[0], RunStarted)
    assert isinstance(events[-1], RunStopped)
    assert events[-1].reason is StopReason.CANCELLED
    assert provider.calls == []

    follow_up = await consume(await session.start("next"))
    assert follow_up[-1].reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_consumer_close_break_cancels_run_cleans_up_and_allows_follow_up(
    tmp_path: Path,
):
    provider = CancellableThenCompletingProvider()
    session = build_session(tmp_path, provider)
    run = await session.start("first")

    async for event in run:
        assert isinstance(event, RunStarted)
        await provider.entered.wait()
        break

    async with asyncio.timeout(0.1):
        await provider.cancelled.wait()
    await run.wait_closed()

    follow_up = await consume(await session.start("second"))
    assert follow_up[-1].reason is StopReason.COMPLETED
    assert session.history == (
        UserMessage("first"),
        UserMessage("second"),
        AssistantMessage("follow-up complete", {"text": "follow-up complete"}),
    )


@pytest.mark.asyncio
async def test_consumer_close_before_iteration_cleans_up_and_allows_follow_up(
    tmp_path: Path,
):
    provider = ScriptedProvider([completed("follow-up complete")])
    session = build_session(tmp_path, provider)
    run = await session.start("first")
    iterator = aiter(run)

    await iterator.aclose()
    await run.wait_closed()

    assert provider.calls == []
    assert session.history == (UserMessage("first"),)
    follow_up = await consume(await session.start("second"))
    assert follow_up[-1].reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_plan_replace_and_preserve_only_after_success_uses_read_only_tools(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        [
            completed("plan A"),
            [ProviderError("planning failed")],
            completed("plan B"),
        ]
    )
    session = build_session(tmp_path, provider)

    first = await session.start("/plan first task")
    await consume(first)
    plan_a = session.current_plan
    failed = await session.start("/plan failed replacement")
    failed_events = await consume(failed)

    assert plan_a is not None
    assert plan_a.content == "plan A"
    assert plan_a.source_run_id == first.run_id
    assert plan_a.status is PlanStatus.READY
    assert failed_events[-1].reason is StopReason.PROVIDER_ERROR
    assert session.current_plan == plan_a

    replacement = await session.start("/plan replacement")
    await consume(replacement)

    assert session.current_plan is not None
    assert session.current_plan.content == "plan B"
    assert session.current_plan.source_run_id == replacement.run_id
    assert session.current_plan != plan_a
    assert all(
        [definition.name for definition in call[0].prompt.tools] == ["read"]
        for call in provider.calls
    )


@pytest.mark.asyncio
async def test_plan_read_only_treats_named_mutating_tool_as_unknown(
    tmp_path: Path,
):
    provider = ScriptedProvider(
        [
            [
                ProviderToolCallDelta(
                    0,
                    call_id_delta="call-write",
                    name_delta="write",
                    arguments_delta="{}",
                ),
                ProviderResponseCompleted({}),
            ],
            completed("safe plan"),
        ]
    )
    registry = ToolRegistry()
    read = FakeTool("read", ToolAccess.READ_ONLY)
    write = FakeTool("write", ToolAccess.MUTATING)
    registry.register(read)
    registry.register(write)
    session = AgentSession(
        provider,
        registry,
        ToolExecutor(registry, Workspace(tmp_path)),
    )

    events = await consume(await session.start("/plan inspect safely"))

    assert events[-1].reason is StopReason.COMPLETED
    assert write.executions == 0
    assert all(
        [definition.name for definition in call[0].prompt.tools] == ["read"]
        for call in provider.calls
    )
    feedback = next(
        message
        for message in session.history
        if isinstance(message, ToolResultsMessage)
    )
    assert feedback.results[0].result.error is not None
    assert feedback.results[0].result.error.code == "unknown_tool"
    assert session.current_plan is not None
    assert session.current_plan.content == "safe plan"


@pytest.mark.asyncio
async def test_plan_preserve_after_unknown_tool_and_iteration_limits(
    tmp_path: Path,
):
    unknown_provider = ScriptedProvider(
        [
            completed("plan A"),
            *(tool_completed(f"unknown-{index}", "missing") for index in range(3)),
        ]
    )
    unknown_session = build_session(tmp_path, unknown_provider)
    await consume(await unknown_session.start("/plan original"))
    plan_a = unknown_session.current_plan

    unknown_events = await consume(
        await unknown_session.start("/plan unsafe replacement")
    )

    assert unknown_events[-1].reason is StopReason.UNKNOWN_TOOL_LIMIT
    assert unknown_session.current_plan == plan_a

    iteration_provider = ScriptedProvider(
        [
            completed("plan B"),
            *(tool_completed(f"known-{index}", "read") for index in range(10)),
        ]
    )
    iteration_session = build_session(tmp_path, iteration_provider)
    await consume(await iteration_session.start("/plan original"))
    plan_b = iteration_session.current_plan

    iteration_events = await consume(
        await iteration_session.start("/plan endless replacement")
    )

    assert iteration_events[-1].reason is StopReason.ITERATION_LIMIT
    assert iteration_session.current_plan == plan_b


@pytest.mark.asyncio
async def test_plan_preserve_after_cancellation(tmp_path: Path):
    provider = CompletingThenBlockingProvider("plan A")
    session = build_session(tmp_path, provider)
    await consume(await session.start("/plan original"))
    plan_a = session.current_plan

    replacement = await session.start("/plan replacement")
    await provider.entered.wait()
    await replacement.cancel()
    events = await consume(replacement)

    assert events[-1].reason is StopReason.CANCELLED
    assert session.current_plan == plan_a


@pytest.mark.asyncio
async def test_do_lifecycle_executes_ready_plan_once_and_marks_it_completed(
    tmp_path: Path,
):
    provider = ScriptedProvider([completed("saved plan"), completed("done")])
    session = build_session(tmp_path, provider)
    await consume(await session.start("/plan make a plan"))
    ready = session.current_plan

    execution = await session.start("/do")
    await consume(execution)

    assert ready is not None
    assert execution.mode is RunMode.DO
    assert provider.calls[1][0].history[-1] == UserMessage("saved plan")
    assert [definition.name for definition in provider.calls[1][0].prompt.tools] == [
        "read",
        "write",
    ]
    assert session.current_plan is not None
    assert session.current_plan.plan_id == ready.plan_id
    assert session.current_plan.status is PlanStatus.COMPLETED

    repeated = await consume(await session.start("/do"))
    assert repeated[-1].reason is StopReason.INVALID_REQUEST
    assert repeated[-1].code == "plan_completed"
    assert len(provider.calls) == 2


@pytest.mark.asyncio
async def test_do_lifecycle_preserves_ready_plan_after_error_for_retry(tmp_path: Path):
    provider = ScriptedProvider(
        [
            completed("saved plan"),
            [ProviderError("execution failed")],
            completed("retry done"),
        ]
    )
    session = build_session(tmp_path, provider)
    await consume(await session.start("/plan make a plan"))
    ready = session.current_plan

    failed = await consume(await session.start("/do"))
    assert failed[-1].reason is StopReason.PROVIDER_ERROR
    assert session.current_plan == ready

    retried = await consume(await session.start("/do"))
    assert retried[-1].reason is StopReason.COMPLETED
    assert session.current_plan is not None
    assert session.current_plan.status is PlanStatus.COMPLETED


@pytest.mark.asyncio
async def test_do_lifecycle_preserves_ready_plan_after_limits(tmp_path: Path):
    unknown_provider = ScriptedProvider(
        [
            completed("saved unknown plan"),
            *(tool_completed(f"unknown-{index}", "missing") for index in range(3)),
            completed("unknown retry complete"),
        ]
    )
    unknown_session = build_session(tmp_path, unknown_provider)
    await consume(await unknown_session.start("/plan prepare"))
    unknown_ready = unknown_session.current_plan

    unknown_events = await consume(await unknown_session.start("/do"))

    assert unknown_events[-1].reason is StopReason.UNKNOWN_TOOL_LIMIT
    assert unknown_session.current_plan == unknown_ready
    unknown_retry = await consume(await unknown_session.start("/do"))
    assert unknown_retry[-1].reason is StopReason.COMPLETED
    assert unknown_session.current_plan is not None
    assert unknown_session.current_plan.status is PlanStatus.COMPLETED

    iteration_provider = ScriptedProvider(
        [
            completed("saved iteration plan"),
            *(tool_completed(f"known-{index}", "read") for index in range(10)),
            completed("iteration retry complete"),
        ]
    )
    iteration_session = build_session(tmp_path, iteration_provider)
    await consume(await iteration_session.start("/plan prepare"))
    iteration_ready = iteration_session.current_plan

    iteration_events = await consume(await iteration_session.start("/do"))

    assert iteration_events[-1].reason is StopReason.ITERATION_LIMIT
    assert iteration_session.current_plan == iteration_ready
    iteration_retry = await consume(await iteration_session.start("/do"))
    assert iteration_retry[-1].reason is StopReason.COMPLETED
    assert iteration_session.current_plan is not None
    assert iteration_session.current_plan.status is PlanStatus.COMPLETED


@pytest.mark.asyncio
async def test_do_lifecycle_preserves_ready_plan_after_cancellation(
    tmp_path: Path,
):
    provider = CompletingThenBlockingProvider("saved plan", "cancel retry complete")
    session = build_session(tmp_path, provider)
    await consume(await session.start("/plan prepare"))
    ready = session.current_plan

    execution = await session.start("/do")
    await provider.entered.wait()
    await execution.cancel()
    events = await consume(execution)

    assert events[-1].reason is StopReason.CANCELLED
    assert session.current_plan == ready
    retry = await consume(await session.start("/do"))
    assert retry[-1].reason is StopReason.COMPLETED
    assert session.current_plan is not None
    assert session.current_plan.status is PlanStatus.COMPLETED


@pytest.mark.asyncio
async def test_close_is_idempotent_cancels_active_run_and_closes_provider_once(
    tmp_path: Path,
):
    provider = BlockingProvider()
    session = build_session(tmp_path, provider)
    run = await session.start("task")
    await provider.entered.wait()

    await asyncio.gather(session.close(), session.close())
    events = await consume(run)

    assert events[-1].reason is StopReason.CANCELLED
    assert provider.close_calls == 1
    with pytest.raises(MewCodeError, match="closed"):
        await session.start("later")


def test_public_api_only_exports_session_run_plan_and_events():
    expected = {
        "AgentEvent",
        "AgentRun",
        "AgentSession",
        "ConfirmationRequested",
        "ConfirmationResolved",
        "EventContext",
        "PlanStatus",
        "ProgressChanged",
        "RunMode",
        "RunPhase",
        "RunStarted",
        "RunStopped",
        "StopReason",
        "StoredPlan",
        "TextDeltaEvent",
        "ToolFinished",
        "ToolStarted",
        "UsageReported",
    }

    assert set(agent_api.__all__) == expected
    assert all(hasattr(agent_api, name) for name in expected)
    assert not hasattr(agent_api, "ResponseCollector")
    assert not hasattr(agent_api, "ToolScheduler")
    assert not hasattr(agent_api, "EventChannel")


def test_import_direction_keeps_lower_layers_independent_from_agent_and_ui():
    root = Path(__file__).parents[1]
    sources = [root / "mewcode/messages.py", root / "mewcode/cancellation.py"]
    sources.extend((root / "mewcode/providers").glob("*.py"))
    sources.extend((root / "mewcode/tools").glob("*.py"))
    forbidden = ("mewcode.agent", "mewcode.tui", "mewcode.cli")

    imports = []
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imports.append(node.module)

    assert not [name for name in imports if name.startswith(forbidden)]
