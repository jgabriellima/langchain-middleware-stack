# Middleware in Deep Agents (LangChain)

## What middleware is here

In LangChain Deep Agents, middleware is the **control layer** around the runtime: small, composable hooks that sit around model calls, tools, and state updates. You use them to intercept execution, adjust inputs and outputs, and observe what happened—without rewriting the core agent loop each time.

Typical responsibilities include:

- Model calls (`wrap_model_call`)
- Tool execution
- Messages and agent state
- Errors, retries, and fallbacks
- Telemetry and tracing

Think of the list you pass to the framework as a **stack of wrappers**. The first entry is the outermost shell: it sees traffic first on the way in and last on the way out. The last entry hugs the actual runtime. That geometry is what makes ordering meaningful, not arbitrary.

---

## Why it matters

Most “agent behavior” that varies by tenant, environment, or policy does not belong only in a static system prompt. Middleware is where **runtime context engineering** lives: you can branch on context, attach tools conditionally, enforce budgets, strip or redact data, and write to memory—all in one coherent pipeline.

So a Deep Agent is not fully described by model plus tools alone. It is described by those pieces **and** by the middleware that governs how they are invoked, wrapped, and observed.

---

## LangChain today: positional lists

Today, `create_agent` accepts middleware as a plain ordered list:

```python
agent = create_agent(
    model=...,
    tools=[...],
    middleware=[mw1, mw2, mw3]
)
```

Under the hood that becomes nested wrapping, conceptually:

```
mw1(mw2(mw3(core)))
```

So the rules are simple but strict: the **first** list element is the **outermost** middleware; the **last** is **innermost**, closest to the model and tools. Swapping two entries is not a style preference—it changes semantics. A timeout wrapped outside a retry limits total wall clock time; the same timeout placed inside limits each attempt. Same primitives, different contract.

---

## Where positional lists hurt

Positional ordering works for a single author and a short stack. It scales poorly when several teams or packages contribute middleware.

Reordering silently breaks invariants someone else relied on. There is no first-class way to say “this must run after logging but before retry” except documentation and discipline. Dependencies show up as **magic indices** instead of named relationships, and nothing in the API validates that your order forms a consistent DAG or that required neighbors exist—mistakes surface as subtle runtime behavior.

---

## Declarative composition: `MiddlewareStack`

`MiddlewareStack` keeps the same LangChain surface (you still end with one ordered list), but **how** that order is produced is constraint-driven instead of hand-sorted.

Each middleware declares:

- `slug` — stable name used in constraints
- `after` — every slug listed here must appear **earlier** in the resolved list than this one. Earlier index means **farther out** in LangChain’s wrap chain (outer middleware).
- `before` — every slug listed here must appear **later** (closer to the core, **inner**).

Examples:

```python
class CacheMiddleware(BaseMiddleware):
    slug = "cache"
    after = ("logging",)
```

```python
class RateLimitMiddleware(BaseMiddleware):
    slug = "rate-limit"
    after = ("cache",)
    before = ("retry",)
```

You register instances in any convenient order; resolution does the rest:

1. Collect all entries and their slugs.
2. Build a directed graph from `after` / `before`.
3. Run a topological sort (this codebase uses a stable Kahn variant tied to registration order when the DAG allows ties).
4. Return a single list you can pass straight into `create_agent`.

```python
stack = MiddlewareStack()
stack.add(...)
stack.add(...)

ordered = stack.resolve()
```

If the constraints contradict each other, resolution fails at build time rather than in production traffic.

---

## What you gain

Independent packages can publish middleware that only knows its **neighbors by slug**, not its absolute slot in someone else’s list. The resolved order is reproducible: same stack definition yields the same list, and invalid graphs (cycles, impossible ordering) are rejected when you call `resolve()`.

Adding a new layer stops being “insert at index 2 and hope.” It becomes “declare `after` / `before` and let the resolver prove the stack is consistent.” That is the difference between tribal knowledge and an enforceable contract—especially when policy, security, and cost controls are modeled as separate middleware.

---

## Mental model

Hand-maintained lists train you to think in terms of “slot 0, slot 1.” The stack model trains you to think in **edges**: who must wrap whom. The resolver’s job is to turn that graph into exactly one linear order LangChain understands. Once you internalize that, cross-team composition stops feeling like a merge conflict in a Python list.

---

## Positional list vs stack

| Aspect              | Positional list        | MiddlewareStack              |
| ------------------- | ----------------------- | ---------------------------- |
| Composition         | You pick every index    | You declare constraints      |
| Cross-team use      | Shared rules and docs   | Slugs and explicit edges     |
| Refactor safety     | Easy to break silently  | Resolver validates ordering  |
| Ordering guarantees | None from the API       | DAG + topological resolution |

---

## Notebook scope

The companion notebook walks through the same ideas in code: positional middleware in LangChain, concrete cases where reordering changes behavior, then `MiddlewareStack` from this package—DAG construction, resolution, and feeding the result into `create_agent`. It also touches advanced pieces such as `wires`, sharing data across middleware, and lining execution up with tracing where the implementation supports it.

---

## Summary

Middleware is effectively the **control plane** of a Deep Agent: the place execution policy and observability attach. Moving from a raw positional list to a declarative stack does not change LangChain’s execution model; it changes **who is allowed to be wrong about order**—ideally nobody, because the graph either resolves cleanly or fails before you ship.
