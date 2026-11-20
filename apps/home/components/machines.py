"""Machines: what turns a fuel into heat, or pumps heat out, under a thermostat.

A machine is the only kind of home component with a meter attached: it
delivers (or removes) heat and charges a fuel for it. Each one is a
composite of a :class:`~components.boundaries.Setpoint` and a
:class:`Thermostat`, Otwin primitives both, plus the fuel arithmetic.

**The thermostat as a resistor.** A thermostat-controlled machine delivers
full power when far from the setpoint and less as it closes in; its
time-averaged output is a clipped proportional law::

    Q = clip( (P / band) · ΔT, 0, P )

Read as heat flowing from a reservoir held at the setpoint into the target
(heating), or from the target into the reservoir (cooling), that is a
monotone law that only lets heat flow down its gradient, so it takes the
*resistor* role in Otwin's port-Hamiltonian form, and the engine needs
nothing new. ``band`` is the proportional band: the kelvin of deficit at
which the machine is at full power. A real on/off thermostat with 0.5-2 K of
hysteresis averages to this over a few minutes, which is right for the
hourly and daily energy that bills and meters record, wrong for
minute-scale cycling.

The machines:

* :class:`Boiler`: burns gas; ``efficiency`` is heat per unit of gas on the
  gross calorific value (0.85-0.95; Spanish gas is billed on the gross).
* :class:`ElectricHeater`: resistive; efficiency 1 by definition.
* :class:`HeatPump`: heats with electricity at ``cop`` ≈ 2.5-4. The COP is
  taken constant (a seasonal value); a COP falling with the outdoor
  temperature is a choice recorded in ARCHITECTURE.md.
* :class:`AirConditioner`: the same law run the other way. It removes heat
  when the room is *above* its setpoint and pays electricity at ``eer``
  (heat removed per electrical watt, ≈ 2.5-3.5 seasonal).
* :class:`WaterHeater`: a cylinder (:class:`~components.stores.StoredWater`)
  with its own thermostat, a :class:`~components.exchanges.StandbyLoss` to
  the room it stands in, and a :class:`~components.gains.HotWaterDraw`.

Outputs of every space machine: ``<name>.heat`` or ``<name>.cool`` (W moved)
and ``<name>.fuel_power`` (W of gas or electricity drawn).
"""

from __future__ import annotations

from otwin import expr as ex
from otwin.components.base import (
    Branch,
    Component,
    ComponentQuantities,
    Composite,
    Ground,
    ResistorBranch,
)
from otwin.expr import Expr

from .boundaries import ZERO_CELSIUS, Setpoint
from .exchanges import StandbyLoss
from .gains import HotWaterDraw
from .schedules import Schedule
from .stores import StoredWater

__all__ = [
    "Thermostat",
    "SpaceMachine",
    "Boiler",
    "ElectricHeater",
    "HeatPump",
    "AirConditioner",
    "WaterHeater",
    "FUELS",
]

#: The energy carriers a machine may draw, and the meter each one feeds.
FUELS = ("electricity", "gas")


class Thermostat(Component):
    """Heat from ``a`` into ``b``: ``Q = clip(power / band · (T_a − T_b), 0, power)``,
    with an interior thermometer.

    The one law behind every machine. Parameters ``power`` (W) and ``band``
    (K) stay symbolic, so a fit can estimate a machine's effective power.

    **The thermometer.** A thermostat acts on what its sensor reads, so the
    sensor is part of it: a probe on the side it controls (``sensor="b"``,
    the room for a heater, the water for a cylinder; ``"a"`` for a cooler,
    which takes heat out of ``a``). The probe carries no heat; it reads the
    temperature of its node. Outputs:

    * ``<name>.temperature`` (K): what the thermometer reads;
    * ``<name>.on``: 1 while the thermostat calls for heat (or cold), 0 when
      it is satisfied;
    * ``<name>.duty``: the fraction of the time the machine runs, 0 to 1. The
      law is the cycle average of an on/off controller, so ``duty`` is what an
      hour of on/off switching averages to, and ``on`` says whether it
      switched on at all.
    """

    domain = "thermal"
    type_name = "thermostat"

    def __init__(
        self,
        power: float,
        band: float = 1.0,
        *,
        sensor: str = "b",
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        if sensor not in ("a", "b"):
            raise ValueError(f"{self.name}: sensor must be 'a' or 'b', not {sensor!r}")
        self.add_port("a")
        self.add_port("b")
        self.sensor = sensor
        self.P = self.add_parameter("power", power, "W", "maximum heat moved")
        self.band = self.add_parameter(
            "band", band, "K", "proportional band: full power this far from the setpoint"
        )

    @property
    def thermometer_label(self) -> str:
        """The label of the thermometer branch (its across is the reading)."""
        return f"{self.name}.thermometer"

    def branches(self) -> list[Branch]:
        """The clipped proportional law ``a`` to ``b``, and the thermometer: a
        probe from the sensed port to the datum that carries no heat."""

        def law(dT: Expr) -> Expr:
            return ex.minimum(ex.maximum(self.P / self.band * dT, 0.0), self.P)

        def probe(dT: Expr) -> Expr:
            return dT * 0.0  # an ideal sensor: no heat flows into it

        sensed = self.a if self.sensor == "a" else self.b
        return [
            ResistorBranch(self, self.a, self.b, law=law),
            ResistorBranch(self, sensed, None, law=probe, label=self.thermometer_label),
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``temperature`` (K), ``on`` (0 or 1) and ``duty`` (0 to 1)."""
        moved = q.through[self.name]
        return {
            "temperature": ("K", q.across[self.thermometer_label]),
            "on": ("", ex.where(moved > 1e-6 * self.P, 1.0, 0.0)),
            "duty": ("", moved / self.P),
        }


class SpaceMachine(Composite):
    """A thermostat-controlled machine on a space: the base of the four above.

    Subclasses fix ``fuel``, the sense (heating or cooling) and the meaning
    of ``efficiency``. Port ``port``: connect to the zone's ``air``.

    Args:
        power: maximum heat moved, W.
        setpoint: thermostat setting, K. ``None`` makes it the input
            ``<name>.setpoint`` for schedules.
        band: proportional band, K.
        efficiency: heat moved per unit of fuel drawn.
        setpoint_schedule: default :class:`Schedule` for a ``None`` setpoint.
    """

    domain = "thermal"
    #: "heat" delivers into the space; "cool" removes from it.
    sense = "heat"
    fuel = "gas"

    def __init__(
        self,
        power: float,
        *,
        setpoint: float | None,
        band: float = 1.0,
        efficiency: float = 1.0,
        setpoint_schedule: Schedule | None = None,
        name: str,
    ) -> None:
        super().__init__(name)
        if self.fuel not in FUELS:
            raise ValueError(
                f"{self.name}: fuel must be one of {FUELS}, not {self.fuel!r}"
            )
        if efficiency <= 0:
            raise ValueError(f"{self.name}: efficiency must be positive")
        if self.fuel == "gas" and efficiency > 1.1:
            # Condensing boilers reach ~1.07 on the net calorific value, but
            # Spanish gas is billed on the gross (PCS), where they stay below 1.
            raise ValueError(f"{self.name}: a gas efficiency above 1.1 is not physical")
        if setpoint_schedule is not None and setpoint is not None:
            raise ValueError(f"{self.name}: give a setpoint or a schedule, not both")
        self.efficiency = float(efficiency)
        self.setpoint_schedule = setpoint_schedule
        sp = Setpoint(setpoint, name="setpoint")
        th = Thermostat(
            power, band, sensor="b" if self.sense == "heat" else "a", name="thermostat"
        )
        self.add(sp, th)
        if self.sense == "heat":
            self.connect(sp.port, th.a)
            self.expose("port", th.b)
        else:
            self.connect(th.b, sp.port)
            self.expose("port", th.a)

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``heat`` or ``cool`` (W moved) and ``fuel_power`` (W of fuel)."""
        moved = q.through[f"{self.name}.thermostat"]
        return {self.sense: ("W", moved), "fuel_power": ("W", moved / self.efficiency)}


class Boiler(SpaceMachine):
    """A gas boiler: a 24 kW *caldera mixta* heats most Spanish flats."""

    type_name = "boiler"
    sense, fuel = "heat", "gas"

    def __init__(
        self,
        power: float = 24e3,
        *,
        setpoint: float | None = ZERO_CELSIUS + 20.0,
        band: float = 1.0,
        efficiency: float = 0.9,
        setpoint_schedule: Schedule | None = None,
        name: str = "heating",
    ) -> None:
        super().__init__(
            power,
            setpoint=setpoint,
            band=band,
            efficiency=efficiency,
            setpoint_schedule=setpoint_schedule,
            name=name,
        )


class ElectricHeater(SpaceMachine):
    """A resistive heater: every watt bought is a watt of heat."""

    type_name = "electric_heater"
    sense, fuel = "heat", "electricity"

    def __init__(
        self,
        power: float = 2e3,
        *,
        setpoint: float | None = ZERO_CELSIUS + 20.0,
        band: float = 1.0,
        setpoint_schedule: Schedule | None = None,
        name: str = "heating",
    ) -> None:
        super().__init__(
            power,
            setpoint=setpoint,
            band=band,
            efficiency=1.0,
            setpoint_schedule=setpoint_schedule,
            name=name,
        )


class HeatPump(SpaceMachine):
    """A heat pump heating: ``cop`` watts of heat per electrical watt."""

    type_name = "heat_pump"
    sense, fuel = "heat", "electricity"

    def __init__(
        self,
        power: float = 5e3,
        *,
        cop: float = 3.0,
        setpoint: float | None = ZERO_CELSIUS + 20.0,
        band: float = 1.0,
        setpoint_schedule: Schedule | None = None,
        name: str = "heating",
    ) -> None:
        super().__init__(
            power,
            setpoint=setpoint,
            band=band,
            efficiency=cop,
            setpoint_schedule=setpoint_schedule,
            name=name,
        )

    @property
    def cop(self) -> float:
        """Heat delivered per electrical watt (the efficiency)."""
        return self.efficiency


class AirConditioner(SpaceMachine):
    """Cooling: removes heat when the room is above the setpoint.

    ``eer`` is the seasonal energy-efficiency ratio: watts of heat removed
    per electrical watt. Output ``<name>.cool`` is positive while cooling.
    """

    type_name = "air_conditioner"
    sense, fuel = "cool", "electricity"

    def __init__(
        self,
        power: float = 5e3,
        *,
        eer: float = 3.0,
        setpoint: float | None = ZERO_CELSIUS + 25.0,
        band: float = 1.0,
        setpoint_schedule: Schedule | None = None,
        name: str = "cooling",
    ) -> None:
        super().__init__(
            power,
            setpoint=setpoint,
            band=band,
            efficiency=eer,
            setpoint_schedule=setpoint_schedule,
            name=name,
        )

    @property
    def eer(self) -> float:
        """Heat removed per electrical watt (the efficiency)."""
        return self.efficiency


class WaterHeater(Composite):
    """A hot-water cylinder: tank, thermostat, standby loss, draws.

    Args:
        volume: litres (an 80 L electric *termo*, a 100 L gas *acumulador*).
        power: heating power, W: 1.2-2 kW electric, 5-10 kW gas burner.
        setpoint: thermostat setting, K (60 °C keeps legionella away).
        band: proportional band, K.
        loss_ua: standby skin loss, W/K (see :class:`StandbyLoss`).
        efficiency: heat per unit of fuel (1 electric, 0.85-0.95 gas).
        fuel: ``"electricity"`` or ``"gas"``.
        temperature: initial water temperature, K; the setpoint if omitted.
        draw_schedule: default :class:`Schedule` for the draw input, W of
            heat (see :func:`~components.schedules.hot_water_heat`).

    Port ``room``: where the standby loss goes: the zone's ``air`` indoors,
    an :class:`~components.boundaries.Outdoors` on a balcony.

    Input ``<name>.draw``: heat drawn by hot-water use, W, positive.

    Outputs: ``<name>.temperature`` (K), ``<name>.heat`` (W from the element
    or burner), ``<name>.fuel_power`` (W), ``<name>.standby_loss`` (W).
    """

    domain = "thermal"
    type_name = "water_heater"

    def __init__(
        self,
        volume: float = 80.0,
        *,
        power: float = 1500.0,
        setpoint: float = ZERO_CELSIUS + 60.0,
        band: float = 2.0,
        loss_ua: float = 1.1,
        efficiency: float = 1.0,
        fuel: str = "electricity",
        temperature: float | None = None,
        draw_schedule: Schedule | None = None,
        name: str = "water_heater",
    ) -> None:
        super().__init__(name)
        if fuel not in FUELS:
            raise ValueError(f"{self.name}: fuel must be one of {FUELS}, not {fuel!r}")
        if efficiency <= 0:
            raise ValueError(f"{self.name}: efficiency must be positive")
        if fuel == "gas" and efficiency > 1.1:
            raise ValueError(f"{self.name}: a gas efficiency above 1.1 is not physical")
        if setpoint <= 0 or (temperature is not None and temperature <= 0):
            raise ValueError(f"{self.name}: temperatures are absolute, in kelvin")
        self.fuel = fuel
        self.efficiency = float(efficiency)
        self.draw_schedule = draw_schedule
        tank = StoredWater(
            volume, temperature=setpoint if temperature is None else temperature
        )
        self.volume = tank.volume
        sp = Setpoint(setpoint)
        th = Thermostat(power, band, name="thermostat")
        loss = StandbyLoss(loss_ua)
        draw = HotWaterDraw()
        ref = Ground(name="ref")
        self.add(tank, sp, th, loss, draw, ref)
        self.connect(sp.port, th.a)
        self.connect(th.b, tank.port, loss.a, draw.port)
        self.connect(draw.ref, ref.port)
        self.expose("room", loss.b)

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``temperature``, ``heat``, ``fuel_power`` and ``standby_loss``."""
        n = self.name
        heat = q.through[f"{n}.thermostat"]
        return {
            "temperature": ("K", q.across[f"{n}.tank"]),
            "heat": ("W", heat),
            "fuel_power": ("W", heat / self.efficiency),
            "standby_loss": ("W", q.through[f"{n}.standby"]),
        }
