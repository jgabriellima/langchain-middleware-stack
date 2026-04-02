# tests/test_stack.py
from __future__ import annotations
from typing import Any, ClassVar
import pytest
from langchain_middleware_stack.errors import (
    MiddlewareCycleError, MiddlewareDuplicateSlugError,
    MiddlewareResolutionError, MiddlewareWiringError,
)
from langchain_middleware_stack.protocol import BaseMiddleware
from langchain_middleware_stack.stack import MiddlewareStack


def _make(slug, after=(), before=(), wires=None):
    attrs = {"slug": slug, "after": after, "before": before}
    if wires is not None:
        attrs["wires"] = wires
    cls = type(f"Stub_{slug}", (BaseMiddleware,), attrs)
    return cls()


class TestResolution:
    def test_single_middleware(self):
        a = _make("a")
        assert MiddlewareStack().add(a).resolve() == [a]

    def test_simple_chain_abc(self):
        a = _make("a", before=("b",))
        b = _make("b", after=("a",), before=("c",))
        c = _make("c", after=("b",))
        stack = MiddlewareStack()
        stack.add(a).add(b).add(c)
        assert stack.resolve() == [a, b, c]

    def test_reverse_insertion_order(self):
        c = _make("c", after=("b",))
        b = _make("b", after=("a",))
        a = _make("a")
        stack = MiddlewareStack()
        stack.add(c).add(b).add(a)
        assert stack.resolve() == [a, b, c]

    def test_before_constraint(self):
        b = _make("b")
        a = _make("a", before=("b",))
        stack = MiddlewareStack()
        stack.add(b).add(a)
        result = stack.resolve()
        assert result.index(a) < result.index(b)

    def test_absent_after_dependency_is_skipped(self):
        a = _make("a", after=("missing",))
        assert MiddlewareStack().add(a).resolve() == [a]

    def test_absent_before_dependency_is_skipped(self):
        a = _make("a", before=("missing",))
        assert MiddlewareStack().add(a).resolve() == [a]

    def test_stable_tie_breaking_by_insertion_order(self):
        a, b, c = _make("a"), _make("b"), _make("c")
        stack = MiddlewareStack()
        stack.add(a).add(b).add(c)
        assert stack.resolve() == [a, b, c]

    def test_chaining_add_returns_self(self):
        stack = MiddlewareStack()
        assert stack.add(_make("x")) is stack

    def test_len(self):
        stack = MiddlewareStack()
        stack.add(_make("a")).add(_make("b"))
        assert len(stack) == 2

    def test_repr(self):
        stack = MiddlewareStack()
        stack.add(_make("a")).add(_make("b"))
        assert "a" in repr(stack) and "b" in repr(stack)


class TestErrors:
    def test_missing_slug_raises_resolution_error(self):
        class _NoSlug: pass
        with pytest.raises(MiddlewareResolutionError, match="slug"):
            MiddlewareStack().add(_NoSlug())

    def test_duplicate_slug_raises(self):
        a1, a2 = _make("dup"), _make("dup")
        with pytest.raises(MiddlewareDuplicateSlugError) as exc_info:
            MiddlewareStack().add(a1).add(a2).resolve()
        assert exc_info.value.slug == "dup"

    def test_cycle_detection(self):
        a = _make("a", after=("b",))
        b = _make("b", after=("a",))
        with pytest.raises(MiddlewareCycleError) as exc_info:
            MiddlewareStack().add(a).add(b).resolve()
        assert "a" in exc_info.value.cycle or "b" in exc_info.value.cycle

    def test_three_node_cycle(self):
        a = _make("a", after=("c",))
        b = _make("b", after=("a",))
        c = _make("c", after=("b",))
        with pytest.raises(MiddlewareCycleError):
            MiddlewareStack().add(a).add(b).add(c).resolve()


class TestWiring:
    def test_wiring_injects_attribute(self):
        source = _make("source")
        source.exported_fn = lambda: 42
        consumer = _make("consumer", after=("source",), wires={"_fn": ("source", "exported_fn")})
        MiddlewareStack().add(source).add(consumer).resolve()
        assert hasattr(consumer, "_fn") and consumer._fn() == 42

    def test_wiring_missing_source_slug_raises(self):
        consumer = _make("consumer", after=("ghost",), wires={"_fn": ("ghost", "fn")})
        with pytest.raises(MiddlewareWiringError, match="ghost"):
            MiddlewareStack().add(consumer).resolve()

    def test_wiring_requires_source_in_after(self):
        source = _make("source")
        consumer = _make("consumer", wires={"_fn": ("source", "fn")})
        with pytest.raises(MiddlewareWiringError, match="must be in 'after'"):
            MiddlewareStack().add(source).add(consumer).resolve()

    def test_wiring_missing_attribute_on_source_raises(self):
        source = _make("source")
        consumer = _make("consumer", after=("source",), wires={"_fn": ("source", "nonexistent")})
        with pytest.raises(MiddlewareWiringError, match="nonexistent"):
            MiddlewareStack().add(source).add(consumer).resolve()
