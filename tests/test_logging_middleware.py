# tests/test_logging_middleware.py
"""Tests for LoggingMiddleware — sync and async, success and error paths."""
from __future__ import annotations

import logging
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from langchain_middleware_stack.middleware.logging import LoggingMiddleware
from langchain_middleware_stack.protocol import BaseMiddleware
from langchain_middleware_stack.stack import MiddlewareStack


def test_slug_and_constraints() -> None:
    mw = LoggingMiddleware()
    assert mw.slug == "logging"
    assert mw.after == ()
    assert mw.before == ()


def test_sync_wrap_calls_handler_and_returns_result(caplog: pytest.LogCaptureFixture) -> None:
    handler = MagicMock(return_value="result")
    mw = LoggingMiddleware()

    with caplog.at_level(logging.INFO):
        result = mw.wrap(handler, "arg1", key="val")

    assert result == "result"
    handler.assert_called_once_with("arg1", key="val")


def test_sync_wrap_logs_entry_and_exit(caplog: pytest.LogCaptureFixture) -> None:
    handler = MagicMock(return_value="ok")
    mw = LoggingMiddleware()

    with caplog.at_level(logging.INFO):
        mw.wrap(handler)

    assert any("logging" in r.message.lower() or "wrap" in r.message.lower() or "call" in r.message.lower() for r in caplog.records)


def test_sync_wrap_logs_and_reraises_on_error(caplog: pytest.LogCaptureFixture) -> None:
    handler = MagicMock(side_effect=ValueError("boom"))
    mw = LoggingMiddleware()

    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="boom"):
            mw.wrap(handler)

    assert any("boom" in r.message or r.levelno >= logging.ERROR for r in caplog.records)


@pytest.mark.asyncio
async def test_async_wrap_calls_handler_and_returns_result() -> None:
    handler = AsyncMock(return_value="async_result")
    mw = LoggingMiddleware()

    result = await mw.awrap(handler, "arg")

    assert result == "async_result"
    handler.assert_called_once_with("arg")


@pytest.mark.asyncio
async def test_async_wrap_reraises_on_error() -> None:
    handler = AsyncMock(side_effect=RuntimeError("async fail"))
    mw = LoggingMiddleware()

    with pytest.raises(RuntimeError, match="async fail"):
        await mw.awrap(handler)


def test_integrates_with_middleware_stack() -> None:
    """MiddlewareStack resolves LoggingMiddleware correctly."""

    class _RetryStub(BaseMiddleware):
        slug: ClassVar[str] = "retry"
        after: ClassVar[tuple[str, ...]] = ("logging",)

    mw_log = LoggingMiddleware()
    mw_retry = _RetryStub()

    stack = MiddlewareStack()
    stack.add(mw_retry)  # added first
    stack.add(mw_log)    # added second

    ordered = stack.resolve()
    assert ordered == [mw_log, mw_retry]


def test_custom_logger_is_used() -> None:
    custom_logger = MagicMock(spec=logging.Logger)
    mw = LoggingMiddleware(logger=custom_logger)
    handler = MagicMock(return_value=42)

    mw.wrap(handler)

    assert custom_logger.log.called or custom_logger.info.called or custom_logger.debug.called
