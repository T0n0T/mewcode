from __future__ import annotations

from collections.abc import Mapping, Sequence


_UNSUPPORTED_MARKERS = (
    "not supported",
    "unsupported",
    "unknown parameter",
    "unknown_parameter",
    "unknown field",
    "unknown_field",
    "unrecognized parameter",
    "unrecognized_parameter",
    "unrecognized field",
    "unrecognized_field",
)


def is_unsupported_cache_hint(
    status_code: int,
    error_body: object,
    field_name: str,
) -> bool:
    """Return whether a structured 400/422 explicitly rejects a cache hint."""

    if status_code not in {400, 422}:
        return False
    if not isinstance(error_body, (Mapping, list, tuple)):
        return False
    normalized_field = field_name.strip().casefold()
    if not normalized_field:
        return False
    structured_text = " ".join(_structured_text(error_body)).casefold()
    return normalized_field in structured_text and any(
        marker in structured_text for marker in _UNSUPPORTED_MARKERS
    )


def _structured_text(value: object) -> list[str]:
    if isinstance(value, Mapping):
        text = [str(key) for key in value]
        for item in value.values():
            text.extend(_structured_text(item))
        return text
    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        text: list[str] = []
        for item in value:
            text.extend(_structured_text(item))
        return text
    if isinstance(value, str):
        return [value]
    return []
