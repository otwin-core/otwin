"""The thermal zone: stores and exchanges assembled into the heated space.

A :class:`ThermalZone` is a composite, built from the primitives the way
``otwin.components.battery.Battery`` is built from resistors and capacitors:

**1R1C** (``ThermalZone(ua, capacity)``)::

    Outdoors ──[Envelope + Ventilation]── RoomAir

    C dT/dt = Q_in − (ua + ventilation) (T − T_out)

**2R2C** (``ThermalZone(..., fabric_capacity=..., fabric_coupling=...)``)::

    Outdoors ──[Envelope]── BuildingFabric ──[InteriorSurface]── RoomAir
        └──────────────────────[Ventilation]───────────────────────┘

This is the lumped model behind ISO 52016-1 and the ISO 13790 5R1C method.
Gains and machines connect at the ``air`` node; the ``outside`` port goes to
an :class:`~components.boundaries.Outdoors`.
"""

from __future__ import annotations

from otwin.components.base import ComponentQuantities, Composite
from otwin.expr import Expr

from .boundaries import ZERO_CELSIUS
from .exchanges import Envelope, InteriorSurface, Ventilation
from .stores import BuildingFabric, RoomAir

__all__ = ["ThermalZone"]


class ThermalZone(Composite):
    """A heated space: indoor air (and contents) plus, optionally, the fabric.

    Args:
        ua: :class:`Envelope` conductance, W/K.
        capacity: :class:`RoomAir` heat capacity, J/K.
        ventilation: :class:`Ventilation` conductance, W/K; ``None`` for no
            separate air-change path.
        fabric_capacity: :class:`BuildingFabric` capacity, J/K. With
            ``fabric_coupling`` it makes the 2R2C form.
        fabric_coupling: :class:`InteriorSurface` conductance, W/K.
        temperature: initial indoor temperature, K (also the fabric's).
        fabric_temperature: initial fabric temperature, if different.

    Ports:
        ``air``: the indoor air node, where gains and machines connect.
        ``outside``: connect an :class:`~components.boundaries.Outdoors`.

    Outputs:
        ``<name>.temperature`` (K), ``<name>.heat_loss`` (W to the outside,
        envelope and ventilation together) and, in the 2R2C form,
        ``<name>.fabric_temperature`` (K).
    """

    type_name = "thermal_zone"
    domain = "thermal"

    def __init__(
        self,
        ua: float = 200.0,
        capacity: float = 2.0e7,
        *,
        ventilation: float | None = None,
        fabric_capacity: float | None = None,
        fabric_coupling: float | None = None,
        temperature: float = ZERO_CELSIUS + 20.0,
        fabric_temperature: float | None = None,
        name: str = "zone",
    ) -> None:
        super().__init__(name)
        if (fabric_capacity is None) != (fabric_coupling is None):
            raise ValueError(
                f"{self.name}: give fabric_capacity and fabric_coupling together "
                "(2R2C), or neither (1R1C)"
            )
        if temperature <= 0 or (
            fabric_temperature is not None and fabric_temperature <= 0
        ):
            raise ValueError(f"{self.name}: temperatures are absolute, in kelvin")
        self.two_node = fabric_capacity is not None
        air = RoomAir(capacity, temperature=temperature)
        envelope = Envelope(ua)
        self.add(air, envelope)
        self._to_outside = [envelope]
        if self.two_node:
            fabric = BuildingFabric(
                fabric_capacity,  # type: ignore[arg-type]
                temperature=fabric_temperature or temperature,
            )
            coupling = InteriorSurface(fabric_coupling)  # type: ignore[arg-type]
            self.add(fabric, coupling)
            self.connect(air.port, coupling.a)
            self.connect(coupling.b, fabric.port, envelope.a)
        else:
            if fabric_temperature is not None:
                raise ValueError(f"{self.name}: fabric_temperature needs the 2R2C form")
            self.connect(air.port, envelope.a)
        outside = [envelope.b]
        if ventilation is not None:
            vent = Ventilation(ventilation)
            self.add(vent)
            self.connect(air.port, vent.a)
            outside.append(vent.b)
            self._to_outside.append(vent)
        if len(outside) > 1:
            self.connect(*outside)
        self.expose("air", air.port)
        self.expose("outside", envelope.b)

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``temperature`` and ``heat_loss``, plus ``fabric_temperature`` in 2R2C."""
        n = self.name
        loss = q.through[self._to_outside[0].name]
        for branch in self._to_outside[1:]:
            loss = loss + q.through[branch.name]
        out = {
            "temperature": ("K", q.across[f"{n}.air"]),
            "heat_loss": ("W", loss),
        }
        if self.two_node:
            out["fabric_temperature"] = ("K", q.across[f"{n}.fabric"])
        return out
