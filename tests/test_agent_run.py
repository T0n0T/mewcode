import asyncio

import pytest

from mewcode.agent.events import (
    ProgressChanged,
    RunStarted,
    RunStopped,
    TextDeltaEvent,
)
from mewcode.agent.run import AgentRun
from mewcode.agent.types import AgentRequest, RunMode, RunPhase, StopReason


class BlockingCollector:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def collect(
        self,
        history,
        tools,
        *,
        run_id,
        iteration,
        instructions,
        cancellation,
        on_text,
        on_stream_started,
    ):
        await on_stream_started()
        await on_text("partial")
        self.started.set()
        await cancellation.wait_cancelled()
        cancellation.raise_if_cancelled()


class UnusedScheduler:
    async def execute(self, *args, **kwargs):
        raise AssertionError("scheduler must not run in the lifecycle slice")


class IdleCollector:
    async def collect(self, *args, **kwargs):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_lifecycle_reports_start_waiting_and_streaming_with_stable_identity():
    collector = BlockingCollector()
    committed = []
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        collector,
        UnusedScheduler(),
        committed.extend,
        id_factory=lambda: "run-1",
    )
    events = aiter(run)

    observed = [await anext(events) for _ in range(4)]
    await collector.started.wait()
    await run.cancel()
    observed.append(await anext(events))

    assert run.run_id == "run-1"
    assert run.mode is RunMode.EXECUTE
    assert [type(event) for event in observed] == [
        RunStarted,
        ProgressChanged,
        ProgressChanged,
        TextDeltaEvent,
        RunStopped,
    ]
    assert [
        event.phase for event in observed if isinstance(event, ProgressChanged)
    ] == [RunPhase.WAITING_MODEL, RunPhase.STREAMING_MODEL]
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED
    assert [event.context.sequence for event in observed] == [1, 2, 3, 4, 5]
    assert {event.context.run_id for event in observed} == {"run-1"}
    assert committed == []


@pytest.mark.asyncio
async def test_public_control_immediate_cancel_is_idempotent_and_closes_run():
    run = AgentRun(
        AgentRequest(RunMode.EXECUTE, "task", "execute", "all"),
        (),
        (),
        IdleCollector(),
        UnusedScheduler(),
        lambda _messages: None,
        id_factory=lambda: "run-1",
    )
    events = aiter(run)

    await asyncio.gather(run.cancel(), run.cancel())
    await run.wait_closed()
    async with asyncio.timeout(0.1):
        observed = [event async for event in events]

    assert isinstance(observed[0], RunStarted)
    assert isinstance(observed[-1], RunStopped)
    assert observed[-1].reason is StopReason.CANCELLED
    assert run.resolve_confirmation("missing", True) is False
