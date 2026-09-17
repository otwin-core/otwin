"""Lumped heat transfer: across is temperature [K], through is heat flow [W].

``ThermalMass`` has one port, ``port``. ``ThermalResistance`` and
``Convection`` connect two ports. ``HeatSource`` injects heat; ``Ambient``
holds a temperature.

Temperature times heat flow is not a power, so this domain is a
*pseudo* port-Hamiltonian one: the storage function the compiler builds,
``H = E^2 / (2 C)`` with ``E = C T`` the stored heat, is a Lyapunov function
whose gradient is the temperature, not a physical energy. The equations that
come out are the ordinary lumped heat balances; the model summary says
``pseudo-port-Hamiltonian`` when a thermal storage is present. Entropy-carrying
models with a real energy live in :mod:`otwin.model.iphs`.
"""

from __future__ import annotations

from ..expr import Expr
from .base import (
    Branch,
    Component,
    ComponentQuantities,
    HeatBranch,
    Law,
    ResistorBranch,
    SourceBranch,
    StorageBranch,
)

__all__ = [
    "ThermalMass",
    "ThermalResistance",
    "Convection",
    "HeatSource",
    "Losses",
    "Ambient",
]


class ThermalMass(Component):
    """A lump of material at one temperature: ``C dT/dt = sum of heat flows``.

    ``temperature`` sets the initial temperature in kelvin. Extra output:
    ``temperature``.
    """

    domain = "thermal"
    type_name = "thermal_mass"

    def __init__(
        self,
        capacity: float = 1.0,
        *,
        temperature: float = 293.15,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("port")
        self.C = self.add_parameter("capacity", capacity, "J/K")
        if temperature < 0:
            raise ValueError(f"{self.name}: temperature is absolute, in kelvin")
        self.initial_temperature = float(temperature)

    def branches(self) -> list[Branch]:
        return [
            StorageBranch(
                self,
                self.port,
                None,
                kind="across",
                state="heat",
                state_unit="J",
                quantity="stored heat",
                initial=self.initial_temperature * self.value("capacity"),
                energy=lambda E: E * E / (2 * self.C),
            )
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        return {"temperature": ("K", q.state["heat"] / self.C)}


class ThermalResistance(Component):
    """Conduction: ``Q = (T_a - T_b) / R``."""

    domain = "thermal"
    type_name = "thermal_resistance"

    def __init__(
        self,
        resistance: float = 1.0,
        *,
        law: Law | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self._law = law
        if law is None:
            self.R = self.add_parameter("resistance", resistance, "K/W")

    def branches(self) -> list[Branch]:
        law = self._law if self._law is not None else (lambda dT: dT / self.R)
        return [ResistorBranch(self, self.a, self.b, law=law)]


class Convection(Component):
    """Convection or a heat-exchanger duty: ``Q = h A (T_a - T_b)``."""

    domain = "thermal"
    type_name = "convection"

    def __init__(self, conductance: float = 1.0, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("a")
        self.add_port("b")
        self.hA = self.add_parameter("conductance", conductance, "W/K")

    def branches(self) -> list[Branch]:
        return [ResistorBranch(self, self.a, self.b, law=lambda dT: self.hA * dT)]


class HeatSource(Component):
    """Heat delivered into ``port`` in watts. ``heat=None`` makes it an input."""

    domain = "thermal"
    type_name = "heat_source"

    def __init__(self, heat: float | None = None, *, name: str | None = None) -> None:
        super().__init__(name)
        self.add_port("port")
        self.heat = None if heat is None else float(heat)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.port,
                None,
                kind="through",
                value=self.heat,
                unit="W",
                quantity="heat flow",
            )
        ]


class Losses(Component):
    """The power dissipated by other components, delivered into ``port`` as heat.

    ``Losses(r0, r1)`` sums the losses of ``r0`` and ``r1`` (any resistor,
    damper, pipe friction ... anything with a dissipative law) at every instant
    and injects them as heat flow. Connect ``port`` to the thermal mass that
    warms up. Nothing has to be written about the power: the compiler already
    knows ``across * through`` of each source.

    Output: ``<name>.heat_flow`` in watts.
    """

    domain = "thermal"
    type_name = "losses"

    def __init__(self, *sources: Component, name: str | None = None) -> None:
        super().__init__(name)
        if not sources:
            raise ValueError(
                "Losses needs at least one component whose losses it collects"
            )
        self.add_port("port")
        self.sources = list(sources)

    def branches(self) -> list[Branch]:
        return [HeatBranch(self, self.port, None, sources=list(self.sources))]


class Ambient(Component):
    """A body large enough that its temperature does not change. ``temperature=None``
    makes the ambient temperature an input."""

    domain = "thermal"
    type_name = "ambient"

    def __init__(
        self, temperature: float | None = 293.15, *, name: str | None = None
    ) -> None:
        super().__init__(name)
        self.add_port("port")
        self.temperature = None if temperature is None else float(temperature)

    def branches(self) -> list[Branch]:
        return [
            SourceBranch(
                self,
                self.port,
                None,
                kind="across",
                value=self.temperature,
                unit="K",
                quantity="temperature",
            )
        ]
