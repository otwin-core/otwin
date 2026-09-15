"""Hydraulics: across is pressure [Pa], through is volumetric flow [m^3/s].

A ``Tank`` has one terminal, ``port``, at its base; the pressure there is
gauge pressure over atmosphere. ``Orifice`` and ``Pipe`` connect two ports.
``Atmosphere`` is the reference.
"""

from __future__ import annotations

from .. import expr as ex
from ..expr import Expr
from .base import (
    Branch,
    Component,
    ComponentQuantities,
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
        self.terminal("port")
        self.A = self.param("area", area, "m^2")
        self.z = self.param("base_elevation", base_elevation, "m", positive=False)
        self.rho = self.param("density", density, "kg/m^3")
        self.g = self.param("gravity", gravity, "m/s^2")
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
                energy=lambda V: self.rho
                * self.g
                * (self.z * ex.maximum(V, 0.0) + ex.maximum(V, 0.0) ** 2 / (2 * self.A)),
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
        self.terminal("a")
        self.terminal("b")
        self.a_ = self.param("area", area, "m^2")
        self.cd = self.param("discharge_coefficient", discharge_coefficient, "")
        self.rho = self.param("density", density, "kg/m^3")

    def branches(self) -> list[Branch]:
        def law(dp: Expr) -> Expr:
            return ex.sign(dp) * self.cd * self.a_ * ex.sqrt(2 * abs(dp) / self.rho)

        return [ResistorBranch(self, self.a, self.b, law=law)]


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
        self.terminal("a")
        self.terminal("b")
        given = sum(v is not None for v in (resistance, friction, law))
        if given != 1:
            raise ValueError(f"{self.name}: give exactly one of resistance, friction, law")
        self._law = law
        self.R = self.K = None
        if resistance is not None:
            self.R = self.param("resistance", resistance, "Pa s/m^3")
        if friction is not None:
            self.K = self.param("friction", friction, "Pa s^2/m^6")

    def branches(self) -> list[Branch]:
        if self._law is not None:
            law = self._law
        elif self.R is not None:
            law = lambda dp: dp / self.R  # noqa: E731
        else:
            law = lambda dp: ex.sign(dp) * ex.sqrt(abs(dp) / self.K)  # noqa: E731
        return [ResistorBranch(self, self.a, self.b, law=law)]


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
        self.terminal("a")
        self.terminal("b")
        self.I = self.param("inertance", inertance, "kg/m^4")  # noqa: E741
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

    def __init__(self, flow: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("a")
        self.terminal("b")
        self.flow = None if flow is None else float(flow)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self, self.a, self.b, kind="through", value=self.flow, unit="m^3/s",
                quantity="flow",
            )
        ]


class PressureSource(Component):
    """Imposes the pressure difference ``p_a - p_b``."""

    domain = "hydraulic"
    type_name = "pressure_source"

    def __init__(self, pressure: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.terminal("a")
        self.terminal("b")
        self.pressure = None if pressure is None else float(pressure)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self, self.a, self.b, kind="across", value=self.pressure, unit="Pa",
                quantity="pressure",
            )
        ]
