"""Gains: heat pushed into (or drawn out of) a store, no temperature of its own.

In Otwin's terms these are *through sources* in the thermal domain. The key
distinction in a home is whether the electricity meter sees the gain:

* :class:`Appliance` and :class:`BaseLoad` are **metered**: every watt they
  deliver as heat was bought through the meter. Almost all of an appliance's
  electricity ends as heat indoors (the fridge, the television, the lights,
  the router), so the heat and the meter reading are the same number. The
  known exception, washers draining hot water, needs a heat fraction on the
  source that Otwin does not have yet (ARCHITECTURE.md, "Choices").
* :class:`GasAppliance` is metered on the **gas** meter instead: a gas hob
  or oven. All of the gas it burns ends up as heat in the kitchen (what the
  pan does not take, the flame gives to the air), so here too the heat and
  the meter reading are the same number.
* :class:`Occupants` and :class:`SolarGain` are **free**: people give off
  80-100 W each and the sun pours in through the windows, but neither shows
  on a bill. Modelling them matters precisely because leaving them out makes
  a fit blame the heating for heat it never supplied.
* ``indoors=False`` sends a gain's heat outside the home instead of into
  the room (a dishwasher's hot water down the drain): still metered, no
  longer heating. It is the all-or-nothing form of the heat fraction above.
* :class:`HotWaterDraw` is a gain with the sign reversed: heat *leaves* the
  cylinder when a tap runs, positive input = heat drawn (W).

``power=None`` makes a gain an input of the model, named after the
component, fed from a :class:`~components.schedules.Schedule` or a measured
series. A number makes it the parameter ``<name>.power``.
"""

from __future__ import annotations

from otwin.components.base import Branch, Component, ComponentQuantities, SourceBranch
from otwin.expr import Expr

from .schedules import Schedule

__all__ = [
    "HeatGain",
    "Appliance",
    "GasAppliance",
    "BaseLoad",
    "Occupants",
    "SolarGain",
    "HotWaterDraw",
]


class HeatGain(Component):
    """Heat delivered into ``port``, in W. The base of every gain.

    ``power=None`` makes it an input; a number, the parameter ``<name>.power``.
    Output: ``<name>.heat`` (W). Not metered: see :class:`Appliance`.
    """

    domain = "thermal"
    type_name = "heat_gain"
    #: Which meter sees this gain: ``None``, ``"electricity"`` or ``"gas"``.
    fuel: str | None = None

    def __init__(
        self,
        power: float | None = None,
        *,
        schedule: Schedule | None = None,
        indoors: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name)
        self.add_port("port")
        #: Where the heat ends up. ``False`` sends it outside the home: a
        #: dishwasher or washing machine pours most of its heat down the drain,
        #: a vented dryer blows it out. The meter sees the same electricity.
        self.indoors = bool(indoors)
        if power is not None and power < 0:
            raise ValueError(f"{self.name}: power cannot be negative")
        if schedule is not None:
            if power is not None:
                raise ValueError(f"{self.name}: give a schedule or a power, not both")
            if min(schedule.values) < 0:
                raise ValueError(f"{self.name}: a schedule of heat cannot be negative")
        self.power = None if power is None else float(power)
        self.schedule = schedule

    def branches(self) -> list[Branch]:
        """One through source into ``port``: the gain, an input when ``power`` is None."""
        return [
            SourceBranch(
                self,
                self.port,
                None,
                kind="through",
                value=self.power,
                unit="W",
                quantity="power",
            )
        ]

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``heat`` (W): what this gain delivers."""
        return {"heat": ("W", -q.through[self.name])}


class Appliance(HeatGain):
    """An appliance, or a group of them: electricity that becomes heat indoors.

    The power is an input (from the ``schedule`` or a measured plug series)
    unless a constant ``power`` is given. Extra output:
    ``<name>.electric_power`` (W), what the meter sees.
    """

    type_name = "appliance"
    fuel = "electricity"

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``heat`` and ``electric_power`` (W), the same number by construction."""
        out = super().extra_outputs(q)
        out["electric_power"] = ("W", out["heat"][1])
        return out


class GasAppliance(HeatGain):
    """A gas hob or oven: gas from the gas meter that becomes heat indoors.

    Like :class:`Appliance`, but billed on the gas meter. Extra output:
    ``<name>.gas_power`` (W of gas, gross calorific value), what the gas
    meter sees. Butane from a bottle shows on no meter: use a plain
    :class:`HeatGain` for it.
    """

    type_name = "gas_appliance"
    fuel = "gas"

    def extra_outputs(self, q: ComponentQuantities) -> dict[str, tuple[str, Expr]]:
        """``heat`` and ``gas_power`` (W), the same number by construction."""
        out = super().extra_outputs(q)
        out["gas_power"] = ("W", out["heat"][1])
        return out


class BaseLoad(Appliance):
    """The always-on electricity of a home: fridge average, router, standby.

    A constant, the parameter ``<name>.power``; calibration fits it from the
    night-time minimum. Spanish households run 80-250 W.
    """

    type_name = "base_load"

    def __init__(self, power: float = 120.0, *, name: str = "base") -> None:
        super().__init__(float(power), name=name)


class Occupants(HeatGain):
    """People: about 90 W of heat each, for free.

    ``Occupants(people=3)`` is a constant parameter (``<name>.power``,
    ``people × watts_each``). ``people=None`` makes it an input in W, fed from
    ``Schedule([...]).scaled(watts_each)`` of headcounts.
    """

    type_name = "occupants"

    def __init__(
        self,
        people: float | None = 2.0,
        *,
        watts_each: float = 90.0,
        schedule: Schedule | None = None,
        name: str = "occupants",
    ) -> None:
        if watts_each <= 0:
            raise ValueError(f"{name}: watts_each must be positive")
        power = None if people is None else float(people) * watts_each
        super().__init__(power, schedule=schedule, name=name)
        self.watts_each = float(watts_each)


class SolarGain(HeatGain):
    """Sun through the windows, in W: aperture × irradiance, computed outside
    the model (an Open-Meteo series times an effective window area). An input."""

    type_name = "solar_gain"

    def __init__(self, *, schedule: Schedule | None = None, name: str = "solar") -> None:
        super().__init__(None, schedule=schedule, name=name)


class HotWaterDraw(Component):
    """Heat drawn out of ``port`` by hot-water use, in W, positive drawing.

    An input of the model (``<name>``), usually from
    :func:`~components.schedules.hot_water_heat`. ``ref`` is where the drawn
    heat goes as far as the model cares: down the drain.
    """

    domain = "thermal"
    type_name = "hot_water_draw"

    def __init__(self, *, schedule: Schedule | None = None, name: str = "draw") -> None:
        super().__init__(name)
        self.add_port("port")
        self.add_port("ref")
        if schedule is not None and min(schedule.values) < 0:
            raise ValueError(f"{self.name}: a draw cannot be negative")
        self.schedule = schedule

    def branches(self) -> list[Branch]:
        """A through source from ``port`` to ``ref``: the heat drawn."""
        return [
            SourceBranch(
                self,
                self.ref,
                self.port,
                kind="through",
                value=None,
                unit="W",
                quantity="heat drawn",
            )
        ]
