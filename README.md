# langchain-middleware-stack

Declarative middleware ordering for LangChain Deep Agents using stable slug-based DAG resolution.

[PyPI](https://pypi.org/project/langchain-middleware-stack/) · [License](LICENSE)

**Docs:** [Technical context](docs/context.md) · [Community PR issue draft](docs/github-issue-langchain-community.md)

After you enable **GitHub Pages** from the `/docs` folder, add your site URL to `docs/index.html` (repository link) and to `pyproject.toml` under `[project.urls]`.

## Why

In LangChain Deep Agents, middleware is a **first-class control layer** over model calls, tools, and state. The framework still composes it as a **positional** `middleware=[...]` list on `create_agent`. In that model, **ordering is semantics**: the first entry is the **outermost** wrapper (for example around `wrap_model_call`), so reordering changes retries, timeouts, logging, and policy in non-obvious ways.

The underlying issue is not middleware itself — it is that **composition is positional instead of declarative**. That breaks down in production because:

- **Fragility** — Inserting or reordering entries changes behavior; constraints like “after logging, before retry” are not declared on the middleware type.
- **Poor composability** — Separate teams or packages cannot merge contributions without one owner of the final list and implicit coordination.
- **Hidden coupling** — Dependencies are expressed as indices, not as explicit, reviewable constraints.
- **No validated guarantees** — Ordering invariants and dependency relationships are not enforced before runtime.

**`langchain-middleware-stack`** addresses this with **constraint-based composition** (DAG + topological sort, stable Kahn tie-break). You declare intent with four primitives:


| Primitive          | Role                                                      |
| ------------------ | --------------------------------------------------------- |
| `slug`             | Stable, unique identity for each middleware               |
| `after` / `before` | Self-declared ordering constraints                        |
| `MiddlewareStack`  | Topological resolver (Kahn's algorithm, stable tie-break) |
| `wires`            | Cross-middleware attribute injection at resolve-time      |


## Installation

```bash
pip install langchain-middleware-stack
```

Zero runtime dependencies. Python ≥ 3.9.

## Demo notebook

[`notebooks/deep-agents-middleware.ipynb`](notebooks/deep-agents-middleware.ipynb) walks through **baseline vs improved**, both using a **real** [`ChatOpenAI`](https://python.langchain.com/docs/integrations/chat/openai/) model (`OPENAI_API_KEY` required for those cells):

| | |
| -- | -- |
| **Baseline** | [`create_agent`](https://reference.langchain.com/python/langchain/agents/create_agent) with a **manually ordered** `middleware=[...]` list. |
| **Improved** | The same middleware types added to a `MiddlewareStack` in **scrambled** order; `resolve()` produces the LangChain list (**outermost first**), then `create_agent` uses that list. |

**Appendices** at the end: an offline `wrap(handler)` toy stack and optional LangChain `FakeListChatModel` — not the main teaching path.

```bash
make notebook   # from a dev setup with `make setup`
```

## Quick start

```python
from langchain_middleware_stack import MiddlewareStack
from langchain_middleware_stack.middleware import LoggingMiddleware, RetryMiddleware

stack = MiddlewareStack()
stack.add([RetryMiddleware(max_retries=3), LoggingMiddleware()])
# or: stack.add(RetryMiddleware(...)).add(LoggingMiddleware())
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

`BaseMiddleware` is a mixin — use it **with** LangChain's `AgentMiddleware` when you pass middleware into `create_agent`. Subclasses must implement the agent hooks you need (typically `wrap_model_call`); declare `tools` (often `()`) on the class.

```python
from typing import ClassVar

from langchain.agents.middleware import AgentMiddleware
from langchain_middleware_stack import BaseMiddleware

class MyMiddleware(AgentMiddleware, BaseMiddleware):
    slug: ClassVar[str] = "my-middleware"
    tools: ClassVar[tuple] = ()

    def wrap_model_call(self, request, handler):
        # intercept model calls; delegate with handler(request)
        return handler(request)
```

The notebook uses this pattern end-to-end for the baseline and improved scenarios.

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


| Exception                      | Raised when                            |
| ------------------------------ | -------------------------------------- |
| `MiddlewareResolutionError`    | Base class for all stack build errors  |
| `MiddlewareCycleError`         | Dependency graph contains a cycle      |
| `MiddlewareDuplicateSlugError` | Two middleware share the same slug     |
| `MiddlewareWiringError`        | Cross-middleware wiring fails          |
| `RetryExhaustedError`          | `RetryMiddleware` runs out of attempts |


## LangChain community PR

This package is the foundation for a proposed contribution to `langchain-ai/langchain` ([tracking issue](https://github.com/langchain-ai/langchain/issues)). The goal is a minimal middleware abstraction in `langchain_community/middleware/` that any LangChain chain can adopt.

## License

Apache-2.0

## Author

João Gabriel Lima 
[joaogabriellima.eng@gmail.com](mailto:joaogabriellima.eng@gmail.com)
[https://jambu.ai](https://jambu.ai)