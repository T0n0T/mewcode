from mewcode.agent.events import EventContext, UsageReported
from mewcode.providers.base import TokenUsage
from mewcode.tui.presentation import usage_text


def event(current: TokenUsage, cumulative: TokenUsage) -> UsageReported:
    return UsageReported(EventContext("run-1", 1, 1), current, cumulative)


def test_usage_text_preserves_three_dimension_format_when_cache_is_missing():
    assert usage_text(
        event(
            TokenUsage(1, 2, 3),
            TokenUsage(4, 5, None),
        )
    ) == (
        "tokens in:1 out:2 total:3 | cumulative in:4 out:5 total:n/a"
    )


def test_usage_text_displays_zero_and_positive_cache_values():
    assert usage_text(
        event(
            TokenUsage(10, 2, 12, 0, 8),
            TokenUsage(20, 4, 24, 7, 0),
        )
    ) == (
        "tokens in:10 out:2 total:12 cache-read:0 cache-write:8 "
        "| cumulative in:20 out:4 total:24 cache-read:7 cache-write:0"
    )


def test_usage_text_checks_current_and_cumulative_cache_fields_independently():
    assert usage_text(
        event(
            TokenUsage(None, 2, None, None, 3),
            TokenUsage(None, 5, None, 9, None),
        )
    ) == (
        "tokens in:n/a out:2 total:n/a cache-write:3 "
        "| cumulative in:n/a out:5 total:n/a cache-read:9"
    )
