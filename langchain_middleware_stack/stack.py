"""Middleware stack with slug-based DAG resolution.

Middleware declares its own identity and ordering constraints via ClassVar
descriptors (``slug``, ``after``, ``before``).  ``MiddlewareStack`` collects
entries, validates the dependency graph, resolves cross-middleware wiring, and
produces the ordered list via stable topological sort.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from langchain_middleware_stack.errors import (
    MiddlewareCycleError,
    MiddlewareDuplicateSlugError,
    MiddlewareResolutionError,
    MiddlewareWiringError,
)

logger = logging.getLogger(__name__)

__all__ = ["MiddlewareStack"]


# ---------------------------------------------------------------------------
# Internal entry representation
# ---------------------------------------------------------------------------


class _Entry:
    """Internal bookkeeping for a single middleware in the stack."""

    __slots__ = ("instance", "slug", "after", "before", "wires", "index")

    def __init__(
        self,
        instance: Any,
        slug: str,
        after: tuple[str, ...],
        before: tuple[str, ...],
        wires: dict[str, tuple[str, str]],
        index: int,
    ) -> None:
        self.instance = instance
        self.slug = slug
        self.after = after
        self.before = before
        self.wires = wires
        self.index = index


# ---------------------------------------------------------------------------
# MiddlewareStack
# ---------------------------------------------------------------------------


class MiddlewareStack:
    """Collect middleware, resolve ordering via topological sort, wire cross-refs.

    Usage::

        stack = MiddlewareStack()
        stack.add(TimeoutMiddleware(300))
        stack.add(SummarizationEntry(model=m, backend=b))
        ordered = stack.resolve()
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._counter = 0

    def add(self, middleware: Any) -> MiddlewareStack:
        """Add a middleware instance. Returns self for chaining."""
        slug = getattr(middleware, "slug", None)
        if slug is None:
            raise MiddlewareResolutionError(
                f"{type(middleware).__name__} does not declare a 'slug' ClassVar"
            )
        after: tuple[str, ...] = getattr(middleware, "after", ())
        before: tuple[str, ...] = getattr(middleware, "before", ())
        wires: dict[str, tuple[str, str]] = getattr(middleware, "wires", {})

        self._entries.append(
            _Entry(
                instance=middleware,
                slug=slug,
                after=after,
                before=before,
                wires=wires,
                index=self._counter,
            )
        )
        self._counter += 1
        return self

    def resolve(self) -> list[Any]:
        """Topological sort → validate → wire → return ordered list."""
        entries = list(self._entries)

        # 1. Validate: duplicate slugs
        slug_to_entry: dict[str, _Entry] = {}
        for entry in entries:
            if entry.slug in slug_to_entry:
                raise MiddlewareDuplicateSlugError(entry.slug)
            slug_to_entry[entry.slug] = entry

        present_slugs = set(slug_to_entry)

        # 2. Build DAG (adjacency list + in-degree)
        graph: dict[str, list[str]] = {e.slug: [] for e in entries}
        in_degree: dict[str, int] = {e.slug: 0 for e in entries}

        for entry in entries:
            for dep in entry.after:
                if dep not in present_slugs:
                    continue
                # dep → entry.slug  (dep must come before entry)
                graph[dep].append(entry.slug)
                in_degree[entry.slug] += 1
            for target in entry.before:
                if target not in present_slugs:
                    continue
                # entry.slug → target  (entry must come before target)
                graph[entry.slug].append(target)
                in_degree[target] += 1

        # 3. Stable Kahn's algorithm
        #    When multiple nodes have in-degree 0, pick the one with the
        #    smallest insertion index to preserve .add() order.
        queue: deque[str] = deque()
        for entry in entries:
            if in_degree[entry.slug] == 0:
                queue.append(entry.slug)

        sorted_slugs: list[str] = []
        while queue:
            # Stable selection: among ready nodes, pick lowest insertion index.
            best_idx = 0
            for i in range(1, len(queue)):
                if slug_to_entry[queue[i]].index < slug_to_entry[queue[best_idx]].index:
                    best_idx = i
            # Remove the chosen element from the queue
            chosen = queue[best_idx]
            del queue[best_idx]

            sorted_slugs.append(chosen)
            for neighbor in graph[chosen]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # 4. Cycle detection
        if len(sorted_slugs) != len(entries):
            cycle = self._find_cycle(entries, in_degree)
            raise MiddlewareCycleError(cycle)

        # 5. Validate: every after/before constraint satisfied in resolved order
        slug_position: dict[str, int] = {
            slug: pos for pos, slug in enumerate(sorted_slugs)
        }
        for entry in entries:
            pos = slug_position[entry.slug]
            for dep in entry.after:
                if dep in slug_position and slug_position[dep] >= pos:
                    raise MiddlewareResolutionError(
                        f"Constraint violation: {entry.slug!r} must come after "
                        f"{dep!r} but resolved at position {pos} vs {slug_position[dep]}"
                    )
            for target in entry.before:
                if target in slug_position and slug_position[target] <= pos:
                    raise MiddlewareResolutionError(
                        f"Constraint violation: {entry.slug!r} must come before "
                        f"{target!r} but resolved at position {pos} vs {slug_position[target]}"
                    )

        # 6. Wire cross-references
        for slug in sorted_slugs:
            entry = slug_to_entry[slug]
            if not entry.wires:
                continue
            for target_attr, (source_slug, source_attr) in entry.wires.items():
                if source_slug not in present_slugs:
                    raise MiddlewareWiringError(
                        f"Wiring {entry.slug!r}.{target_attr} → "
                        f"{source_slug!r}.{source_attr}: "
                        f"source slug {source_slug!r} not in stack"
                    )
                if source_slug not in set(entry.after):
                    raise MiddlewareWiringError(
                        f"Wiring {entry.slug!r}.{target_attr} → "
                        f"{source_slug!r}.{source_attr}: "
                        f"source slug {source_slug!r} must be in 'after' declarations"
                    )
                source_entry = slug_to_entry[source_slug]
                if not hasattr(source_entry.instance, source_attr):
                    raise MiddlewareWiringError(
                        f"Wiring {entry.slug!r}.{target_attr} → "
                        f"{source_slug!r}.{source_attr}: "
                        f"attribute {source_attr!r} not found on "
                        f"{type(source_entry.instance).__name__}"
                    )
                value = getattr(source_entry.instance, source_attr)
                setattr(entry.instance, target_attr, value)
                logger.debug(
                    "wired %s.%s from %s.%s",
                    entry.slug,
                    target_attr,
                    source_slug,
                    source_attr,
                )

        # 7. Return ordered list
        return [slug_to_entry[slug].instance for slug in sorted_slugs]

    @staticmethod
    def _find_cycle(
        entries: list[_Entry], in_degree: dict[str, int]
    ) -> list[str]:
        """Extract a cycle path from the remaining nodes with non-zero in-degree."""
        remaining = {e.slug for e in entries if in_degree[e.slug] > 0}
        if not remaining:
            return ["<unknown>"]

        slug_to_entry = {e.slug: e for e in entries}
        start = next(iter(remaining))
        visited: dict[str, int] = {}
        path: list[str] = []
        current = start

        for _ in range(len(remaining) + 1):
            if current in visited:
                cycle_start = visited[current]
                return path[cycle_start:] + [current]
            visited[current] = len(path)
            path.append(current)

            entry = slug_to_entry[current]
            next_node = None
            for dep in entry.after:
                if dep in remaining:
                    next_node = dep
                    break
            if next_node is None:
                for other in entries:
                    if other.slug in remaining and current in other.after:
                        next_node = other.slug
                        break
            if next_node is None:
                break
            current = next_node

        return path + [start] if path else [start]

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        slugs = [e.slug for e in self._entries]
        return f"MiddlewareStack({slugs!r})"
