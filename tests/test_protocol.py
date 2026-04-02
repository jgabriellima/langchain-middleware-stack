# tests/test_protocol.py
"""Tests for BaseMiddleware defaults and SupportsMiddlewareDescriptor.

NOTE: We do NOT use isinstance() against SupportsMiddlewareDescriptor for
attribute presence. Python < 3.12 isinstance() checks against
@runtime_checkable Protocol only verify callable members, not plain ClassVar
attributes. The actual runtime contract is enforced by MiddlewareStack.add()
via getattr, not isinstance. We test the behavioural contract instead.
"""
from __future__ import annotations

from typing import ClassVar

import pytest

from langchain_middleware_stack.protocol import BaseMiddleware, SupportsMiddlewareDescriptor
from langchain_middleware_stack.stack import MiddlewareStack
from langchain_middleware_stack.errors import MiddlewareResolutionError


class _ConcreteMiddleware(BaseMiddleware):
    slug: ClassVar[str] = "concrete"


def test_base_middleware_defaults() -> None:
    m = _ConcreteMiddleware()
    assert m.slug == "concrete"
    assert m.after == ()
    assert m.before == ()
    assert m.wires == {}


def test_base_middleware_subclass_can_override_constraints() -> None:
    class _MW(BaseMiddleware):
        slug: ClassVar[str] = "mw"
        after: ClassVar[tuple[str, ...]] = ("other",)
        before: ClassVar[tuple[str, ...]] = ("third",)
        wires: ClassVar[dict[str, tuple[str, str]]] = {"_fn": ("other", "fn")}

    m = _MW()
    assert m.after == ("other",)
    assert m.before == ("third",)
    assert m.wires == {"_fn": ("other", "fn")}


def test_subclass_wires_does_not_mutate_base_default() -> None:
    class _A(BaseMiddleware):
        slug: ClassVar[str] = "a"
        wires: ClassVar[dict[str, tuple[str, str]]] = {"_x": ("b", "x")}

    class _B(BaseMiddleware):
        slug: ClassVar[str] = "b"

    assert _B.wires == {}
    assert _A.wires == {"_x": ("b", "x")}


def test_duck_typed_object_accepted_by_stack() -> None:
    """MiddlewareStack accepts any object with a slug — no inheritance required."""
    class _Duck:
        slug: ClassVar[str] = "duck"
        after: ClassVar[tuple[str, ...]] = ()
        before: ClassVar[tuple[str, ...]] = ()

    result = MiddlewareStack().add(_Duck()).resolve()
    assert len(result) == 1
    assert result[0].slug == "duck"  # type: ignore[attr-defined]


def test_object_without_slug_rejected_by_stack() -> None:
    """MiddlewareStack.add() raises MiddlewareResolutionError when slug is missing."""
    class _NoSlug:
        pass

    with pytest.raises(MiddlewareResolutionError, match="slug"):
        MiddlewareStack().add(_NoSlug())  # type: ignore[arg-type]


def test_protocol_exported_from_module() -> None:
    """Ensure SupportsMiddlewareDescriptor is importable (public API check)."""
    assert SupportsMiddlewareDescriptor is not None
