"""The component model: what a physical primitive declares.

A component declares terminals, parameters and *branches*. A branch is one
constitutive relation between two terminals (or one terminal and the
reference): a storage, a resistor, a source or one half of a two-port. The
compiler reads branches. It never reads a component's Python methods at
simulation time, so nothing here ends up in the numerical loop.

Every domain uses the same two variables:

==========  =====================  ================
domain      across                 through
==========  =====================  ================
electrical  voltage [V]            current [A]
mechanical  velocity [m/s]         force [N]
rotational  angular vel. [rad/s]   torque [N m]
hydraulic   pressure [Pa]          flow [m^3/s]
thermal     temperature [K]        heat flow [W]
==========  =====================  ================

The across variable is shared by every terminal joined into a node; the
through variables of the branches meeting there sum to zero. That single rule
is Kirchhoff's laws, Newton's third law, mass conservation at a pipe junction
and heat conservation at a wall, and it is what lets one compiler serve all
five domains.

Extending the library means subclassing :class:`Component` and returning
branches from :meth:`Component.branches`. See ``docs/developer/components.md``.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from .. import expr as ex
from ..expr import Expr

__all__ = [
    "Domain",
    "DOMAINS",
    "Terminal",
    "Parameter",
    "Branch",
    "StorageBranch",
    "ResistorBranch",
    "SourceBranch",
    "TwoPortBranch",
    "Component",
    "Composite",
    "Ground",
    "Law",
]


@dataclass(frozen=True)
class Domain:
    name: str
    across: str
    across_unit: str
    through: str
    through_unit: str
    power_conjugate: bool = True


DOMAINS: dict[str, Domain] = {
    "electrical": Domain("electrical", "voltage", "V", "current", "A"),
    "mechanical": Domain("mechanical", "velocity", "m/s", "force", "N"),
    "rotational": Domain("rotational", "angular_velocity", "rad/s", "torque", "N m"),
    "hydraulic": Domain("hydraulic", "pressure", "Pa", "flow", "m^3/s"),
    "thermal": Domain("thermal", "temperature", "K", "heat_flow", "W", False),
}


class Terminal:
    """A connection point on a component. Two terminals joined share an across
    variable; that is all a connection means."""

    __slots__ = ("component", "name", "domain")

    def __init__(self, component: Component, name: str, domain: str) -> None:
        self.component = component
        self.name = name
        self.domain = domain

    @property
    def qualified(self) -> str:
        return f"{self.component.name}.{self.name}"

    def __repr__(self) -> str:
        return f"<{self.domain} terminal {self.qualified}>"


@dataclass
class Parameter:
    name: str
    value: float
    unit: str
    description: str = ""
    positive: bool = True
    nonneg: bool = False

    def validate(self, owner: str) -> None:
        v = self.value
        if math.isnan(v):
            raise ValueError(f"{owner}.{self.name} is NaN")
        if self.positive and not v > 0:
            raise ValueError(
                f"{owner}.{self.name} must be positive, got {v} {self.unit}".rstrip()
            )
        if self.nonneg and v < 0:
            raise ValueError(
                f"{owner}.{self.name} must not be negative, got {v} {self.unit}".rstrip()
            )


Law = Callable[[Expr], Expr]


@dataclass(eq=False)
class Branch:
    """Base of every constitutive relation. ``b is None`` means the reference."""

    component: Component
    a: Terminal
    b: Terminal | None
    label: str = ""

    @property
    def domain(self) -> str:
        return self.a.domain

    @property
    def name(self) -> str:
        return self.label or self.component.name


@dataclass(eq=False)
class StorageBranch(Branch):
    """An energy store.

    ``kind == "across"``: the state is the integral of the through variable
    and the across variable is ``dH/dx`` (capacitor, mass, tank, thermal mass).

    ``kind == "through"``: the state is the integral of the across variable and
    the through variable is ``dH/dx`` (inductor, spring, fluid inertance).
    """

    kind: str = "across"
    state: str = "x"
    state_unit: str = ""
    quantity: str = ""
    initial: float = 0.0
    energy: Callable[[Expr], Expr] = field(default=lambda x: x)


@dataclass(eq=False)
class ResistorBranch(Branch):
    """A dissipative element: ``through = law(across)``.

    The law is any traceable function. A linear law ``lambda v: g * v`` is the
    common case and the only one allowed where the across variable must be
    solved for algebraically (a node with no storage pinning it).
    """

    law: Law = field(default=lambda v: v)


@dataclass(eq=False)
class SourceBranch(Branch):
    """An across source (voltage, pressure, temperature, imposed velocity) or a
    through source (current, force, flow, heat).

    ``value is None`` makes the source an input of the compiled model; a number
    makes it a constant parameter that can still be changed later.
    """

    kind: str = "across"
    value: float | None = None
    unit: str = ""
    quantity: str = ""


@dataclass(eq=False)
class TwoPortBranch(Branch):
    """A lossless two-port between branch 1 ``(a, b)`` and branch 2 ``(a2, b2)``.

    transformer: ``across_2 = ratio * across_1``, ``through_1 = -ratio * through_2``
    gyrator:     ``across_2 = ratio * through_1``, ``across_1 = -ratio * through_2``

    Both conserve power: ``across_1 through_1 + across_2 through_2 = 0``.
    """

    kind: str = "transformer"
    a2: Terminal | None = None
    b2: Terminal | None = None
    ratio: Expr = field(default_factory=lambda: ex.const(1.0))
    label2: str = ""


class Component:
    """Base class of every physical primitive.

    Subclasses set ``domain`` and ``type_name``, declare terminals and
    parameters in ``__init__`` with :meth:`terminal` and :meth:`param`, and
    return their constitutive relations from :meth:`branches`.
    """

    domain: ClassVar[str] = ""
    type_name: ClassVar[str] = "component"
    _counters: ClassVar[dict[str, itertools.count]] = {}

    def __init__(self, name: str | None = None) -> None:
        if name is None:
            counter = Component._counters.setdefault(self.type_name, itertools.count(1))
            name = f"{self.type_name}_{next(counter)}"
        if not isinstance(name, str) or not name or "." in name or ":" in name:
            raise ValueError(
                f"component name must be a non-empty string without '.' or ':', got {name!r}"
            )
        self.name = name
        self.terminals: dict[str, Terminal] = {}
        self.parameters: dict[str, Parameter] = {}
        self.description: str = ""

    # ------------------------------------------------------------ declaration
    def terminal(self, name: str, domain: str | None = None) -> Terminal:
        t = Terminal(self, name, domain or self.domain)
        self.terminals[name] = t
        setattr(self, name, t)
        return t

    def param(
        self,
        name: str,
        value: float,
        unit: str,
        description: str = "",
        positive: bool = True,
        nonneg: bool = False,
    ) -> Expr:
        """Declare a parameter and return its symbol for use in laws."""
        p = Parameter(name, float(value), unit, description, positive, nonneg)
        p.validate(self.name)
        self.parameters[name] = p
        return self.symbol(name)

    def symbol(self, name: str) -> Expr:
        """The symbol of a parameter, stable under renaming (composites rename
        their parts). The compiler maps it to ``<component>.<name>``."""
        return ex.symbol("param", f"{self.uid}.{name}")

    @property
    def uid(self) -> str:
        return f"#{id(self)}"

    def value(self, name: str) -> float:
        return self.parameters[name].value

    # ---------------------------------------------------------------- output
    def branches(self) -> list[Branch]:
        raise NotImplementedError

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """Named outputs beyond the across/through of each branch.

        ``q`` gives the compiled across, through and state expressions of this
        component's branches by label. Return ``{name: (unit, expr)}``.
        """
        return {}

    def __repr__(self) -> str:
        params = ", ".join(f"{k}={p.value:g}" for k, p in self.parameters.items())
        return f"{type(self).__name__}({self.name}{', ' if params else ''}{params})"

    def __rshift__(self, other: Any) -> Any:
        from ..system import chain

        return chain(self, other)


class ComponentQuantities:
    """What a component may reference when it declares extra outputs."""

    def __init__(self) -> None:
        self.across: dict[str, Expr] = {}
        self.through: dict[str, Expr] = {}
        self.state: dict[str, Expr] = {}
        self.params: dict[str, Expr] = {}


class Composite(Component):
    """A component assembled from other components.

    Subclasses build ``self.parts`` and ``self.links`` (lists of terminals to
    join) in ``__init__`` and expose inner terminals with :meth:`expose`.
    The compiler flattens composites before it does anything else.
    """

    type_name = "composite"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.parts: list[Component] = []
        self.links: list[tuple[Terminal, ...]] = []
        self.aliases: dict[Terminal, Terminal] = {}

    def add(self, *parts: Component) -> None:
        for p in parts:
            p.name = f"{self.name}.{p.name}"
            self.parts.append(p)

    def link(self, *terminals: Terminal) -> None:
        self.links.append(tuple(terminals))

    def expose(self, name: str, inner: Terminal) -> Terminal:
        t = self.terminal(name, inner.domain)
        self.aliases[t] = inner
        return t

    def branches(self) -> list[Branch]:
        return []


class Ground(Component):
    """The reference: across variable zero. Electrical ground, a fixed frame,
    atmospheric pressure, the temperature datum.

    One terminal, any domain. Connect anything to it that is nailed down.
    """

    type_name = "ground"
    domain = "any"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("terminal", "any")

    def branches(self) -> list[Branch]:
        return []
