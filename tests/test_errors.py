# tests/test_errors.py
from langchain_middleware_stack.errors import (
    MiddlewareResolutionError,
    MiddlewareCycleError,
    MiddlewareDuplicateSlugError,
    MiddlewareWiringError,
    RetryExhaustedError,
)


def test_cycle_error_stores_cycle_and_formats_message() -> None:
    err = MiddlewareCycleError(["a", "b", "a"])
    assert err.cycle == ["a", "b", "a"]
    assert "a → b → a" in str(err)


def test_duplicate_slug_error_stores_slug() -> None:
    err = MiddlewareDuplicateSlugError("logging")
    assert err.slug == "logging"
    assert "logging" in str(err)


def test_wiring_error_stores_detail() -> None:
    detail = "slug 'x' not in stack"
    err = MiddlewareWiringError(detail)
    assert err.detail == detail
    assert detail in str(err)


def test_retry_exhausted_stores_attempts_and_cause() -> None:
    cause = ValueError("boom")
    err = RetryExhaustedError(attempts=4, last_exception=cause)
    assert err.attempts == 4
    assert err.last_exception is cause
    assert "4" in str(err)


def test_error_hierarchy() -> None:
    assert issubclass(MiddlewareCycleError, MiddlewareResolutionError)
    assert issubclass(MiddlewareDuplicateSlugError, MiddlewareResolutionError)
    assert issubclass(MiddlewareWiringError, MiddlewareResolutionError)
    assert issubclass(MiddlewareResolutionError, Exception)
    assert issubclass(RetryExhaustedError, Exception)
    # RetryExhaustedError is NOT a MiddlewareResolutionError — it's a runtime failure
    assert not issubclass(RetryExhaustedError, MiddlewareResolutionError)
