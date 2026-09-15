"""The component graph: what exists and how it is connected.

A :class:`System` holds components and connections. A connection joins two or
more terminals into one node, where they share an across variable (voltage,
velocity, pressure, temperature) and their through variables sum to zero.
Nothing is computed here. Compilation happens in :func:`otwin.compile`.

::

    >>> from otwin import System
    >>> from otwin.components.mechanical import Mass, Spring, Damper, Fixed
    >>> m, k, c, wall = Mass(1.0), Spring(20.0), Damper(0.3), Fixed()
    >>> s = System(m, k, c, wall, name="oscillator")
    >>> _ = s.connect(m.flange, k.a, c.a)
    >>> _ = s.connect(k.b, c.b, wall.terminal)
    >>> len(s.components), len(s.connections)
    (4, 2)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .components.base import Component, Composite, Ground, Terminal

__all__ = ["System", "chain", "ConnectionError_"]


class ConnectionError_(ValueError):
    """A connection that cannot be made: a domain mismatch, a terminal joined
    twice, a component the system does not know."""


class System:
    """A set of components and the connections between their terminals."""

    def __init__(self, *components: Component, name: str = "system") -> None:
        self.name = name
        self.components: list[Component] = []
        self.connections: list[tuple[Terminal, ...]] = []
        self._names: set[str] = set()
        self.add(*components)

    # ---------------------------------------------------------------- build
    def add(self, *components: Component) -> System:
        for c in components:
            if not isinstance(c, Component):
                raise TypeError(f"System.add expects components, got {type(c).__name__}")
            if c in self.components:
                continue
            if c.name in self._names:
                raise ConnectionError_(
                    f"two components are named {c.name!r}; give one of them a name="
                )
            self._names.add(c.name)
            self.components.append(c)
        return self

    def connect(self, *terminals: Terminal) -> System:
        """Join terminals into one node. Components are added if not yet present."""
        if len(terminals) < 2:
            raise ConnectionError_("connect needs at least two terminals")
        for t in terminals:
            if not isinstance(t, Terminal):
                raise TypeError(
                    f"connect expects terminals such as resistor.p, got {t!r}"
                )
            if t.component not in self.components:
                self.add(t.component)
        domains = {t.domain for t in terminals if t.domain != "any"}
        if len(domains) > 1:
            names = ", ".join(f"{t.qualified} [{t.domain}]" for t in terminals)
            raise ConnectionError_(
                f"incompatible connection: {names}. Terminals of different domains "
                "cannot share a node; couple domains with a Transformer or a Gyrator."
            )
        self.connections.append(tuple(terminals))
        return self

    def ground(self, *terminals: Terminal) -> System:
        """Connect terminals to a new reference (ground, fixed frame, atmosphere)."""
        g = Ground()
        self.add(g)
        return self.connect(g.terminal, *terminals)

    # -------------------------------------------------------------- inspect
    def flattened(self) -> tuple[list[Component], list[tuple[Terminal, ...]]]:
        """Expand composites into their parts. Returns (components, connections)."""
        comps: list[Component] = []
        links: list[tuple[Terminal, ...]] = list(self.connections)
        alias: dict[Terminal, Terminal] = {}

        def visit(c: Component) -> None:
            if isinstance(c, Composite):
                for t, inner in c.aliases.items():
                    alias[t] = inner
                for part in c.parts:
                    visit(part)
                links.extend(c.links)
            else:
                comps.append(c)

        for c in self.components:
            visit(c)

        def resolve(t: Terminal) -> Terminal:
            seen = 0
            while t in alias:
                t = alias[t]
                seen += 1
                if seen > 100:
                    raise ConnectionError_("circular terminal alias")
            return t

        resolved = [tuple(resolve(t) for t in link) for link in links]
        return comps, resolved

    def terminals(self) -> Iterable[Terminal]:
        for c in self.components:
            yield from c.terminals.values()

    def __repr__(self) -> str:
        return (
            f"System({self.name!r}, {len(self.components)} components, "
            f"{len(self.connections)} connections)"
        )

    def __rshift__(self, other: Any) -> Any:
        return chain(self, other)


def chain(*items: Any, name: str = "system") -> System:
    """Connect two-terminal components in series: ``a >> b >> c``.

    Each component must expose a pair of terminals ``(p, n)`` or ``(a, b)``.
    The chain is left open; close it with ``system.connect``.
    """
    system = System(name=name)
    prev_out: Terminal | None = None
    for item in items:
        if isinstance(item, System):
            system.add(*item.components)
            system.connections.extend(item.connections)
            if item.components:
                tail = _series_pair(item.components[-1])
                if prev_out is not None:
                    system.connect(prev_out, _series_pair(item.components[0])[0])
                prev_out = tail[1]
            continue
        if not isinstance(item, Component):
            raise TypeError(
                f"chain expects components or systems, got {type(item).__name__}"
            )
        system.add(item)
        pair = _series_pair(item)
        if prev_out is not None:
            system.connect(prev_out, pair[0])
        prev_out = pair[1]
    return system


def _series_pair(c: Component) -> tuple[Terminal, Terminal]:
    for a, b in (("p", "n"), ("a", "b")):
        if a in c.terminals and b in c.terminals:
            return c.terminals[a], c.terminals[b]
    raise ConnectionError_(
        f"{c.name} is not a two-terminal component; connect it with System.connect"
    )
