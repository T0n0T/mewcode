from __future__ import annotations

import os
import platform as platform_module
from datetime import datetime, timedelta
from pathlib import Path

from mewcode.prompting.types import EnvironmentSnapshot


def capture_environment(
    working_directory: Path,
    *,
    now: datetime | None = None,
    platform_name: str | None = None,
    shell: str | None = None,
) -> EnvironmentSnapshot:
    injected_now = now is not None
    current = now if now is not None else datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Environment time must include timezone information.")

    observed_platform = (
        platform_module.system() if platform_name is None else platform_name
    )
    normalized_platform = _value_or_unknown(observed_platform)
    normalized_shell = _resolve_shell(shell, normalized_platform)
    timezone = _resolve_timezone(current, injected=injected_now)

    return EnvironmentSnapshot(
        working_directory.expanduser().resolve(),
        normalized_platform,
        normalized_shell,
        current.date(),
        timezone,
    )


def _resolve_shell(explicit: str | None, platform_name: str) -> str:
    if explicit is not None:
        return _value_or_unknown(explicit)
    configured = os.environ.get("SHELL")
    if configured and configured.strip():
        return configured.strip()
    if platform_name.casefold().startswith("windows"):
        command = os.environ.get("COMSPEC")
        if command and command.strip():
            return command.strip()
    return "unknown"


def _resolve_timezone(current: datetime, *, injected: bool) -> str:
    if not injected:
        configured = os.environ.get("TZ")
        if configured and configured.strip():
            return configured.strip()

    zone_key = getattr(current.tzinfo, "key", None)
    if isinstance(zone_key, str) and zone_key.strip():
        return zone_key.strip()
    zone_name = current.tzname()
    if zone_name and zone_name.strip():
        return zone_name.strip()
    offset = current.utcoffset()
    if offset is not None:
        return _format_offset(offset)
    return "unknown"


def _format_offset(offset: timedelta) -> str:
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _value_or_unknown(value: str) -> str:
    normalized = value.strip()
    return normalized or "unknown"
