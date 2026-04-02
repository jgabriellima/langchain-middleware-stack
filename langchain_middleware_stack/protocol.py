# langchain_middleware_stack/protocol.py
"""Middleware descriptor Protocol and BaseMiddleware mixin."""

from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

__all__ = ["BaseMiddleware", "SupportsMiddlewareDescriptor"]


@runtime_checkable
class SupportsMiddlewareDescriptor(Protocol):
    """Structural Protocol for middleware that participates in MiddlewareStack.

    A conforming middleware is any class that declares all four attributes as
    class-level attributes. Inheritance from this Protocol is not required.

    **isinstance() caveat:** Python < 3.12 isinstance() checks against
    @runtime_checkable Protocol only verify callable members, not non-callable
    ClassVar attributes. Use this Protocol for static type checking (mypy/pyright)
    only. MiddlewareStack enforces the runtime contract via getattr, not isinstance.

    LangChain's ``AgentMiddleware`` base class alone does NOT conform — a subclass
    that declares ``slug``, ``after``, ``before``, and ``wires`` does.

    Attributes:
        slug: Stable, unique identifier (lowercase, alphanumeric + hyphens).
        after: Slugs this middleware must be positioned after.
        before: Slugs this middleware must be positioned before.
        wires: Maps local attribute name to (source_slug, source_attribute).
    """

    slug: ClassVar[str]
    after: ClassVar[tuple[str, ...]]
    before: ClassVar[tuple[str, ...]]
    wires: ClassVar[dict[str, tuple[str, str]]]


class BaseMiddleware:
    """Optional mixin-style base providing safe defaults for all descriptor fields.

    Subclasses must declare ``slug``. All other fields default to empty
    collections and are safe to use without override.

    **wires safety:** Subclasses that declare ``wires`` must assign a new dict
    literal at the class body level. Never mutate ``BaseMiddleware.wires`` or
    any inherited class default dict at runtime. ``MiddlewareStack`` reads
    ``wires`` via ``getattr`` and never mutates it.

    This class has no ``__init__`` requirements and is MRO-safe as a mixin
    alongside other base classes (e.g. LangChain's ``AgentMiddleware``).
    """

    slug: ClassVar[str]
    after: ClassVar[tuple[str, ...]] = ()
    before: ClassVar[tuple[str, ...]] = ()
    wires: ClassVar[dict[str, tuple[str, str]]] = {}
