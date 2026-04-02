# langchain_middleware_stack/middleware/retry.py
"""RetryMiddleware — wraps callable invocations with exponential backoff and retry."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from langchain_middleware_stack.errors import RetryExhaustedError
from langchain_middleware_stack.protocol import BaseMiddleware

__all__ = ["RetryMiddleware"]


class RetryMiddleware(BaseMiddleware):
    """Retry calls on failure with exponential backoff.

    Runs after LoggingMiddleware so every retry attempt is logged.

    Retry contract:
        - ``max_retries``: number of *additional* attempts after first failure.
        - Total handler invocations: at most ``max_retries + 1``.
        - ``RetryExhaustedError.attempts``: total invocations made (= max_retries + 1).

    Args:
        max_retries: Additional attempts after the first failure. Default: 3.
        initial_delay: Seconds to wait before the first retry. Default: 1.0.
        backoff_factor: Multiplier applied to delay after each retry. Default: 2.0.
        retryable_exceptions: Exception types that trigger a retry. Default: all
            ``Exception`` subclasses.
    """

    slug: ClassVar[str] = "retry"
    after: ClassVar[tuple[str, ...]] = ("logging",)
    before: ClassVar[tuple[str, ...]] = ()

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    ) -> None:
        self._max_retries = max_retries
        self._initial_delay = initial_delay
        self._backoff_factor = backoff_factor
        self._retryable_exceptions = retryable_exceptions

    def wrap(self, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Wrap a synchronous callable with retry logic."""
        delay = self._initial_delay
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return handler(*args, **kwargs)
            except self._retryable_exceptions as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(delay)
                    delay *= self._backoff_factor
            except Exception:
                raise

        raise RetryExhaustedError(
            attempts=self._max_retries + 1,
            last_exception=last_exc,  # type: ignore[arg-type]
        )

    async def awrap(
        self,
        handler: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Wrap an async callable with retry logic."""
        delay = self._initial_delay
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                return await handler(*args, **kwargs)
            except self._retryable_exceptions as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(delay)
                    delay *= self._backoff_factor
            except Exception:
                raise

        raise RetryExhaustedError(
            attempts=self._max_retries + 1,
            last_exception=last_exc,  # type: ignore[arg-type]
        )
