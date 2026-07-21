from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from mewcode.tools.base import ToolScope


class RunMode(str, Enum):
    EXECUTE = "execute"
    PLAN = "plan"
    DO = "do"


class RunPhase(str, Enum):
    WAITING_MODEL = "waiting_model"
    STREAMING_MODEL = "streaming_model"
    EXECUTING_TOOLS = "executing_tools"
    WAITING_CONFIRMATION = "waiting_confirmation"
    FEEDING_BACK = "feeding_back"
    STOPPING = "stopping"


class StopReason(str, Enum):
    COMPLETED = "completed"
    ITERATION_LIMIT = "iteration_limit"
    CANCELLED = "cancelled"
    UNKNOWN_TOOL_LIMIT = "unknown_tool_limit"
    PROVIDER_ERROR = "provider_error"
    INVALID_REQUEST = "invalid_request"
    INTERNAL_ERROR = "internal_error"


class PlanStatus(str, Enum):
    READY = "ready"
    COMPLETED = "completed"


@dataclass(frozen=True)
class AgentRequest:
    mode: RunMode
    user_content: str
    tool_scope: ToolScope
    source_plan_id: str | None = None


@dataclass(frozen=True)
class StoredPlan:
    plan_id: str
    source_run_id: str
    content: str
    status: PlanStatus
