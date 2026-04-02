# langchain-middleware-stack

Declarative middleware ordering for LangChain and agent frameworks — via stable slug-based DAG resolution.

[![PyPI](https://img.shields.io/pypi/v/langchain-middleware-stack)](https://pypi.org/project/langchain-middleware-stack/)
[![Python](https://img.shields.io/pypi/pyversions/langchain-middleware-stack)](https://pypi.org/project/langchain-middleware-stack/)
[![License](https://img.shields.io/pypi/l/langchain-middleware-stack)](LICENSE)

## Why

Middleware in agent frameworks is typically ordered by insertion position. That fails at scale:

- Position silently shifts as new middleware is added.
- Integration code must know the exact insertion site.
- Two middleware packages cannot express mutual ordering without tight coupling.

`langchain-middleware-stack` solves this with four primitives:

| Primitive | Role |
|-----------|------|
| `slug` | Stable, unique identity for each middleware |
| `after` / `before` | Self-declared ordering constraints |
| `MiddlewareStack` | Topological resolver (Kahn's algorithm, stable tie-break) |
| `wires` | Cross-middleware attribute injection at resolve-time |

## Installation

```bash
pip install langchain-middleware-stack
```

Zero runtime dependencies. Python ≥ 3.9.

## Quick start

```python
from langchain_middleware_stack import MiddlewareStack
from langchain_middleware_stack.middleware import LoggingMiddleware, RetryMiddleware

stack = MiddlewareStack()
stack.add(RetryMiddleware(max_retries=3))
stack.add(LoggingMiddleware())
ordered = stack.resolve()
# -> [LoggingMiddleware, RetryMiddleware]
# retry.after=("logging",) reordered — every retry is logged
```

## Writing your own middleware

```python
from typing import ClassVar
from langchain_middleware_stack import BaseMiddleware

class TracingMiddleware(BaseMiddleware):
    slug: ClassVar[str] = "tracing"
    after: ClassVar[tuple[str, ...]] = ("logging",)  # run after logging

    def wrap(self, handler, *args, **kwargs):
        with tracer.start_span(handler.__name__):
            return handler(*args, **kwargs)

    async def awrap(self, handler, *args, **kwargs):
        with tracer.start_span(handler.__name__):
            return await handler(*args, **kwargs)
```

`BaseMiddleware` is a mixin — it is fully compatible with LangChain's `AgentMiddleware`:

```python
from langchain.agents.middleware import AgentMiddleware
from langchain_middleware_stack import BaseMiddleware

class MyMiddleware(AgentMiddleware, BaseMiddleware):
    slug: ClassVar[str] = "my-middleware"
```

## Cross-middleware wiring

`wires` injects an attribute from a resolved upstream middleware into your middleware at stack build time:

```python
class ConsumerMiddleware(BaseMiddleware):
    slug: ClassVar[str] = "consumer"
    after: ClassVar[tuple[str, ...]] = ("provider",)
    wires: ClassVar[dict[str, tuple[str, str]]] = {
        "_shared_fn": ("provider", "exported_fn")
    }
    # _shared_fn is injected from provider.exported_fn after resolve()
```

## Error reference

| Exception | Raised when |
|-----------|------------|
| `MiddlewareResolutionError` | Base class for all stack build errors |
| `MiddlewareCycleError` | Dependency graph contains a cycle |
| `MiddlewareDuplicateSlugError` | Two middleware share the same slug |
| `MiddlewareWiringError` | Cross-middleware wiring fails |
| `RetryExhaustedError` | `RetryMiddleware` runs out of attempts |

## LangChain community PR

This package is the foundation for a proposed contribution to `langchain-ai/langchain` ([tracking issue](https://github.com/langchain-ai/langchain/issues)). The goal is a minimal middleware abstraction in `langchain_community/middleware/` that any LangChain chain can adopt.

## License

Apache-2.0
