"""Stores: where a home keeps heat.

In Otwin's terms these are *across storages* in the thermal domain: a state
that accumulates heat, whose temperature is what a thermometer would read.
A home has three that matter:

* :class:`RoomAir`: the air and light contents of the heated space. Small
  (about 1-2×10⁷ J/K for a flat), so it reacts in hours.
* :class:`BuildingFabric`: walls, floor slab, partitions. An order of
  magnitude larger, so it reacts in days. This is why a cold spell takes a
  day to show indoors, and why pre-heating works.
* :class:`StoredWater`: the water in a hot-water cylinder, sized in litres.

Each is a :class:`~otwin.components.thermal.ThermalMass` under a name that
says what it is in a house; the heat capacity stays a fittable parameter
(``<name>.capacity``, J/K).
"""

from __future__ import annotations

from otwin.components.thermal import ThermalMass

from .boundaries import ZERO_CELSIUS

__all__ = ["RoomAir", "BuildingFabric", "StoredWater", "WATER_HEAT_CAPACITY"]

#: Volumetric heat capacity of water, J/(L K): 4186 J/(kg K) at 1 kg/L. Tap
#: water at 40-60 °C is 1-2 % less dense, inside any household's uncertainty.
WATER_HEAT_CAPACITY = 4186.0


class RoomAir(ThermalMass):
    """The air and light contents of the heated space, as one store.

    Args:
        capacity: heat capacity in J/K. Air alone is about 2.5×10⁵ J/K per
            100 m³; furniture and surfaces raise the effective value to
            1-2×10⁷ J/K for a flat.
        temperature: initial temperature, K.
    """

    type_name = "room_air"

    def __init__(
        self,
        capacity: float = 1.5e7,
        *,
        temperature: float = ZERO_CELSIUS + 20.0,
        name: str = "air",
    ) -> None:
        super().__init__(capacity, temperature=temperature, name=name)


class BuildingFabric(ThermalMass):
    """Walls, slab and partitions: the slow store that steadies the home.

    Args:
        capacity: heat capacity in J/K; around 10⁸ J/K for a brick flat.
        temperature: initial temperature, K.
    """

    type_name = "building_fabric"

    def __init__(
        self,
        capacity: float = 1.0e8,
        *,
        temperature: float = ZERO_CELSIUS + 20.0,
        name: str = "fabric",
    ) -> None:
        super().__init__(capacity, temperature=temperature, name=name)


class StoredWater(ThermalMass):
    """The water inside a cylinder, sized the way the box is labelled: litres.

    ``capacity = 4186 J/(L K) × volume`` and stays the fittable parameter;
    ``volume`` is kept as an attribute for reporting.
    """

    type_name = "stored_water"

    def __init__(
        self,
        volume: float = 80.0,
        *,
        temperature: float = ZERO_CELSIUS + 60.0,
        name: str = "tank",
    ) -> None:
        if volume <= 0:
            raise ValueError(f"{name}: volume must be positive (litres)")
        self.volume = float(volume)
        super().__init__(
            WATER_HEAT_CAPACITY * self.volume, temperature=temperature, name=name
        )
