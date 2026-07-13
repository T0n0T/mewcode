from __future__ import annotations

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from mewcode.tools.base import Tool, ToolDefinition


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

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
        self._tools[definition.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(tool.definition for tool in self._tools.values())
