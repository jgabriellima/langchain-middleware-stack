# langchain_middleware_stack/middleware/logging.py
"""LoggingMiddleware — records entry, exit, latency, and errors for every call."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from langchain_middleware_stack.protocol import BaseMiddleware

__all__ = ["LoggingMiddleware"]

_DEFAULT_LOGGER = logging.getLogger("langchain_middleware_stack.logging")


class LoggingMiddleware(BaseMiddleware):
    """Middleware that logs every wrapped call: entry, exit, latency, and errors.

    Designed to run first in the stack so all downstream middleware calls
    (including retries) are captured.

    Example::

        stack = MiddlewareStack()
        stack.add([RetryMiddleware(max_retries=3), LoggingMiddleware()])
        ordered = stack.resolve()
        # -> [LoggingMiddleware, RetryMiddleware]

    Args:
        logger: Logger instance to use. Defaults to
            ``langchain_middleware_stack.logging``.
        level: Log level for entry/exit records. Defaults to ``logging.INFO``.
    """

    slug: ClassVar[str] = "logging"
    after: ClassVar[tuple[str, ...]] = ()
    before: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        logger: logging.Logger | None = None,
        level: int = logging.INFO,
    ) -> None:
        self._logger = logger or _DEFAULT_LOGGER
        self._level = level

    def wrap(self, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Wrap a synchronous callable, logging entry, exit, and latency."""
        self._logger.log(self._level, "middleware.call.start handler=%s", _name(handler))
        start = time.monotonic()
        try:
            result = handler(*args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.log(
                self._level,
                "middleware.call.end handler=%s latency_ms=%.1f",
                _name(handler),
                elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.error(
                "middleware.call.error handler=%s latency_ms=%.1f error=%s",
                _name(handler),
                elapsed_ms,
                exc,
            )
            raise

    async def awrap(
        self,
        handler: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Wrap an async callable, logging entry, exit, and latency."""
        self._logger.log(self._level, "middleware.call.start handler=%s", _name(handler))
        start = time.monotonic()
        try:
            result = await handler(*args, **kwargs)
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.log(
                self._level,
                "middleware.call.end handler=%s latency_ms=%.1f",
                _name(handler),
                elapsed_ms,
            )
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            self._logger.error(
                "middleware.call.error handler=%s latency_ms=%.1f error=%s",
                _name(handler),
                elapsed_ms,
                exc,
            )
            raise


def _name(handler: Callable[..., Any]) -> str:
    return getattr(handler, "__name__", repr(handler))
