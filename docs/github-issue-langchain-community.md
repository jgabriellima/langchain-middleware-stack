# GitHub Issue — langchain-ai/langchain

**Title:** `[Community] Add middleware abstractions for chain execution`

**Body:**

---

## Problem

LangChain's current middleware hooks (`AgentMiddleware.wrap_model_call`, `awrap_model_call`) are ordered positionally at integration time. As stacks grow, position silently shifts, creating fragile ordering that cannot express mutual constraints across packages.

Concrete failures:
- A `RetryMiddleware` added before `LoggingMiddleware` means retries are never logged — silent correctness bug.
- Two independent packages cannot declare ordering between each other without tight coupling.
- No stable identity per middleware — "the second element in the list" is not a contract.

## Proposal

A minimal `middleware/` module in `langchain_community` with:

- A `SupportsMiddlewareDescriptor` Protocol (`slug` + `after`/`before`/`wires` ClassVars)
- A `MiddlewareStack` resolver (topological sort via Kahn's algorithm, zero dependencies, ~230 LOC)
- 2 reference implementations: `LoggingMiddleware`, `RetryMiddleware`

## Scope

- No changes to `langchain_core`
- Pure addition in `langchain_community/middleware/`
- Existing middleware and usage is entirely unaffected
- Python ≥ 3.9 compatible

## Out of scope

- YAML/JSON spec loaders
- Streaming hooks
- Prompt middleware
- Changes to `langchain_core` base classes

## External package

The full implementation is published as [`langchain-middleware-stack`](https://pypi.org/project/langchain-middleware-stack/) on PyPI.

- Zero runtime dependencies
- 50 tests, all passing
- Apache-2.0 license

The PR would vendor only the resolver (~230 LOC: `MiddlewareStack`, `_Entry`, error classes) if maintainers prefer no new external dependency.

## Usage example

```python
from langchain_community.middleware import MiddlewareStack, LoggingMiddleware, RetryMiddleware

stack = MiddlewareStack()
stack.add(RetryMiddleware(max_retries=3))
stack.add(LoggingMiddleware())
ordered = stack.resolve()
# -> [LoggingMiddleware, RetryMiddleware]
# retry.after=("logging",) reorders correctly — every retry attempt is logged
```

## Writing custom middleware

```python
from typing import ClassVar
from langchain_community.middleware import BaseMiddleware

class TracingMiddleware(BaseMiddleware):
    slug: ClassVar[str] = "tracing"
    after: ClassVar[tuple[str, ...]] = ("logging",)

    def wrap(self, handler, *args, **kwargs):
        with tracer.start_span(handler.__name__):
            return handler(*args, **kwargs)

    async def awrap(self, handler, *args, **kwargs):
        with tracer.start_span(handler.__name__):
            return await handler(*args, **kwargs)
```

`BaseMiddleware` is a mixin — fully compatible with the existing `AgentMiddleware`:

```python
from langchain.agents.middleware import AgentMiddleware
from langchain_community.middleware import BaseMiddleware

class MyMiddleware(AgentMiddleware, BaseMiddleware):
    slug: ClassVar[str] = "my-middleware"
    after: ClassVar[tuple[str, ...]] = ("logging",)
```

## Cross-middleware attribute wiring

```python
class ConsumerMiddleware(BaseMiddleware):
    slug: ClassVar[str] = "consumer"
    after: ClassVar[tuple[str, ...]] = ("provider",)
    wires: ClassVar[dict[str, tuple[str, str]]] = {
        "_shared_fn": ("provider", "exported_fn")
    }
    # _shared_fn is injected from provider.exported_fn at stack.resolve() time
```

## References

- PyPI package: https://pypi.org/project/langchain-middleware-stack/
- Whitepaper: _Declarative Middleware Composition for Agent Stacks_ (available on request)
