"""The physical system: which components exist and how they are connected.

A :class:`PhysicalSystem` (``otwin.System`` for short) is a graph. Its nodes
are components, its edges are connections between their ports. It holds no
equations and computes nothing: it is the description an engineer writes, and
it is what :func:`otwin.compile` reads.

::

    >>> from otwin import System
    >>> from otwin.components.mechanical import Mass, Spring, Damper, Fixed
    >>> m, k, c, wall = Mass(1.0), Spring(20.0), Damper(0.3), Fixed()
    >>> s = System(m, k, c, wall, name="oscillator")
    >>> _ = s.connect(m.flange, k.a, c.a)
    >>> _ = s.connect(k.b, c.b, wall.port)
    >>> len(s.components), len(s.connections), sorted(s.domains)
    (4, 2, ['mechanical'])

Everything the system knows can be inspected before compiling:
:attr:`components`, :attr:`connections`, :attr:`ports`, :attr:`parameters`,
:attr:`domains`, and :meth:`summary` for a readable listing.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .components.base import Component, Composite, Connection, Ground, Parameter, Port

__all__ = ["PhysicalSystem", "System", "chain", "ConnectionError_"]


class ConnectionError_(ValueError):
    """A connection that cannot be made: a domain mismatch, a port joined
    twice, a component the system does not know."""


class PhysicalSystem:
    """Components plus the connections between their ports.

    Build it with :meth:`add` and :meth:`connect`, or with ``>>`` for a
    series chain. Then ``otwin.compile(system)``.
    """

    def __init__(self, *components: Component, name: str = "system") -> None:
        self.name = name
        self.components: list[Component] = []
        self.connections: list[Connection] = []
        self._names: set[str] = set()
        self.add(*components)

    # ---------------------------------------------------------------- build
    def add(self, *components: Component) -> PhysicalSystem:
        """Add components. Names must be unique within the system."""
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

    def connect(self, *ports: Port) -> PhysicalSystem:
        """Join ports into one node. Components are added if not yet present.

        Ports must share a domain; a reference (``Ground``, ``Fixed``,
        ``Atmosphere``) fits any domain. To couple two domains use a
        ``Transformer`` or a ``Gyrator``, not a connection.
        """
        for t in ports:
            if not isinstance(t, Port):
                raise TypeError(f"connect expects ports such as resistor.p, got {t!r}")
        try:
            connection = Connection(*ports)
        except ValueError as exc:
            raise ConnectionError_(str(exc)) from None
        for t in ports:
            if t.component not in self.components:
                self.add(t.component)
        self.connections.append(connection)
        return self

    def ground(self, *ports: Port) -> PhysicalSystem:
        """Connect ports to a new reference (ground, fixed frame, atmosphere)."""
        g = Ground()
        self.add(g)
        return self.connect(g.port, *ports)

    # -------------------------------------------------------------- inspect
    @property
    def ports(self) -> list[Port]:
        """Every port of every component, connected or not."""
        return [p for c in self.components for p in c.ports.values()]

    @property
    def parameters(self) -> dict[str, Parameter]:
        """``{"<component>.<parameter>": Parameter}`` over the flattened system."""
        comps, _ = self.flattened()
        return {f"{c.name}.{n}": p for c in comps for n, p in c.parameters.items()}

    @property
    def domains(self) -> set[str]:
        """The physical domains present (references excluded)."""
        return {p.domain for p in self.ports if p.domain != "any"}

    def unconnected(self) -> list[Port]:
        """Ports that appear in no connection. Two-port elements need all theirs."""
        used = {p for conn in self.connections for p in conn}
        return [p for p in self.ports if p not in used]

    def flattened(self) -> tuple[list[Component], list[Connection]]:
        """Expand composites into their parts. Returns (components, connections)."""
        comps: list[Component] = []
        links: list[Connection] = list(self.connections)
        alias: dict[Port, Port] = {}

        def visit(c: Component) -> None:
            if isinstance(c, Composite):
                for t, inner in c.aliases.items():
                    alias[t] = inner
                for part in c.parts:
                    visit(part)
                links.extend(c.connections)
            else:
                comps.append(c)

        for c in self.components:
            visit(c)

        def resolve(t: Port) -> Port:
            seen = 0
            while t in alias:
                t = alias[t]
                seen += 1
                if seen > 100:
                    raise ConnectionError_("circular port alias")
            return t

        resolved = [Connection(*(resolve(t) for t in link)) for link in links]
        return comps, resolved

    def summary(self) -> str:
        """A readable listing: components with parameters, then connections."""
        lines = [
            f"{self.name}: {len(self.components)} components, "
            f"{len(self.connections)} connections, domains {sorted(self.domains)}"
        ]
        for c in self.components:
            params = ", ".join(
                f"{n}={p.value:g} {p.unit}".rstrip() for n, p in c.parameters.items()
            )
            ports = ", ".join(c.ports)
            lines.append(
                f"  {c.name} ({type(c).__name__}) ports: {ports}"
                + (f"; {params}" if params else "")
            )
        for conn in self.connections:
            lines.append("  " + " = ".join(p.qualified for p in conn))
        loose = self.unconnected()
        if loose:
            lines.append("  unconnected: " + ", ".join(p.qualified for p in loose))
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"System({self.name!r}, {len(self.components)} components, "
            f"{len(self.connections)} connections)"
        )

    def __rshift__(self, other: Any) -> Any:
        return chain(self, other)


System = PhysicalSystem


def chain(*items: Any, name: str = "system") -> PhysicalSystem:
    """Connect two-port components in series: ``a >> b >> c``.

    Each component must expose a pair of ports ``(p, n)`` or ``(a, b)``.
    The chain is left open; close it with ``system.connect``.
    """
    system = PhysicalSystem(name=name)
    prev_out: Port | None = None
    for item in items:
        if isinstance(item, PhysicalSystem):
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


def _series_pair(c: Component) -> tuple[Port, Port]:
    for a, b in (("p", "n"), ("a", "b")):
        if a in c.ports and b in c.ports:
            return c.ports[a], c.ports[b]
    raise ConnectionError_(
        f"{c.name} is not a two-port component; connect it with System.connect"
    )


def _iter_ports(conns: Iterable[Connection]) -> Iterable[Port]:
    for c in conns:
        yield from c
