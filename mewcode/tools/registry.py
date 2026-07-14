from __future__ import annotations

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mewcode.tools.base import (
    Tool,
    ToolAccess,
    ToolDefinition,
    ToolDescriptor,
    ToolExecutionPolicy,
    ToolScope,
)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}

    def register(self, tool: Tool) -> None:
        definition = tool.definition
        if not definition.name.strip():
            raise ValueError("Tool name must not be empty.")
        if definition.name in self._tools:
            raise ValueError(f"Tool '{definition.name}' is already registered.")
        schema = definition.input_schema
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ValueError(f"Invalid schema for tool '{definition.name}': {exc.message}") from exc
        if schema.get("type") != "object":
            raise ValueError(f"Tool '{definition.name}' schema must have an object root.")
        if schema.get("additionalProperties") is not False:
            raise ValueError(
                f"Tool '{definition.name}' schema must set additionalProperties to false."
            )
        access = getattr(tool, "access", ToolAccess.MUTATING)
        execution_policy = getattr(
            tool,
            "execution_policy",
            ToolExecutionPolicy.SERIAL,
        )
        requires_confirmation = bool(getattr(tool, "requires_confirmation", False))
        if execution_policy is ToolExecutionPolicy.PARALLEL_SAFE and (
            access is ToolAccess.MUTATING or requires_confirmation
        ):
            raise ValueError(
                f"Tool '{definition.name}' must use serial execution when it mutates "
                "state or requires confirmation."
            )
        self._tools[definition.name] = tool
        self._descriptors[definition.name] = ToolDescriptor(
            definition,
            access,
            execution_policy,
            requires_confirmation,
        )

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def descriptor(self, name: str) -> ToolDescriptor | None:
        return self._descriptors.get(name)

    def definitions(self, scope: ToolScope = "all") -> tuple[ToolDefinition, ...]:
        if scope == "all":
            return tuple(tool.definition for tool in self._tools.values())
        return tuple(
            descriptor.definition
            for descriptor in self._descriptors.values()
            if descriptor.access is ToolAccess.READ_ONLY
        )
