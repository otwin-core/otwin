"""Hydraulics: across is pressure [Pa], through is volumetric flow [m^3/s].

A ``Tank`` has one port, ``port``, at its base; the pressure there is
gauge pressure over atmosphere. ``Orifice``, ``Pipe``, ``Filter`` and ``Pump``
connect two ports. ``Atmosphere`` is the reference.
"""

from __future__ import annotations

from collections.abc import Sequence

from .. import expr as ex
from ..expr import Expr
from .base import (
    Branch,
    Component,
    ComponentQuantities,
    Composite,
    Ground,
    Law,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
)

__all__ = [
    "Tank",
    "Orifice",
    "Pipe",
    "FluidInertance",
    "FlowSource",
    "PressureSource",
    "Filter",
    "Pump",
    "Atmosphere",
]

G_ACC = 9.81


class Atmosphere(Ground):
    """Atmospheric pressure. The hydraulic reference."""

    type_name = "atmosphere"


class Tank(Component):
    """An open tank with a free surface.

    State: stored volume ``V``. Energy: gravitational potential of the column,
    ``H = rho g (z V + V^2 / (2 A))`` with ``z`` the base elevation over the
    datum, so the pressure at the port is ``rho g (z + V / A)``. The volume is
    clamped at empty inside ``H``: a step that overshoots below zero reads a
    pressure of zero rather than a negative one, so the tank cannot be drained
    past empty and the energy cannot read back as an increase.

    ``level`` sets the initial level above the base. Extra output: ``level``.
    """

    domain = "hydraulic"
    type_name = "tank"

    def __init__(
        self,
        area: float = 1.0,
        *,
        level: float = 0.0,
        base_elevation: float = 0.0,
        density: float = 1000.0,
        gravity: float = G_ACC,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("port")
        self.A = self.add_parameter("area", area, "m^2", "free surface area")
        self.z = self.add_parameter(
            "base_elevation",
            base_elevation,
            "m",
            "height of the tank floor",
            positive=False,
        )
        self.rho = self.add_parameter("density", density, "kg/m^3", "of the liquid")
        self.g = self.add_parameter(
            "gravity", gravity, "m/s^2", "gravitational acceleration"
        )
        if level < 0:
            raise ValueError(f"{self.name}: level must not be negative")
        self.initial_level = float(level)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.port,
                None,
                kind="across",
                state="volume",
                state_unit="m^3",
                quantity="volume",
                initial=self.initial_level * self.value("area"),
                energy=lambda V: (
                    self.rho
                    * self.g
                    * (
                        self.z * ex.maximum(V, 0.0)
                        + ex.maximum(V, 0.0) ** 2 / (2 * self.A)
                    )
                ),
            )
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        return {"level": ("m", q.state["volume"] / self.A)}


class Orifice(Component):
    """Torricelli outflow through a sharp orifice: ``Q = Cd a sqrt(2 dp / rho)``.

    Flow is positive from ``a`` to ``b`` when the pressure at ``a`` is higher;
    the law is odd in the pressure difference so reversed flow is handled.
    """

    domain = "hydraulic"
    type_name = "orifice"

    def __init__(
        self,
        area: float = 0.01,
        *,
        discharge_coefficient: float = 0.6,
        density: float = 1000.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.a_ = self.add_parameter("area", area, "m^2", "opening area")
        self.cd = self.add_parameter(
            "discharge_coefficient",
            discharge_coefficient,
            "",
            "Q = Cd A sqrt(2 dp / rho)",
        )
        self.rho = self.add_parameter("density", density, "kg/m^3", "of the liquid")

    def branches(self) -> list[Branch]:
        def law(dp: Expr) -> Expr:
            return ex.sign(dp) * self.cd * self.a_ * ex.sqrt(2 * abs(dp) / self.rho)

        def inverse(q: Expr) -> Expr:
            return self.rho * q * abs(q) / (2 * self.cd * self.cd * self.a_ * self.a_)

        return [ResistorBranch(self, self.a, self.b, law=law, inverse=inverse)]


class Pipe(Component):
    """A pipe with laminar (linear) or turbulent (quadratic) loss.

    ``resistance`` gives ``dp = R Q`` in Pa s/m^3. ``friction`` gives
    ``dp = K Q |Q|`` in Pa s^2/m^6 instead. Give one or the other.
    """

    domain = "hydraulic"
    type_name = "pipe"

    def __init__(
        self,
        resistance: float | None = None,
        *,
        friction: float | None = None,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        given = sum(v is not None for v in (resistance, friction, law))
        if given != 1:
            raise ValueError(
                f"{self.name}: give exactly one of resistance, friction, law"
            )
        self._law = law
        self.R = self.K = None
        if resistance is not None:
            self.R = self.add_parameter(
                "resistance", resistance, "Pa s/m^3", "laminar: dp = R Q"
            )
        if friction is not None:
            self.K = self.add_parameter(
                "friction", friction, "Pa s^2/m^6", "turbulent: dp = K Q |Q|"
            )

    def branches(self) -> list[Branch]:
        inverse = None
        if self._law is not None:
            law = self._law
        elif self.R is not None:
            law = lambda dp: dp / self.R  # noqa: E731
            inverse = lambda q: q * self.R  # noqa: E731
        else:
            law = lambda dp: ex.sign(dp) * ex.sqrt(abs(dp) / self.K)  # noqa: E731
            inverse = lambda q: self.K * q * abs(q)  # noqa: E731
        return [ResistorBranch(self, self.a, self.b, law=law, inverse=inverse)]


class FluidInertance(Component):
    """The inertia of the fluid in a pipe: ``dp = I dQ/dt``, ``H = I Q^2 / 2``.

    The state is the flow momentum ``I Q``. ``inertance`` is ``rho L / A``.
    """

    domain = "hydraulic"
    type_name = "fluid_inertance"

    def __init__(
        self, inertance: float = 1.0, *, flow: float = 0.0, name: str | None = None
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.I = self.add_parameter(  # noqa: E741
            "inertance", inertance, "kg/m^4", "rho L / A of the liquid column"
        )
        self.initial_flow = float(flow)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.a,
                self.b,
                kind="through",
                state="flow_momentum",
                state_unit="Pa s",
                quantity="flow momentum",
                initial=self.initial_flow * self.value("inertance"),
                energy=lambda p: p * p / (2 * self.I),
            )
        ]


class FlowSource(Component):
    """A pump or a demand. Positive flow is drawn from ``b`` and delivered at
    ``a``; with ``b`` at :class:`Atmosphere` it is an inlet, with ``a`` there a
    drain. ``flow=None`` makes it an input.
    """

    domain = "hydraulic"
    type_name = "flow_source"
    series_ports = ("b", "a")

    def __init__(self, flow: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.flow = None if flow is None else float(flow)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.a,
                self.b,
                kind="through",
                value=self.flow,
                unit="m^3/s",
                quantity="flow",
            )
        ]


class PressureSource(Component):
    """Imposes the pressure difference ``p_a - p_b``."""

    domain = "hydraulic"
    type_name = "pressure_source"
    series_ports = ("b", "a")

    def __init__(self, pressure: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.pressure = None if pressure is None else float(pressure)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.a,
                self.b,
                kind="across",
                value=self.pressure,
                unit="Pa",
                quantity="pressure",
            )
        ]


class Filter(Component):
    """A filter, membrane or strainer: a linear resistance that fouls.

    ``dp = R Q`` with ``R = resistance * (1 + fouling)``. ``fouling`` is a
    parameter (0 when clean) so a maintenance study can raise it with
    ``model.with_parameters({"<name>.fouling": 0.8})`` or identify it from
    measurements. Ports ``a`` (upstream) and ``b`` (downstream).

    Extra output: ``<name>.pressure_drop`` in Pa.
    """

    domain = "hydraulic"
    type_name = "filter"

    def __init__(
        self,
        resistance: float,
        *,
        fouling: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.R = self.add_parameter("resistance", resistance, "Pa s/m^3", "when clean")
        self.phi = self.add_parameter(
            "fouling", fouling, "", "extra resistance as a fraction of clean", False, True
        )

    def branches(self) -> list[Branch]:
        return [
            ResistorBranch(
                self, self.a, self.b, law=lambda dp: dp / (self.R * (1 + self.phi))
            )
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        return {"pressure_drop": ("Pa", q.across[self.name])}


class _Curve(Component):
    """The loss below shut-off of a tabulated pump: ``drop(Q)`` and its inverse."""

    domain = "hydraulic"
    type_name = "pump_curve"

    def __init__(self, drops: list[float], flows: list[float], *, name: str) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.drops, self.flows = drops, flows

    def branches(self) -> list[Branch]:
        drops, flows = self.drops, self.flows
        return [
            ResistorBranch(
                self,
                self.a,
                self.b,
                law=lambda drop: ex.sign(drop) * ex.interp(abs(drop), drops, flows),
                inverse=lambda q: ex.sign(q) * ex.interp(abs(q), flows, drops),
            )
        ]


class Pump(Composite):
    """A centrifugal pump given by its curve: pressure rise against flow.

    Give either the table ``curve=[(flow, pressure_rise), ...]`` in m^3/s and
    Pa, from shut-off (flow 0) to the end of the curve, or the two numbers of
    a parabola: ``shutoff`` (pressure rise at zero flow) and ``max_flow`` (flow
    at zero pressure rise), giving ``dp = shutoff (1 - (Q / max_flow)^2)``.

    Ports ``inlet`` (suction) and ``outlet`` (discharge). Flow is positive from
    inlet to outlet. Inside, the pump is a pressure source at the shut-off
    value in series with a hydraulic loss that follows the curve and the
    inertia of the water in the pump (``inertance``, kg/m^4, by default
    that of about ten metres of pipe). The inertia is what every real pump
    line has, and it makes the flow a state: the compiler integrates it
    instead of solving the curve against the network at every step.

    Outputs: ``<name>.flow`` (m^3/s), ``<name>.pressure_rise`` (Pa),
    ``<name>.hydraulic_power`` (W, the power handed to the water).
    """

    type_name = "pump"
    domain = "hydraulic"

    def __init__(
        self,
        curve: Sequence[tuple[float, float]] | None = None,
        *,
        shutoff: float | None = None,
        max_flow: float | None = None,
        inertance: float = 1e6,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if curve is not None:
            if shutoff is not None or max_flow is not None:
                raise ValueError(
                    f"{self.name}: give curve or (shutoff, max_flow), not both"
                )
            pts = sorted((float(q), float(dp)) for q, dp in curve)
            if len(pts) < 2 or pts[0][0] != 0.0:
                raise ValueError(
                    f"{self.name}: curve needs at least two points, the first at flow 0"
                )
            flows = [q for q, _ in pts]
            rises = [dp for _, dp in pts]
            if any(b >= a for a, b in zip(rises[:-1], rises[1:], strict=True)):
                raise ValueError(f"{self.name}: pressure rise must fall as flow grows")
            dp0 = rises[0]
            drops = [dp0 - dp for dp in rises]  # increasing, starts at 0
            loss = _Curve(drops, flows, name="curve")
        else:
            if shutoff is None or max_flow is None:
                raise ValueError(
                    f"{self.name}: give curve=[...] or shutoff= and max_flow="
                )
            if shutoff <= 0 or max_flow <= 0:
                raise ValueError(f"{self.name}: shutoff and max_flow must be positive")
            dp0 = float(shutoff)
            loss = Pipe(friction=dp0 / float(max_flow) ** 2, name="curve")
        self.shutoff = dp0
        head = PressureSource(dp0, name="head")
        water = FluidInertance(inertance, name="water")
        self.add(head, loss, water)
        self.connect(head.a, loss.a)
        self.connect(loss.b, water.a)
        self.expose("inlet", head.b)
        self.expose("outlet", water.b)

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        n = self.name
        flow = q.through[f"{n}.water"]
        rise = q.across[f"{n}.head"] - q.across[f"{n}.curve"] - q.across[f"{n}.water"]
        return {
            "flow": ("m^3/s", flow),
            "pressure_rise": ("Pa", rise),
            "hydraulic_power": ("W", rise * flow),
        }
