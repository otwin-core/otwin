"""Otwin Home components: a household's heat and money on the Otwin engine.

One module per role, the way ``otwin.components`` keeps one module per
domain. Every component plays exactly one role, and the roles map one to one
onto Otwin's own (see ARCHITECTURE.md, "Components"):

=============  ===========================  =======================================
home role      otwin role                   components
=============  ===========================  =======================================
boundaries     across source                ``Outdoors``, ``Setpoint``
stores         across storage               ``RoomAir``, ``BuildingFabric``,
                                            ``StoredWater``
exchanges      resistor                     ``Envelope``, ``Ventilation``,
                                            ``InteriorSurface``, ``StandbyLoss``
gains          through source               ``Appliance``, ``GasAppliance``,
                                            ``BaseLoad``, ``Occupants``, ``SolarGain``,
                                            ``HotWaterDraw``
machines       composite with a meter       ``Boiler``, ``ElectricHeater``,
                                            ``HeatPump``, ``AirConditioner``,
                                            ``WaterHeater`` (law: ``Thermostat``)
zones          composite                    ``ThermalZone``
schedules      inputs, not physics          ``Schedule``, ``hot_water_heat``
catalogue      ready-made homes             ``madrid_flat``, ``seville_house``
=============  ===========================  =======================================

:func:`build_home` wires one zone, its gains and its machines into one
compiled model; :class:`HomeTwin` runs it and reads the electricity and gas
meters.

>>> from components import seville_house
>>> twin = seville_house(backend="numpy")
>>> sorted(twin.input_names)
['kitchen', 'living', 'outdoor', 'termo.draw']
>>> twin.gas_outputs  # everything in Seville runs on electricity
[]
"""

from __future__ import annotations

from .boundaries import ZERO_CELSIUS, Outdoors, Setpoint
from .catalogue import madrid_flat, seville_house
from .exchanges import (
    Envelope,
    InteriorSurface,
    SkyRadiation,
    StandbyLoss,
    Ventilation,
    sky_depression,
)
from .gains import (
    Appliance,
    BaseLoad,
    GasAppliance,
    HeatGain,
    HotWaterDraw,
    Occupants,
    SolarGain,
)
from .home import HomeRun, HomeTwin, build_home
from .machines import (
    FUELS,
    AirConditioner,
    Boiler,
    ElectricHeater,
    HeatPump,
    SpaceMachine,
    Thermostat,
    WaterHeater,
)
from .schedules import WATER_HEAT_CAPACITY, Schedule, hot_water_heat
from .stores import BuildingFabric, RoomAir, StoredWater
from .zones import ThermalZone

__all__ = [
    # boundaries
    "Outdoors",
    "Setpoint",
    "ZERO_CELSIUS",
    # stores
    "RoomAir",
    "BuildingFabric",
    "StoredWater",
    "WATER_HEAT_CAPACITY",
    # exchanges
    "Envelope",
    "SkyRadiation",
    "sky_depression",
    "Ventilation",
    "InteriorSurface",
    "StandbyLoss",
    # gains
    "HeatGain",
    "Appliance",
    "GasAppliance",
    "BaseLoad",
    "Occupants",
    "SolarGain",
    "HotWaterDraw",
    # machines
    "Thermostat",
    "SpaceMachine",
    "Boiler",
    "ElectricHeater",
    "HeatPump",
    "AirConditioner",
    "WaterHeater",
    "FUELS",
    # zones
    "ThermalZone",
    # schedules
    "Schedule",
    "hot_water_heat",
    # the twin
    "HomeTwin",
    "HomeRun",
    "build_home",
    # catalogue
    "madrid_flat",
    "seville_house",
]
