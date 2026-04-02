# langchain_middleware_stack/errors.py
"""Exception hierarchy for langchain-middleware-stack."""

from __future__ import annotations

__all__ = [
    "MiddlewareResolutionError",
    "MiddlewareCycleError",
    "MiddlewareDuplicateSlugError",
    "MiddlewareWiringError",
    "RetryExhaustedError",
]


class MiddlewareResolutionError(Exception):
    """Base exception for stack resolution failures (build-time)."""


class MiddlewareCycleError(MiddlewareResolutionError):
    """Raised when the dependency graph contains a cycle."""

    def __init__(self, cycle: list[str]) -> None:
        self.cycle = cycle
        super().__init__("Dependency cycle detected: " + " → ".join(cycle))


class MiddlewareDuplicateSlugError(MiddlewareResolutionError):
    """Raised when two middleware share the same slug."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"Duplicate middleware slug: {slug!r}")


class MiddlewareWiringError(MiddlewareResolutionError):
    """Raised when cross-middleware attribute wiring fails."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class RetryExhaustedError(Exception):
    """Raised by RetryMiddleware after all retry attempts are exhausted.

    Attributes:
        attempts: Total number of handler invocations made (= max_retries + 1).
        last_exception: The exception raised on the final attempt.
    """

    def __init__(self, attempts: int, last_exception: Exception) -> None:
        self.attempts = attempts
        self.last_exception = last_exception
        super().__init__(
            f"Retry exhausted after {attempts} attempt(s): {last_exception}"
        )
