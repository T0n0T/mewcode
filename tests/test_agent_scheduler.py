import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from mewcode.agent.collector import RawToolCall
from mewcode.agent.scheduler import ToolScheduler
from mewcode.cancellation import CancellationToken
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


class FakeTool:
    manages_own_timeout = False

    def __init__(self, name, policy, *, confirm=False, behavior=None):
        self.definition = ToolDefinition(
            name,
            name,
            {"type": "object", "properties": {}, "additionalProperties": False},
        )
        self.access = ToolAccess.MUTATING if confirm else ToolAccess.READ_ONLY
        self.execution_policy = policy
        self.requires_confirmation = confirm
        self.behavior = behavior

    async def prepare(self, arguments, context):
        return PreparedToolAction(
            dict(arguments),
            ConfirmationPreview("write", self.definition.name, "safe")
            if self.requires_confirmation
            else None,
        )

    async def execute(self, action, context):
        if self.behavior is not None:
            return await self.behavior(self.definition.name)
        return ToolResult(status="success", data={"name": self.definition.name})


class RecordingEvents:
    def __init__(self, approvals: bool | Sequence[bool] = True):
        self.records = []
        self.approvals = approvals
        self._approval_iterator = (
            iter(approvals) if isinstance(approvals, (list, tuple)) else None
        )

    async def started(self, batch, call):
        self.records.append(("started", call.name))

    async def confirm(self, call, preview):
        self.records.append(("confirm", call.name))
        if self._approval_iterator is not None:
            return next(self._approval_iterator)
        assert isinstance(self.approvals, bool)
        return self.approvals

    async def finished(self, batch, call, result):
        self.records.append(("finished", call.name))


def scheduler(tmp_path: Path, tools):
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolScheduler(registry, ToolExecutor(registry, Workspace(tmp_path)))


def raw(slot, name, arguments="{}", call_id=None):
    return RawToolCall(slot, call_id or f"call-{slot}", name, arguments)


def test_parse_calls_isolates_invalid_unknown_and_known_policy(tmp_path: Path):
    read = FakeTool("read", ToolExecutionPolicy.PARALLEL_SAFE)
    parsed = scheduler(tmp_path, [read]).parse_calls(
        [raw(0, "read"), raw(1, "read", "["), raw(2, "read", "[]"), raw(3, "missing")]
    )

    assert parsed[0].arguments == {}
    assert parsed[0].execution_policy is ToolExecutionPolicy.PARALLEL_SAFE
    errors = [parsed[index].preflight_error for index in (1, 2)]
    assert all(error is not None and error.error is not None for error in errors)
    assert [
        error.error.code
        for error in errors
        if error is not None and error.error is not None
    ] == [
        "invalid_arguments",
        "invalid_arguments",
    ]
    assert parsed[3].execution_policy is ToolExecutionPolicy.SERIAL


@pytest.mark.asyncio
async def test_mixed_valid_invalid_and_unknown_calls_keep_independent_results(
    tmp_path: Path,
):
    service = scheduler(
        tmp_path,
        [FakeTool("read", ToolExecutionPolicy.PARALLEL_SAFE)],
    )
    outcome = await service.execute(
        [
            raw(0, "read", call_id="valid"),
            raw(1, "read", "[", call_id="invalid"),
            raw(2, "missing", call_id="unknown"),
        ],
        iteration=1,
        cancellation=CancellationToken(),
        events=RecordingEvents(),
    )

    assert [feedback.call_id for feedback in outcome.feedback] == [
        "valid",
        "invalid",
        "unknown",
    ]
    assert [
        feedback.result.error.code if feedback.result.error is not None else None
        for feedback in outcome.feedback
    ] == [None, "invalid_arguments", "unknown_tool"]
    assert outcome.all_unknown is False


def test_build_batches_preserves_parallel_groups_and_serial_barriers(tmp_path: Path):
    tools = [
        FakeTool("a", ToolExecutionPolicy.PARALLEL_SAFE),
        FakeTool("b", ToolExecutionPolicy.PARALLEL_SAFE),
        FakeTool("c", ToolExecutionPolicy.SERIAL),
        FakeTool("d", ToolExecutionPolicy.PARALLEL_SAFE),
    ]
    service = scheduler(tmp_path, tools)
    batches = service.build_batches(
        service.parse_calls([raw(i, name) for i, name in enumerate("abcd")])
    )

    assert [[call.name for call in batch.calls] for batch in batches] == [
        ["a", "b"],
        ["c"],
        ["d"],
    ]
    assert [batch.execution_policy for batch in batches] == [
        ToolExecutionPolicy.PARALLEL_SAFE,
        ToolExecutionPolicy.SERIAL,
        ToolExecutionPolicy.PARALLEL_SAFE,
    ]


@pytest.mark.asyncio
async def test_parallel_completion_is_live_but_feedback_keeps_original_order(
    tmp_path: Path,
):
    both_started = asyncio.Event()
    started = set()
    release_first = asyncio.Event()

    async def behavior(name):
        started.add(name)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()
        if name == "first":
            await release_first.wait()
        else:
            release_first.set()
        return ToolResult(status="success", data={"name": name})

    service = scheduler(
        tmp_path,
        [
            FakeTool("first", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
            FakeTool("second", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
        ],
    )
    events = RecordingEvents()
    outcome = await service.execute(
        [raw(0, "first"), raw(1, "second")],
        iteration=1,
        cancellation=CancellationToken(),
        events=events,
    )

    assert events.records[:2] == [
        ("started", "first"),
        ("started", "second"),
    ]
    assert [record for record in events.records if record[0] == "finished"] == [
        ("finished", "second"),
        ("finished", "first"),
    ]
    assert [feedback.name for feedback in outcome.feedback] == ["first", "second"]


@pytest.mark.asyncio
async def test_parallel_tool_exception_does_not_cancel_sibling(tmp_path: Path):
    completed = []

    async def behavior(name):
        if name == "broken":
            raise RuntimeError("boom")
        completed.append(name)
        return ToolResult(status="success")

    service = scheduler(
        tmp_path,
        [
            FakeTool("broken", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
            FakeTool("healthy", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
        ],
    )
    outcome = await service.execute(
        [raw(0, "broken"), raw(1, "healthy")],
        iteration=1,
        cancellation=CancellationToken(),
        events=RecordingEvents(),
    )

    assert completed == ["healthy"]
    assert [feedback.result.status for feedback in outcome.feedback] == [
        "error",
        "success",
    ]


@pytest.mark.asyncio
async def test_serial_barrier_and_confirmation_continue_after_rejection(tmp_path: Path):
    order = []

    async def behavior(name):
        order.append(name)
        return ToolResult(status="success")

    service = scheduler(
        tmp_path,
        [
            FakeTool("read", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
            FakeTool(
                "write", ToolExecutionPolicy.SERIAL, confirm=True, behavior=behavior
            ),
            FakeTool("after", ToolExecutionPolicy.PARALLEL_SAFE, behavior=behavior),
        ],
    )
    outcome = await service.execute(
        [raw(0, "read"), raw(1, "write"), raw(2, "after")],
        iteration=1,
        cancellation=CancellationToken(),
        events=RecordingEvents(approvals=False),
    )

    assert order == ["read", "after"]
    assert [feedback.result.status for feedback in outcome.feedback] == [
        "success",
        "rejected",
        "success",
    ]


@pytest.mark.asyncio
async def test_serial_tools_are_confirmed_individually(tmp_path: Path):
    executed = []

    async def behavior(name):
        executed.append(name)
        return ToolResult(status="success")

    service = scheduler(
        tmp_path,
        [
            FakeTool(
                "first", ToolExecutionPolicy.SERIAL, confirm=True, behavior=behavior
            ),
            FakeTool(
                "second", ToolExecutionPolicy.SERIAL, confirm=True, behavior=behavior
            ),
        ],
    )
    events = RecordingEvents(approvals=[True, False])
    outcome = await service.execute(
        [raw(0, "first"), raw(1, "second")],
        iteration=1,
        cancellation=CancellationToken(),
        events=events,
    )

    assert [record for record in events.records if record[0] == "confirm"] == [
        ("confirm", "first"),
        ("confirm", "second"),
    ]
    assert executed == ["first"]
    assert [feedback.result.status for feedback in outcome.feedback] == [
        "success",
        "rejected",
    ]


@pytest.mark.asyncio
async def test_all_unknown_only_when_every_result_is_unknown(tmp_path: Path):
    service = scheduler(tmp_path, [])
    unknown = await service.execute(
        [raw(0, "missing"), raw(1, "other")],
        iteration=1,
        cancellation=CancellationToken(),
        events=RecordingEvents(),
    )
    mixed = await service.execute(
        [raw(0, "missing"), raw(1, "other", "[")],
        iteration=1,
        cancellation=CancellationToken(),
        events=RecordingEvents(),
    )
    assert unknown.all_unknown is True
    assert mixed.all_unknown is False


@pytest.mark.asyncio
async def test_cancellation_aborts_parallel_batch_and_later_barrier(tmp_path: Path):
    started = asyncio.Event()
    later_calls = []

    async def block(_name):
        started.set()
        await asyncio.Event().wait()

    async def later(name):
        later_calls.append(name)
        return ToolResult(status="success")

    service = scheduler(
        tmp_path,
        [
            FakeTool("block", ToolExecutionPolicy.PARALLEL_SAFE, behavior=block),
            FakeTool("later", ToolExecutionPolicy.SERIAL, behavior=later),
        ],
    )
    cancellation = CancellationToken()
    task = asyncio.create_task(
        service.execute(
            [raw(0, "block"), raw(1, "later")],
            iteration=1,
            cancellation=cancellation,
            events=RecordingEvents(),
        )
    )
    await started.wait()
    cancellation.cancel()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert later_calls == []
