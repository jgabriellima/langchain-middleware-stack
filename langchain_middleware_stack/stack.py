"""Middleware stack with slug-based DAG resolution.

Middleware declares its own identity and ordering constraints via ClassVar
descriptors (``slug``, ``after``, ``before``).  ``MiddlewareStack`` collects
entries, validates the dependency graph, resolves cross-middleware wiring, and
produces the ordered list via stable topological sort.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Optional

from langchain_middleware_stack.errors import (
    MiddlewareCycleError,
    MiddlewareDuplicateSlugError,
    MiddlewareResolutionError,
    MiddlewareWiringError,
)

logger = logging.getLogger(__name__)

__all__ = ["MiddlewareStack"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug_to_node_id(slug: str) -> str:
    """Convert a slug to a valid Mermaid node identifier (no hyphens)."""
    return slug.replace("-", "_")


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
        # or: stack.add([TimeoutMiddleware(300), SummarizationEntry(model=m, backend=b)])
        ordered = stack.resolve()
    """

    def __init__(self) -> None:
        self._entries: list[_Entry] = []
        self._counter = 0

    def _append_entry(self, middleware: Any) -> None:
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

    def add(self, *middlewares: Any) -> MiddlewareStack:
        """Register one or more middleware instances. Returns self for chaining.

        Forms:

        * ``stack.add(mw)`` — single instance.
        * ``stack.add(a, b, c)`` — multiple instances (left-to-right registration order).
        * ``stack.add([a, b, c])`` or ``stack.add((a, b, c))`` — same as three separate adds.

        An empty list/tuple is allowed (no-op).
        """
        if not middlewares:
            raise TypeError("add() requires at least one argument")
        if len(middlewares) == 1 and isinstance(middlewares[0], (list, tuple)):
            for mw in middlewares[0]:
                self._append_entry(mw)
            return self
        for mw in middlewares:
            self._append_entry(mw)
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

    # ── Graph visualisation ──────────────────────────────────────────────────

    def draw_mermaid(self, *, include_model_call: bool = True) -> str:
        """Return a Mermaid ``flowchart LR`` string for the constraint DAG.

        Each registered middleware becomes a node.  Directed edges represent
        declared ``after`` / ``before`` constraints between slugs that are both
        present in the stack.  An optional terminal ``model_call`` sink node is
        appended and wired to the innermost (last resolved) middleware.

        Args:
            include_model_call: When ``True`` (default) append a
                ``model_call`` sink node and connect the innermost middleware
                to it.

        Returns:
            A Mermaid ``flowchart LR`` string compatible with ``mermaid.js``,
            ``mermaid.ink``, GitHub Markdown, and Jupyter ``%%mermaid`` magic.
        """
        entries = self._entries
        present_slugs = {e.slug for e in entries}

        lines: list[str] = ["flowchart LR"]

        for e in entries:
            node_id = _slug_to_node_id(e.slug)
            class_name = type(e.instance).__name__
            lines.append(f'    {node_id}["{e.slug}\\n({class_name})"]')

        if include_model_call:
            lines.append('    model_call(["⚙ model_call"])')

        edges: set[tuple[str, str]] = set()
        for e in entries:
            for dep in e.after:
                if dep in present_slugs:
                    edges.add((dep, e.slug))
            for target in e.before:
                if target in present_slugs:
                    edges.add((e.slug, target))

        for src, dst in sorted(edges):
            lines.append(f"    {_slug_to_node_id(src)} --> {_slug_to_node_id(dst)}")

        if include_model_call and entries:
            try:
                resolved = self.resolve()
                if resolved:
                    innermost = _slug_to_node_id(resolved[-1].slug)
                    lines.append(f"    {innermost} --> model_call")
            except Exception:
                pass

        return "\n".join(lines)

    def draw_mermaid_png(
        self,
        *,
        include_model_call: bool = True,
        background_color: str = "white",
        timeout_s: int = 15,
    ) -> bytes:
        """Render the middleware DAG as a PNG using a public Mermaid render API.

        Attempts ``mermaid.ink`` first, then falls back to ``kroki.io``.
        No extra runtime dependencies — only stdlib ``urllib`` and ``base64``
        are used.  Requires outbound HTTPS access to at least one of these
        services.

        Args:
            include_model_call: Forwarded to :meth:`draw_mermaid`.
            background_color: CSS colour value for the diagram background
                (e.g. ``"white"``, ``"transparent"``, ``"#f8f8f8"``).
                Passed to ``mermaid.ink``; ignored by ``kroki.io``.
            timeout_s: HTTP request timeout in seconds per service attempt.

        Returns:
            Raw PNG bytes suitable for writing to a file or passing to
            ``IPython.display.Image(data=...)``.

        Raises:
            RuntimeError: When all render services fail.
        """
        import base64
        import urllib.parse
        import urllib.request

        source = self.draw_mermaid(include_model_call=include_model_call)

        errors: list[str] = []

        # ── Attempt 1: mermaid.ink ────────────────────────────────────────────
        try:
            encoded = base64.urlsafe_b64encode(source.encode()).decode()
            bg = urllib.parse.quote(background_color, safe="")
            url = f"https://mermaid.ink/img/{encoded}?bgColor={bg}"
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
                return resp.read()
        except Exception as exc:
            errors.append(f"mermaid.ink: {exc}")

        # ── Attempt 2: kroki.io ───────────────────────────────────────────────
        try:
            encoded = base64.urlsafe_b64encode(source.encode()).decode().rstrip("=")
            url = f"https://kroki.io/mermaid/png/{encoded}"
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310
                return resp.read()
        except Exception as exc:
            errors.append(f"kroki.io: {exc}")

        raise RuntimeError(
            "All Mermaid render services failed:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + "\n\nFallback: call stack.draw_mermaid() and paste into "
            "https://mermaid.live to render offline."
        )

    def display(
        self,
        *,
        format: str = "auto",
        include_model_call: bool = True,
    ) -> Optional[Any]:
        """Display or return the middleware constraint DAG.

        Mirrors the ``graph.draw_mermaid_png()`` / display pattern from
        LangGraph so the API feels familiar.

        Behaviour by *format*:

        * ``"auto"`` *(default)* — in Jupyter / IPython, renders a PNG via
          :meth:`draw_mermaid_png`, or if that fails (no kernel network), an
          ``<img>`` to the same mermaid.ink URL so the browser can load it
          (frontends often strip ``<script>``-based Mermaid).  Outside IPython,
          returns the Mermaid source string.
        * ``"mermaid"`` — always returns the Mermaid source string.
        * ``"png"`` — always returns raw PNG bytes.

        Args:
            format: ``"auto"``, ``"mermaid"``, or ``"png"``.
            include_model_call: Forwarded to the underlying draw methods.

        Returns:
            ``None`` after inline Jupyter display; ``str`` for ``"mermaid"``
            or the ``"auto"`` fallback; ``bytes`` for ``"png"``.
        """
        if format == "mermaid":
            return self.draw_mermaid(include_model_call=include_model_call)

        if format == "png":
            return self.draw_mermaid_png(include_model_call=include_model_call)

        # "auto": attempt inline Jupyter/IPython rendering
        try:
            import base64
            import urllib.parse

            from IPython import get_ipython
            from IPython.display import HTML, Image
            from IPython.display import display as _ipy_display

            if get_ipython() is not None:
                try:
                    png = self.draw_mermaid_png(
                        include_model_call=include_model_call,
                    )
                    _ipy_display(Image(data=png))
                    return None
                except RuntimeError:
                    # Many Jupyter frontends strip or ignore <script>, so a
                    # mermaid.js HTML fallback shows raw source.  Ask the
                    # browser to load the same PNG URL instead (may work when
                    # the kernel cannot reach mermaid.ink but the UI can).
                    src = self.draw_mermaid(include_model_call=include_model_call)
                    encoded = base64.urlsafe_b64encode(src.encode()).decode()
                    bg = urllib.parse.quote("white", safe="")
                    url = f"https://mermaid.ink/img/{encoded}?bgColor={bg}"
                    _ipy_display(
                        HTML(
                            "<p style=\"color:#666;font-size:0.9em\">"
                            "Diagram via browser (mermaid.ink). "
                            "If this image fails, paste <code>draw_mermaid()</code> "
                            "output into <a href=\"https://mermaid.live\">mermaid.live</a>."
                            "</p>"
                            f'<img src="{url}" alt="Middleware constraint graph" />'
                        )
                    )
                    return None
        except ImportError:
            pass

        return self.draw_mermaid(include_model_call=include_model_call)

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        slugs = [e.slug for e in self._entries]
        return f"MiddlewareStack({slugs!r})"
