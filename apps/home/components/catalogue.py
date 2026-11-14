"""Ready-made homes, the way ``otwin.components.catalogue`` carries systems.

Each function assembles a fully specified household from the component
library and returns a compiled :class:`~components.home.HomeTwin`. They are
the bundled examples and the fixtures of the test suite; a real household
starts from one and changes the numbers.

* :func:`madrid_flat`: gas heating, electric hot water, cold winters.
* :func:`seville_house`: heat pump and air conditioning on one electricity
  meter, hot summers.
"""

from __future__ import annotations

from .boundaries import ZERO_CELSIUS
from .gains import Appliance, BaseLoad, Occupants
from .home import HomeTwin, build_home
from .machines import AirConditioner, Boiler, HeatPump, WaterHeater
from .schedules import Schedule, hot_water_heat
from .zones import ThermalZone

__all__ = [
    "madrid_flat",
    "seville_house",
    "KITCHEN",
    "LIVING",
    "HOT_WATER",
    "HEATING_SETPOINT",
]

#: Appliance use of a two-person household on a weekday, W per local hour:
#: breakfast, lunch at 14-15 h (the Spanish timetable), dinner and television
#: in the evening. 3.9 kWh a day, on top of the base load.
KITCHEN = Schedule(
    [
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        350,
        250,
        0,
        0,
        0,
        0,
        600,
        900,
        300,
        0,
        0,
        0,
        0,
        700,
        500,
        300,
        0,
    ]
)
#: Television and lights in the evening: 0.75 kWh a day.
LIVING = Schedule(
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 100, 150, 200, 200, 100]
)
#: Hot water drawn, as heat (W): morning showers, dishes after lunch, evening.
#: 170 L a day at 40 °C from 15 °C mains, about 4.9 kWh of heat.
HOT_WATER = Schedule(
    hot_water_heat(
        [0, 0, 0, 0, 0, 0, 0, 60, 30, 0, 0, 0, 0, 0, 20, 10, 0, 0, 0, 0, 30, 20, 0, 0]
    )
)
#: Heating: 20 °C from 7 to 23 h, 16 °C setback at night.
HEATING_SETPOINT = Schedule(
    [ZERO_CELSIUS + (20.0 if 7 <= h < 23 else 16.0) for h in range(24)]
)


def madrid_flat(backend: str = "auto") -> HomeTwin:
    """A 90 m² flat in Madrid: gas heating, electric hot water.

    * Zone (2R2C): envelope 160 W/K, ventilation 40 W/K (about half an air
      change per hour), 1.5×10⁷ J/K of air and furniture, 1.2×10⁸ J/K of
      fabric coupled at 600 W/K. A 1980s brick flat.
    * Conditioning: a 24 kW gas combi boiler at 90 % on the gross calorific
      value, 20 °C by day and 16 °C at night.
    * Hot water: an 80 L electric *termo* at 60 °C, 1.5 kW, in the kitchen.
    * Electricity: 120 W base load, a kitchen and a living-room schedule.
    """
    zone = ThermalZone(
        ua=160.0,
        capacity=1.5e7,
        ventilation=40.0,
        fabric_capacity=1.2e8,
        fabric_coupling=600.0,
        temperature=ZERO_CELSIUS + 19.0,
        fabric_temperature=ZERO_CELSIUS + 17.0,
    )
    return build_home(
        zone,
        gains=[
            BaseLoad(120.0),
            Appliance(schedule=KITCHEN, name="kitchen"),
            Appliance(schedule=LIVING, name="living"),
        ],
        conditioning=[
            Boiler(
                24e3, setpoint=None, setpoint_schedule=HEATING_SETPOINT, efficiency=0.9
            )
        ],
        water_heaters=[
            (
                WaterHeater(80.0, power=1500.0, draw_schedule=HOT_WATER, name="termo"),
                "indoors",
            )
        ],
        backend=backend,
        name="madrid_flat",
    )


def seville_house(backend: str = "auto") -> HomeTwin:
    """A 110 m² house in Seville: everything electric, hot summers.

    * Zone (2R2C): envelope 180 W/K, ventilation 50 W/K, 1.6×10⁷ J/K of air,
      1.5×10⁸ J/K of fabric coupled at 700 W/K. A 1990s build.
    * Conditioning: one reversible split unit. Heating as a heat pump, 4.5 kW
      at a seasonal COP of 3.2, set to 20 °C. Cooling as an air conditioner,
      5 kW of heat removed at a seasonal EER of 2.8, set to 25 °C. Both on
      the electricity meter; there is no gas supply.
    * Hot water: an 80 L electric *termo* on the back porch (outdoors), so
      its standby loss does not heat the house.
    * Gains: 240 W base load, kitchen and living schedules, and a family of
      three (about 270 W of body heat while at home).
    """
    zone = ThermalZone(
        ua=180.0,
        capacity=1.6e7,
        ventilation=50.0,
        fabric_capacity=1.5e8,
        fabric_coupling=700.0,
        temperature=ZERO_CELSIUS + 22.0,
        fabric_temperature=ZERO_CELSIUS + 22.0,
    )
    return build_home(
        zone,
        gains=[
            BaseLoad(240.0),
            Appliance(schedule=KITCHEN, name="kitchen"),
            Appliance(schedule=LIVING, name="living"),
            Occupants(people=3.0),
        ],
        conditioning=[
            HeatPump(4.5e3, cop=3.2, setpoint=ZERO_CELSIUS + 20.0, name="heatpump"),
            AirConditioner(5e3, eer=2.8, setpoint=ZERO_CELSIUS + 25.0, name="aircon"),
        ],
        water_heaters=[
            (
                WaterHeater(80.0, power=1500.0, draw_schedule=HOT_WATER, name="termo"),
                "outdoors",
            )
        ],
        backend=backend,
        name="seville_house",
    )
