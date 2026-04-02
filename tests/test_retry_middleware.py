# tests/test_retry_middleware.py
"""Tests for RetryMiddleware: success on first try, success on nth retry,
exhaustion, backoff, async, and stack ordering."""
from __future__ import annotations

from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from langchain_middleware_stack.errors import RetryExhaustedError
from langchain_middleware_stack.middleware.retry import RetryMiddleware
from langchain_middleware_stack.protocol import BaseMiddleware
from langchain_middleware_stack.stack import MiddlewareStack


def test_slug_and_constraints() -> None:
    mw = RetryMiddleware()
    assert mw.slug == "retry"
    assert mw.after == ("logging",)
    assert mw.before == ()


def test_succeeds_on_first_attempt() -> None:
    handler = MagicMock(return_value="ok")
    mw = RetryMiddleware(max_retries=3)
    result = mw.wrap(handler)
    assert result == "ok"
    handler.assert_called_once()


def test_retries_and_succeeds_on_nth_attempt() -> None:
    """Fails twice, then succeeds on the third call."""
    call_count = 0

    def handler() -> str:
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ValueError("transient")
        return "recovered"

    mw = RetryMiddleware(max_retries=3, initial_delay=0.0)
    result = mw.wrap(handler)
    assert result == "recovered"
    assert call_count == 3


def test_exhaustion_raises_retry_exhausted_error() -> None:
    """All attempts fail — RetryExhaustedError raised with correct attempt count."""
    handler = MagicMock(side_effect=ValueError("permanent"))
    mw = RetryMiddleware(max_retries=2, initial_delay=0.0)

    with pytest.raises(RetryExhaustedError) as exc_info:
        mw.wrap(handler)

    assert exc_info.value.attempts == 3  # max_retries + 1
    assert isinstance(exc_info.value.last_exception, ValueError)
    assert handler.call_count == 3


def test_only_retryable_exceptions_are_retried() -> None:
    """Non-retryable exceptions propagate immediately without retry."""
    handler = MagicMock(side_effect=TypeError("not retryable"))
    mw = RetryMiddleware(
        max_retries=3,
        initial_delay=0.0,
        retryable_exceptions=(ValueError,),
    )

    with pytest.raises(TypeError, match="not retryable"):
        mw.wrap(handler)

    handler.assert_called_once()


def test_backoff_is_applied_between_retries() -> None:
    """Verify time.sleep is called with exponentially increasing delays."""
    handler = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])
    mw = RetryMiddleware(max_retries=3, initial_delay=1.0, backoff_factor=2.0)

    with patch("langchain_middleware_stack.middleware.retry.time.sleep") as mock_sleep:
        mw.wrap(handler)

    assert mock_sleep.call_count == 2
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert delays[0] == pytest.approx(1.0)
    assert delays[1] == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_async_succeeds_on_first_attempt() -> None:
    handler = AsyncMock(return_value="async_ok")
    mw = RetryMiddleware(max_retries=3)
    result = await mw.awrap(handler)
    assert result == "async_ok"
    handler.assert_called_once()


@pytest.mark.asyncio
async def test_async_exhaustion_raises() -> None:
    handler = AsyncMock(side_effect=RuntimeError("async fail"))
    mw = RetryMiddleware(max_retries=1, initial_delay=0.0)

    with pytest.raises(RetryExhaustedError) as exc_info:
        await mw.awrap(handler)

    assert exc_info.value.attempts == 2


def test_ordering_in_stack() -> None:
    """retry.after=('logging',) places retry after logging even if added first."""
    from langchain_middleware_stack.middleware.logging import LoggingMiddleware

    retry = RetryMiddleware()
    log = LoggingMiddleware()

    stack = MiddlewareStack()
    stack.add(retry)  # added first
    stack.add(log)    # added second

    ordered = stack.resolve()
    assert ordered == [log, retry]
