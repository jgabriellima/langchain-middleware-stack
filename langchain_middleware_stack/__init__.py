# langchain_middleware_stack/__init__.py
"""langchain-middleware-stack — declarative middleware ordering via slug-based DAG resolution.

Zero runtime dependencies. Works with LangChain, LangGraph, deepagents, or any
agent framework. Middleware declares its own ordering constraints; MiddlewareStack
resolves them at build time.

Example::

    from langchain_middleware_stack import MiddlewareStack
    from langchain_middleware_stack.middleware import LoggingMiddleware, RetryMiddleware

    stack = MiddlewareStack()
    stack.add(RetryMiddleware(max_retries=3))
    stack.add(LoggingMiddleware())
    ordered = stack.resolve()
    # -> [LoggingMiddleware, RetryMiddleware]
    # retry.after=("logging",) reordered — every retry attempt is logged
"""

from langchain_middleware_stack.errors import (
    MiddlewareCycleError,
    MiddlewareDuplicateSlugError,
    MiddlewareResolutionError,
    MiddlewareWiringError,
    RetryExhaustedError,
)
from langchain_middleware_stack.protocol import BaseMiddleware, SupportsMiddlewareDescriptor
from langchain_middleware_stack.stack import MiddlewareStack

__all__ = [
    "BaseMiddleware",
    "MiddlewareCycleError",
    "MiddlewareDuplicateSlugError",
    "MiddlewareResolutionError",
    "MiddlewareStack",
    "MiddlewareWiringError",
    "RetryExhaustedError",
    "SupportsMiddlewareDescriptor",
]
