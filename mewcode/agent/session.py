from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from uuid import uuid4

from mewcode.agent.collector import ResponseCollector
from mewcode.agent.run import AgentRun
from mewcode.agent.scheduler import ToolScheduler
from mewcode.agent.types import (
    AgentRequest,
    PlanStatus,
    RunMode,
    StopReason,
    StoredPlan,
)
from mewcode.errors import MewCodeError
from mewcode.messages import ConversationMessage, UserMessage
from mewcode.providers.base import LLMProvider
from mewcode.tools.base import ToolScope
from mewcode.tools.executor import ToolExecutor
from mewcode.tools.registry import ToolRegistry

EXECUTE_INSTRUCTIONS = (
    "Execute the user's request with the available tools and adapt to observations."
)
PLAN_INSTRUCTIONS = (
    "Analyze the request with read-only tools and return a concrete implementation plan."
)
DO_INSTRUCTIONS = (
    "Execute the saved plan with the available tools and adapt to observations."
)


@dataclass(frozen=True)
class _InvalidRequest:
    mode: RunMode
    code: str
    message: str


def _new_id() -> str:
    return str(uuid4())


class AgentSession:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        executor: ToolExecutor,
        *,
        max_iterations: int = 10,
        unknown_tool_limit: int = 3,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._executor = executor
        self._max_iterations = max_iterations
        self._unknown_tool_limit = unknown_tool_limit
        self._id_factory = id_factory or _new_id
        self._collector = ResponseCollector(provider)
        self._history: list[ConversationMessage] = []
        self._current_plan: StoredPlan | None = None
        self._active_run: AgentRun | None = None
        self._closed = False
        self._provider_closed = False

    @property
    def history(self) -> tuple[ConversationMessage, ...]:
        return tuple(self._history)

    @property
    def current_plan(self) -> StoredPlan | None:
        return self._current_plan

    async def start(self, user_input: str) -> AgentRun:
        if self._closed:
            raise MewCodeError("The Agent session is closed.")
        if self._active_run is not None:
            raise MewCodeError("An Agent run is already running.")

        parsed = self._parse_request(user_input)
        if isinstance(parsed, _InvalidRequest):
            request = AgentRequest(
                parsed.mode,
                "",
                "",
                "all",
                self._current_plan.plan_id if self._current_plan is not None else None,
            )
            run = self._create_run(
                request,
                (),
                invalid=(parsed.code, parsed.message),
            )
        else:
            request = parsed
            self._commit((UserMessage(request.user_content),))
            tools = self._registry.definitions(request.tool_scope)
            run = self._create_run(request, tools)
        self._active_run = run
        return run

    async def close(self) -> None:
        if self._closed and self._provider_closed:
            return
        self._closed = True
        active = self._active_run
        if active is not None:
            await active.cancel()
            await active.wait_closed()
        if not self._provider_closed:
            self._provider_closed = True
            await self._provider.aclose()

    def _create_run(
        self,
        request: AgentRequest,
        tools: Sequence,
        *,
        invalid: tuple[str, str] | None = None,
    ) -> AgentRun:
        scheduler = ToolScheduler(
            self._registry,
            self._executor,
            id_factory=self._id_factory,
            allowed_tool_names=(definition.name for definition in tools),
        )
        return AgentRun(
            request,
            self._history,
            tools,
            self._collector,
            scheduler,
            self._commit,
            max_iterations=self._max_iterations,
            unknown_tool_limit=self._unknown_tool_limit,
            id_factory=self._id_factory,
            tool_presenter=self._executor.presentation,
            invalid=invalid,
            on_closed=lambda run_id, mode, reason, final_text: self._run_closed(
                request, run_id, mode, reason, final_text
            ),
        )

    def _parse_request(self, user_input: str) -> AgentRequest | _InvalidRequest:
        if _is_command(user_input, "/plan"):
            task = user_input[len("/plan") :].strip()
            if not task:
                return _InvalidRequest(
                    RunMode.PLAN,
                    "empty_plan_task",
                    "Usage: /plan <task>.",
                )
            return AgentRequest(
                RunMode.PLAN,
                task,
                PLAN_INSTRUCTIONS,
                "read_only",
            )

        if _is_command(user_input, "/do"):
            if user_input != "/do":
                return _InvalidRequest(
                    RunMode.DO,
                    "do_takes_no_arguments",
                    "Usage: /do.",
                )
            if self._current_plan is None:
                return _InvalidRequest(
                    RunMode.DO,
                    "no_plan",
                    "There is no saved plan to execute.",
                )
            if self._current_plan.status is PlanStatus.COMPLETED:
                return _InvalidRequest(
                    RunMode.DO,
                    "plan_completed",
                    "The saved plan has already completed.",
                )
            return AgentRequest(
                RunMode.DO,
                self._current_plan.content,
                DO_INSTRUCTIONS,
                "all",
                self._current_plan.plan_id,
            )

        return AgentRequest(
            RunMode.EXECUTE,
            user_input,
            EXECUTE_INSTRUCTIONS,
            "all",
        )

    def _commit(self, messages: Sequence[ConversationMessage]) -> None:
        self._history.extend(messages)

    def _run_closed(
        self,
        request: AgentRequest,
        run_id: str,
        mode: RunMode,
        reason: StopReason,
        final_text: str | None,
    ) -> None:
        if self._active_run is not None and self._active_run.run_id == run_id:
            self._active_run = None
        if reason is not StopReason.COMPLETED or final_text is None:
            return
        if mode is RunMode.PLAN:
            self._current_plan = StoredPlan(
                self._id_factory(),
                run_id,
                final_text,
                PlanStatus.READY,
            )
        elif (
            mode is RunMode.DO
            and self._current_plan is not None
            and self._current_plan.plan_id == request.source_plan_id
        ):
            self._current_plan = replace(
                self._current_plan,
                status=PlanStatus.COMPLETED,
            )


def _is_command(user_input: str, command: str) -> bool:
    return user_input == command or (
        user_input.startswith(command)
        and len(user_input) > len(command)
        and user_input[len(command)].isspace()
    )
