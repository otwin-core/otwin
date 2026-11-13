"""Chemistry: species, reactions and reactors, in the chemical domain.

The across variable of a chemical port is the concentration [mol/m^3], the
through variable a molar flow [mol/s]. A :class:`Species` is an across
storage whose state is the amount ``n`` [mol] in a volume ``V``, so the
concentration at its port is ``n / V``. A :class:`Reaction` draws from and
delivers to species ports at the mass-action rate of its reactants, through
one-way rate branches. The compiler writes one mass balance per species node.
Nothing here writes a differential equation.

What this module covers, each checked against a closed form in the tests:
first- and second-order kinetics with any stoichiometry, consecutive
reactions, dosing, an accumulated quantity, the mixed reactor with inflow and
outflow, and the plug-flow reactor approximated by mixed tanks in series.
Isothermal only: temperature, a reaction enthalpy and a spatial (PDE) plug
flow reactor are on the roadmap.

Three things to know:

* **Concentration is not a thermodynamic potential.** The energy a species
  stores is ``n^2 / 2V``, a bookkeeping device, not a Gibbs energy. The
  compiled model is ``pseudo-port-hamiltonian``: the mass balances are exact,
  and the energy audit is not a first-law statement. Do not read it as one.
* **Use ``solver="patankar"``.** It keeps every amount non-negative and
  every mass balance exact for any step size, which the general integrators
  do not: Euler goes negative at ``k dt > 1`` and the implicit midpoint at
  ``k dt > 2``, and because the storage function is even in ``n`` the energy
  audit does not notice. It is first order; a tenth of the fastest time
  constant gives about one per cent. The concentration a reaction sees is
  also clamped at ``max(n, 0) / V``, so with another solver an overshoot
  stops reacting rather than reversing.
* **Flows are one-way.** An :class:`Outflow` carries a species downstream at
  ``Q c_upstream``; nothing downstream affects it. A reactor's ``out_<s>``
  port must end somewhere: the next reactor, an :class:`Accumulator`, or a
  :class:`~otwin.components.base.Ground`.

Units: mol, m^3, s. A first-order rate constant is in 1/s, a second-order one
in m^3/(mol s).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from .. import expr as ex
from ..expr import Expr
from .base import (
    Branch,
    Component,
    ComponentQuantities,
    Composite,
    Parameter,
    RateBranch,
    SourceBranch,
    StorageBranch,
)

__all__ = [
    "Species",
    "Reaction",
    "Dose",
    "Outflow",
    "Accumulator",
    "MixedReactor",
    "TanksInSeries",
]

Concentrations = Mapping[str, Expr]


def _check_species_name(name: str, owner: str) -> None:
    """A species name becomes a port, so it must be a plain identifier."""
    if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
        raise ValueError(
            f"{owner}: species name {name!r} must be a plain identifier (letters, digits, "
            "underscores, not starting with an underscore), because it names a port"
        )


class Species(Component):
    """An amount of one species in a well-mixed volume.

    State: the amount ``n`` [mol]. The concentration at the port is
    ``max(n, 0) / volume``: clamped at zero, so an overshoot below empty (only
    possible with a solver other than ``patankar``) cannot drive a negative
    reaction rate. Extra output: ``concentration`` [mol/m^3], unclamped, so a
    negative amount is visible if a step produced one.

    Args:
        volume: The volume the species is dissolved in [m^3].
        concentration: Initial concentration [mol/m^3].
    """

    domain = "chemical"
    type_name = "species"

    def __init__(
        self,
        volume: float = 1.0,
        *,
        concentration: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("port")
        self.V = self.add_parameter("volume", volume, "m^3", "volume of the mixture")
        if concentration < 0:
            raise ValueError(f"{self.name}: concentration must not be negative")
        self.initial_concentration = float(concentration)

    def branches(self) -> list[Branch]:
        """One across storage against the reference, state ``amount`` (mol):
        ``c = max(n, 0) / V``, storage function ``max(n, 0)^2 / 2V``."""
        return [
            StorageBranch(
                self,
                self.port,
                None,
                kind="across",
                state="amount",
                state_unit="mol",
                quantity="amount of substance",
                initial=self.initial_concentration * self.value("volume"),
                energy=lambda n: ex.maximum(n, 0.0) ** 2 / (2 * self.V),
            )
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``concentration`` (mol/m^3): the amount over the volume, unclamped."""
        return {"concentration": ("mol/m^3", q.state["amount"] / self.V)}


def _rate_unit(total_order: float) -> str:
    """The unit of a mass-action rate constant for a given total order."""
    if total_order == 1:
        return "1/s"
    if total_order == 2:
        return "m^3/(mol s)"
    return f"(m^3/mol)^{total_order - 1:g}/s"


class Reaction(Component):
    """A reaction among species, at a mass-action rate.

    One port per species named in ``stoichiometry``, to be connected to that
    species' port (a :class:`MixedReactor` does this for you). Negative
    coefficients are reactants, positive ones products. The molar rate is

        ``R = k * volume * prod(c_s ** order_s)``

    and species ``s`` changes at ``nu_s * R``. By default the reaction is
    elementary: ``order_s = -nu_s`` for every reactant. ``A -> B`` is first
    order, ``A + B -> P`` second order, ``2A -> P`` second order in ``A``.

    Args:
        stoichiometry: ``{species: coefficient}``, at least one reactant.
        rate_constant: ``k``, in 1/s for a first-order reaction and
            m^3/(mol s) for a second-order one. A parameter, so it can be fitted.
        order: Override the reaction order per species, e.g. ``{"A": 1}`` for
            a reaction that is first order in ``A`` whatever its coefficient.
        volume: The volume the reaction happens in [m^3]. A
            :class:`MixedReactor` sets it to its own.
        rate: A custom law instead of mass action: ``rate(c, k)`` with ``c``
            the concentrations by species name and ``k`` the rate constant,
            returning the rate per unit volume [mol/(m^3 s)] as an expression
            built with :mod:`otwin.expr`.

    Extra output: ``rate`` [mol/s], the molar rate ``R``.
    """

    domain = "chemical"
    type_name = "reaction"

    def __init__(
        self,
        stoichiometry: Mapping[str, float] | None = None,
        rate_constant: float = 1.0,
        *,
        order: Mapping[str, float] | None = None,
        volume: float = 1.0,
        rate: Callable[[Concentrations, Expr], Expr] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        stoich = dict(
            stoichiometry if stoichiometry is not None else {"A": -1.0, "B": 1.0}
        )
        if not stoich:
            raise ValueError(f"{self.name}: a reaction needs at least one species")
        for s, nu in stoich.items():
            _check_species_name(s, self.name)
            if hasattr(self, s):
                raise ValueError(f"{self.name}: {s!r} cannot be a species name here")
            if not nu:
                raise ValueError(f"{self.name}: species {s!r} has coefficient 0")
        reactants = {s: -nu for s, nu in stoich.items() if nu < 0}
        if not reactants and rate is None:
            raise ValueError(
                f"{self.name}: no reactant (negative coefficient); mass action needs one"
            )
        self.stoichiometry = {s: float(nu) for s, nu in stoich.items()}
        self.order = {
            s: float(o) for s, o in (order if order is not None else reactants).items()
        }
        unknown = set(self.order) - set(self.stoichiometry)
        if unknown:
            raise ValueError(
                f"{self.name}: order names species not in the reaction: {sorted(unknown)}"
            )
        for s in self.stoichiometry:
            self.add_port(s)
        total = sum(self.order.values())
        self.k = self.add_parameter(
            "k", rate_constant, _rate_unit(total), "rate constant, mass action"
        )
        self.V = self.add_parameter(
            "volume", volume, "m^3", "volume the reaction happens in"
        )
        self._rate = rate

    def clone(self, name: str | None = None) -> Reaction:
        """A new, independent reaction with the same stoichiometry, order, rate
        constant, volume and law. A component belongs to one place in a
        system; a reactor that needs the same reaction again clones it."""
        return Reaction(
            self.stoichiometry,
            self.parameters["k"].value,
            order=self.order,
            volume=self.parameters["volume"].value,
            rate=self._rate,
            name=name or self.name,
        )

    def set_volume(self, volume: float) -> None:
        """Change the reaction volume. A reactor does this when it takes the reaction in."""
        self.parameters["volume"] = Parameter(
            "volume", float(volume), "m^3", "volume the reaction happens in"
        )
        self.parameters["volume"].validate(self.name)

    def molar_rate(self, c: Concentrations) -> Expr:
        """``R`` [mol/s] from the concentrations at the ports."""
        if self._rate is not None:
            return self.V * ex.as_expr(self._rate(c, self.k))
        r: Expr = self.k * self.V
        for s, o in self.order.items():
            cs = c[s]
            r = r * (cs if o == 1 else cs * cs if o == 2 else cs**o)
        return r

    def branches(self) -> list[Branch]:
        """One rate branch per species, port to reference, carrying
        ``-nu_s * R`` out of the node, so the species changes at ``nu_s * R``."""
        return [
            RateBranch(
                self,
                self.ports[s],
                None,
                label=f"{self.name}.{s}",
                rate=(lambda c, nu=nu: -nu * self.molar_rate(c)),
            )
            for s, nu in self.stoichiometry.items()
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``rate`` (mol/s): the molar rate of the reaction."""
        c = {s: q.across[f"{self.name}.{s}"] for s in self.stoichiometry}
        return {"rate": ("mol/s", self.molar_rate(c))}


class Dose(Component):
    """A molar flow of one species into a port: a feed, a dosing pump.

    ``rate=None`` makes it an input of the compiled model, named after the
    component, in mol/s. A number makes it a constant.
    """

    domain = "chemical"
    type_name = "dose"

    def __init__(self, rate: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("port")
        self.rate = None if rate is None else float(rate)

    def branches(self) -> list[Branch]:
        """One through source delivering the molar flow at ``port``."""
        return [
            SourceBranch(
                self,
                self.port,
                None,
                kind="through",
                value=self.rate,
                unit="mol/s",
                quantity="molar_flow",
            )
        ]


class Outflow(Component):
    """The liquid leaving a volume carries a species with it: ``Q c_a`` from ``a`` to ``b``.

    One-way: the concentration at ``b`` does not enter. ``b`` must be
    connected to something that takes the flow, such as the next reactor's
    inlet, an :class:`Accumulator` or a :class:`~otwin.components.base.Ground`.
    """

    domain = "chemical"
    type_name = "outflow"
    series_ports = ("a", "b")

    def __init__(self, flow: float = 1.0, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.Q = self.add_parameter(
            "flow", flow, "m^3/s", "volumetric flow carrying the species"
        )

    def branches(self) -> list[Branch]:
        """One rate branch ``a`` to ``b`` with rate ``Q c_a``."""
        return [RateBranch(self, self.a, self.b, rate=lambda c: self.Q * c["a"])]


class Accumulator(Component):
    """The amount of a species that has flowed into it: the integral of a molar flow.

    It holds its port at zero concentration (it is a sink) and counts what
    arrives. State: ``amount`` [mol]. Put one on the outlet of a reactor to
    get the cumulative discharge; connect a :class:`Dose` to one to integrate
    a dosing schedule.
    """

    domain = "chemical"
    type_name = "accumulator"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("port")

    def branches(self) -> list[Branch]:
        """One across storage with zero storage function: the port sits at
        concentration zero and the state integrates the incoming flow."""
        return [
            StorageBranch(
                self,
                self.port,
                None,
                kind="across",
                state="amount",
                state_unit="mol",
                quantity="accumulated amount",
                initial=0.0,
                energy=lambda n: 0.0 * n,
            )
        ]


class MixedReactor(Composite):
    """A continuously stirred tank: species in one volume, reactions among
    them, and a liquid flow that carries every species out.

    Ports: ``in_<species>`` (connect a :class:`Dose` or an upstream reactor's
    ``out_<species>``) and ``out_<species>`` (connect the next reactor's
    ``in_<species>``, an :class:`Accumulator` or a ``Ground``). Every outlet
    must be connected.

    States: ``<name>.<species>.amount``. Outputs include
    ``<name>.<species>.concentration`` and ``<name>.<reaction>.rate``.

    Args:
        volume: Reactor volume [m^3].
        flow: Volumetric flow through the reactor [m^3/s]. The residence time
            is ``volume / flow``.
        concentrations: ``{species: initial concentration}``. Every species
            the reactions name must be listed, with 0 if absent at the start.
        reactions: The reactions taking place. Their volume is set to the
            reactor's. A reaction object belongs to one reactor; use
            :meth:`Reaction.clone` for another.
    """

    type_name = "mixed_reactor"
    domain = "chemical"

    def __init__(
        self,
        volume: float = 1.0,
        flow: float = 1.0,
        concentrations: Mapping[str, float] | None = None,
        reactions: Sequence[Reaction] = (),
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        conc = dict(concentrations if concentrations is not None else {"A": 1.0})
        if not conc:
            raise ValueError(f"{self.name}: a reactor needs at least one species")
        for s in conc:
            _check_species_name(s, self.name)
        self.species_names = list(conc)
        self.reactions = list(reactions)
        for rx in self.reactions:
            missing = set(rx.stoichiometry) - set(conc)
            if missing:
                raise ValueError(
                    f"{self.name}: reaction {rx.name!r} names species {sorted(missing)} that "
                    f"the reactor does not hold; list them in concentrations (0 if absent)"
                )
            rx.set_volume(volume)
        self.species = {
            s: Species(volume, concentration=c0, name=s) for s, c0 in conc.items()
        }
        self.outflows = {s: Outflow(flow, name=f"out_{s}") for s in conc}
        self.add(*self.species.values(), *self.outflows.values(), *self.reactions)
        for s, sp in self.species.items():
            self.connect(
                sp.port,
                self.outflows[s].a,
                *(rx.ports[s] for rx in self.reactions if s in rx.ports),
            )
            self.expose(f"in_{s}", sp.port)
            self.expose(f"out_{s}", self.outflows[s].b)


class TanksInSeries(Composite):
    """``n`` identical mixed reactors in a line, the classical approximation of
    a plug-flow reactor. The total volume is shared equally; the outflow of
    each tank is the inflow of the next.

    With ``n = 1`` this is a :class:`MixedReactor`; as ``n`` grows the outlet
    concentration of a first-order reaction approaches ``c_in exp(-k tau)``,
    the plug-flow value, as ``(1 + k tau / n)^-n``. A spatially resolved
    plug-flow reactor (dispersion, a PDE) is on the roadmap.

    Ports: ``in_<species>`` of the first tank and ``out_<species>`` of the
    last. States: ``<name>.tank<i>.<species>.amount``.

    Args:
        n: Number of tanks.
        volume: Total volume [m^3].
        flow: Volumetric flow [m^3/s].
        concentrations: Initial concentrations, the same in every tank.
        reactions: Reactions, copied into every tank.
    """

    type_name = "tanks_in_series"
    domain = "chemical"

    def __init__(
        self,
        n: int = 2,
        volume: float = 1.0,
        flow: float = 1.0,
        concentrations: Mapping[str, float] | None = None,
        reactions: Sequence[Reaction] = (),
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if int(n) < 1:
            raise ValueError(f"{self.name}: n must be at least 1")
        self.n = int(n)
        self.tanks = [
            MixedReactor(
                volume / self.n,
                flow,
                concentrations,
                [rx.clone() for rx in reactions],
                name=f"tank{i}",
            )
            for i in range(self.n)
        ]
        self.add(*self.tanks)
        first, last = self.tanks[0], self.tanks[-1]
        for s in first.species_names:
            for up, down in zip(self.tanks, self.tanks[1:], strict=False):
                self.connect(up.ports[f"out_{s}"], down.ports[f"in_{s}"])
            self.expose(f"in_{s}", first.ports[f"in_{s}"])
            self.expose(f"out_{s}", last.ports[f"out_{s}"])
