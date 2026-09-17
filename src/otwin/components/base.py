"""The three things an engineer works with: components, ports, connections.

**Component.** A piece of equipment, or a piece of one: a resistor, a mass, a
tank, a battery. It has *ports* to connect it to others, *parameters* with
units, and a small amount of physics inside, declared as *branches*. You never
write differential equations in a component.

**Port.** A point where a component can be connected. Every port belongs to
one physical domain and carries two quantities: an *across* variable that is
shared when ports are joined (voltage, velocity, pressure, temperature) and a
*through* variable that flows in or out (current, force, flow, heat).

**Connection.** Two or more ports of the same domain joined together. That is
all a connection means: the across variables become equal and the through
variables add up to zero at the joint. The compiler turns connections into
equations; you do not.

**Branch.** The physics inside a component, one relation between two ports (or
one port and the reference): a storage, a resistor, a source or one half of a
two-port. The compiler reads branches and nothing else about a component, so
nothing written here runs inside the numerical loop.

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

The across variable is shared by every port joined into a node; the
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
    "Port",
    "Connection",
    "Parameter",
    "Branch",
    "StorageBranch",
    "ResistorBranch",
    "SourceBranch",
    "TwoPortBranch",
    "HeatBranch",
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


class Port:
    """A point where a component can be connected.

    Attributes:
        component: the component the port belongs to.
        name: the port's name on that component (``p``, ``flange``, ``port``).
        domain: ``"electrical"``, ``"mechanical"``, ``"rotational"``,
            ``"hydraulic"``, ``"thermal"``, or ``"any"`` for a reference.

    A port carries an across variable and a through variable, named by its
    domain (see :data:`DOMAINS`). Joining ports in a :class:`Connection` makes
    their across variables equal and their through variables sum to zero.
    """

    __slots__ = ("component", "name", "domain")

    def __init__(self, component: Component, name: str, domain: str) -> None:
        self.component = component
        self.name = name
        self.domain = domain

    @property
    def qualified(self) -> str:
        """``<component>.<port>``, the name used in messages and outputs."""
        return f"{self.component.name}.{self.name}"

    @property
    def across(self) -> str:
        """Name of the across variable this port carries, e.g. ``voltage``."""
        return DOMAINS[self.domain].across if self.domain in DOMAINS else "across"

    @property
    def through(self) -> str:
        """Name of the through variable this port carries, e.g. ``current``."""
        return DOMAINS[self.domain].through if self.domain in DOMAINS else "through"

    def __repr__(self) -> str:
        return f"<{self.domain} port {self.qualified}>"


class Connection:
    """Two or more ports joined into one node.

    Ports in a connection must share a domain (a reference port fits any).
    At the node the across variables are equal and the through variables sum
    to zero. A connection holds no numbers and does no computation; the
    compiler reads it.

    Iterating a connection yields its ports, so it can be used wherever a
    tuple of ports was expected.
    """

    __slots__ = ("ports",)

    def __init__(self, *ports: Port) -> None:
        if len(ports) < 2:
            raise ValueError("a connection joins at least two ports")
        for p in ports:
            if not isinstance(p, Port):
                raise TypeError(f"connections are made of ports, got {p!r}")
        domains = {p.domain for p in ports if p.domain != "any"}
        if len(domains) > 1:
            names = ", ".join(f"{p.qualified} [{p.domain}]" for p in ports)
            raise ValueError(
                f"incompatible connection: {names}. Ports of different domains "
                "cannot share a node; couple domains with a Transformer or a Gyrator."
            )
        self.ports: tuple[Port, ...] = tuple(ports)

    @property
    def domain(self) -> str:
        """The shared domain, or ``"any"`` if only references are joined."""
        for p in self.ports:
            if p.domain != "any":
                return p.domain
        return "any"

    def __iter__(self):
        return iter(self.ports)

    def __len__(self) -> int:
        return len(self.ports)

    def __getitem__(self, i):
        return self.ports[i]

    def __contains__(self, port: object) -> bool:
        return port in self.ports

    def __repr__(self) -> str:
        return "Connection(" + ", ".join(p.qualified for p in self.ports) + ")"


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
    a: Port
    b: Port | None
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
    """A dissipative element: ``through = law(across)``, or the other way
    round, ``across = inverse(through)``.

    The law is any traceable function. A linear law ``lambda v: g * v`` is the
    common case and the only one allowed where the across variable must be
    solved for algebraically (a node with no storage pinning it).

    ``inverse`` is for elements naturally written with the flow as the input:
    a pump curve ``dp = f(Q)``, turbulent friction ``dp = K Q |Q|``, Coulomb
    friction ``F = mu sign(v)``. Such a branch must sit in series with
    something that sets its flow: an inductor, spring or fluid inertance, a
    flow or current source, or another branch of the same kind. The compiler
    then reads the across off the flow instead of inverting the law. Give
    ``law`` too when it is available, so the element also works with its
    across pinned.
    """

    law: Law | None = field(default=lambda v: v)
    inverse: Law | None = None


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
    a2: Port | None = None
    b2: Port | None = None
    ratio: Expr = field(default_factory=lambda: ex.const(1.0))
    label2: str = ""


@dataclass(eq=False)
class HeatBranch(Branch):
    """Losses of other components delivered as heat into a thermal port.

    ``a`` is the thermal port that receives the heat, ``b`` the thermal
    reference (``None``). ``sources`` lists the components whose dissipated
    power (``across * through`` of their resistor branches) is summed and
    injected as heat flow. This is how a battery's ohmic losses warm its cell,
    or a motor's copper losses warm its housing.

    Heat generation is one-directional (electrical power becomes heat, never
    the reverse), so a model with a heat branch is reported as
    ``pseudo-port-hamiltonian``: the heat balance is exact, but temperature
    times heat flow is not a power and the energy audit spans two bookkeepings.
    """

    sources: list[Component] = field(default_factory=list)


class Component:
    """Base class of every physical primitive.

    Subclasses set ``domain`` and ``type_name``, declare ports and
    parameters in ``__init__`` with :meth:`port` and :meth:`param`, and
    return their constitutive relations from :meth:`branches`.

    ``series_ports`` names the (entry, exit) ports a chain ``a >> b >> c``
    passes through. Passive two-ports use their natural pair (``p, n``;
    ``a, b``; ``inlet, outlet``); sources set it the other way round so that
    the chain follows the flow they push out (``gnd >> supply >> load >> gnd``
    puts ``supply.p`` on the load side).
    """

    series_ports: tuple[str, str] | None = None

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
        self.ports: dict[str, Port] = {}
        self.parameters: dict[str, Parameter] = {}
        self.description: str = ""

    # ------------------------------------------------------------ declaration
    def add_port(self, name: str, domain: str | None = None) -> Port:
        """Declare a port. It becomes ``self.<name>`` and ``self.ports[name]``."""
        t = Port(self, name, domain or self.domain)
        self.ports[name] = t
        setattr(self, name, t)
        return t

    def add_parameter(
        self,
        name: str,
        value: float,
        unit: str,
        description: str = "",
        positive: bool = True,
        nonneg: bool = False,
    ) -> Expr:
        """Declare a parameter and return its symbol for use in laws.

        The symbol stays symbolic through compilation: the compiled model can
        change the value without recompiling and estimators can fit it.
        """
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
        """``a >> b``: a series chain. Installed by :mod:`otwin.system`, which
        owns :func:`~otwin.system.chain`; components never import the system
        module, so there is no import cycle."""
        raise TypeError("import otwin before chaining components with >>")


class ComponentQuantities:
    """What a component may reference when it declares extra outputs."""

    def __init__(self) -> None:
        self.across: dict[str, Expr] = {}
        self.through: dict[str, Expr] = {}
        self.state: dict[str, Expr] = {}
        self.params: dict[str, Expr] = {}


class Composite(Component):
    """A component built from other components: a motor, a battery, a pump.

    In ``__init__``, :meth:`add` the parts, :meth:`connect` their ports and
    :meth:`expose` the ports the outside should see. The compiler flattens a
    composite before anything else and names the parts ``<device>.<part>``,
    so their states and outputs are ordinary outputs of the model.
    """

    type_name = "composite"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.parts: list[Component] = []
        self.connections: list[Connection] = []
        self.aliases: dict[Port, Port] = {}

    def add(self, *parts: Component) -> None:
        """Take ownership of parts; they are renamed ``<self>.<part>``."""
        for p in parts:
            p.name = f"{self.name}.{p.name}"
            self.parts.append(p)

    def connect(self, *ports: Port) -> Connection:
        """Join ports of the parts, exactly like :meth:`System.connect`."""
        c = Connection(*ports)
        self.connections.append(c)
        return c

    @property
    def links(self) -> list[Connection]:
        return self.connections

    def expose(self, name: str, inner: Port) -> Port:
        t = self.add_port(name, inner.domain)
        self.aliases[t] = inner
        return t

    def branches(self) -> list[Branch]:
        return []


class Ground(Component):
    """The reference: across variable zero. Electrical ground, a fixed frame,
    atmospheric pressure, the temperature datum.

    One port, any domain. Connect anything to it that is nailed down.
    """

    type_name = "ground"
    domain = "any"

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("port", "any")

    def branches(self) -> list[Branch]:
        return []
