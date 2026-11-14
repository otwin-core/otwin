"""From the householder's answers to a twin with typical values.

:class:`HomeDescription` holds the answers to :data:`survey.QUESTIONS`;
:func:`build_twin` assembles a :class:`~components.HomeTwin` from them. The
numbers it uses are *typical starting points*, not measurements: calibration
(:mod:`calibration`) replaces the ones the electricity meter can see (heat
loss, heat storage, heating size, always-on load) with the home's own.
:func:`assumptions` says, in plain words, what was assumed.

The typical values, per m² of useful floor area:

=====================================  =========================================
heat loss through the envelope         flat 2.6 / 2.0 / 1.1 W/K per m² (before
                                       1980 / 1980-2006 / 2007 on); ×1.5 for a
                                       terraced house, ×2.0 detached
ventilation                            0.45 W/K per m² (half an air change per
                                       hour, 2.6 m ceilings)
heat stored by air and furniture       1.6×10⁵ J/K per m²
heat pump                              60 W of heat per m², at least 3.5 kW;
                                       seasonal COP 3
electric heaters                       100 W per m²
gas boiler                             24 kW, 90 % on the gross calorific value
air conditioning                       60 W of cooling per m², at least 2.5 kW;
                                       seasonal EER 3; set to 25 °C
always-on electricity                  100 W plus 15 W per person
people                                 60 W of body heat each, averaged over a
                                       day of comings and goings
=====================================  =========================================
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from components import (
    ZERO_CELSIUS,
    AirConditioner,
    Appliance,
    BaseLoad,
    Boiler,
    ElectricHeater,
    HeatPump,
    HomeTwin,
    Occupants,
    Schedule,
    ThermalZone,
    WaterHeater,
    build_home,
    hot_water_heat,
)
from components.catalogue import LIVING

from .questions import PROVINCES, QUESTIONS

__all__ = ["HomeDescription", "build_twin", "assumptions", "FLOOR_AREA"]

#: Representative floor area of each size band, m².
FLOOR_AREA = {"s": 50.0, "m": 75.0, "l": 105.0, "xl": 140.0}
_UA_PER_M2 = {"pre1980": 2.6, "1980_2006": 2.0, "post2007": 1.1}  # flats, W/K per m²
_EXPOSURE = {"flat": 1.0, "terraced": 1.5, "detached": 2.0}
_VENT_PER_M2 = 0.45  # W/K per m²
_CAPACITY_PER_M2 = 1.6e5  # J/K per m²
_PERSON_W = 60.0
#: Hot water drawn by two people, litres per hour at 40 °C (170 L a day).
_HOT_WATER_2P = [
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    60,
    30,
    0,
    0,
    0,
    0,
    0,
    20,
    10,
    0,
    0,
    0,
    0,
    30,
    20,
    0,
    0,
]


def _at(hours: Mapping[int, float]) -> Schedule:
    return Schedule([float(hours.get(h, 0.0)) for h in range(24)])


#: name -> (W by hour for two people, scales with people?, heat stays indoors?)
_APPLIANCES: dict[str, tuple[dict[int, float], bool, bool]] = {
    "dishwasher": ({21: 800.0}, True, False),  # hot water down the drain
    "washing_machine": ({11: 600.0}, True, False),
    "dryer": ({12: 1000.0}, True, False),  # vented outside
    "oven": ({14: 1000.0}, False, True),
    "hob": ({14: 400.0, 21: 500.0}, True, True),
    "tv": ({}, False, True),  # the living-room schedule
    "ev": ({1: 2000.0, 2: 2000.0, 3: 2000.0}, False, False),  # charged in the garage
}


@dataclass(frozen=True)
class HomeDescription:
    """The answers to the first step of the wizard (see :data:`survey.QUESTIONS`)."""

    province: str = "madrid"
    home_type: str = "flat"
    size: str = "m"
    built: str = "1980_2006"
    heating: str = "heat_pump"
    cooling: str = "no"
    thermostat: str = "20"
    night: str = "lower"
    people: str = "2"
    water: str = "electric"
    appliances: tuple[str, ...] = field(
        default=("dishwasher", "washing_machine", "oven", "tv")
    )

    def __post_init__(self) -> None:
        apps = tuple(dict.fromkeys(self.appliances))
        object.__setattr__(self, "appliances", apps)
        for q in QUESTIONS:
            value = getattr(self, q.id)
            allowed = q.values()
            given = value if q.kind == "multi" else (value,)
            bad = [v for v in given if v not in allowed]
            if bad:
                raise ValueError(f"{q.id}: {bad[0]!r} is not one of {list(allowed)}")

    @classmethod
    def from_answers(cls, answers: Mapping[str, object]) -> HomeDescription:
        """From the wizard's answers (a dict), ignoring keys it does not know."""
        known = {q.id for q in QUESTIONS}
        kw = {k: v for k, v in answers.items() if k in known}
        if "appliances" in kw:
            kw["appliances"] = tuple(kw["appliances"])  # type: ignore[arg-type]
        return cls(**kw)  # type: ignore[arg-type]

    # ------------------------------------------------------------ derived
    @property
    def area(self) -> float:
        """Representative floor area, m²."""
        return FLOOR_AREA[self.size]

    @property
    def people_count(self) -> int:
        """Number of people."""
        return int(self.people)

    @property
    def timezone(self) -> str:
        """The province's clock."""
        return next(p.timezone for p in PROVINCES if p.value == self.province)

    @property
    def envelope_ua(self) -> float:
        """Typical heat loss through the envelope, W/K."""
        return _UA_PER_M2[self.built] * _EXPOSURE[self.home_type] * self.area

    @property
    def ventilation_ua(self) -> float:
        """Typical ventilation conductance, W/K."""
        return _VENT_PER_M2 * self.area

    @property
    def setpoint_c(self) -> float:
        """Daytime heating setpoint, °C."""
        return float(self.thermostat)


def _people_factor(desc: HomeDescription) -> float:
    return desc.people_count / 2.0


def build_twin(
    desc: HomeDescription,
    *,
    backend: str = "auto",
    with_heating: bool = True,
    with_cooling: bool = True,
    overrides: Mapping[str, float] | None = None,
) -> HomeTwin:
    """The twin of ``desc``, with typical values.

    ``with_heating``/``with_cooling`` leave a machine out (a winter month
    says nothing about an air conditioner). ``overrides`` sets model
    parameters after building, by name.
    """
    a = desc.area
    tz = desc.timezone
    zone = ThermalZone(
        desc.envelope_ua,
        _CAPACITY_PER_M2 * a,
        ventilation=desc.ventilation_ua,
        temperature=ZERO_CELSIUS + desc.setpoint_c - 1.0,
    )
    day = ZERO_CELSIUS + desc.setpoint_c
    night = ZERO_CELSIUS + (16.0 if desc.night == "lower" else desc.setpoint_c)
    setpoint = Schedule([day if 7 <= h < 23 else night for h in range(24)], tz)

    conditioning = []
    if with_heating and desc.heating != "none":
        if desc.heating == "heat_pump":
            conditioning.append(
                HeatPump(
                    max(3500.0, 60.0 * a),
                    cop=3.0,
                    setpoint=None,
                    setpoint_schedule=setpoint,
                    name="heating",
                )
            )
        elif desc.heating == "electric":
            conditioning.append(
                ElectricHeater(
                    100.0 * a, setpoint=None, setpoint_schedule=setpoint, name="heating"
                )
            )
        else:
            conditioning.append(
                Boiler(
                    24e3,
                    setpoint=None,
                    setpoint_schedule=setpoint,
                    efficiency=0.9,
                    name="heating",
                )
            )
    if with_cooling and desc.cooling == "yes":
        conditioning.append(
            AirConditioner(
                max(2500.0, 60.0 * a),
                eer=3.0,
                setpoint=ZERO_CELSIUS + 25.0,
                name="cooling",
            )
        )

    people = desc.people_count
    scale = _people_factor(desc)
    gains: list = [
        BaseLoad(100.0 + 15.0 * people),
        Occupants(float(people), watts_each=_PERSON_W),
    ]
    for name in desc.appliances:
        hours, scales, indoors = _APPLIANCES[name]
        sched = LIVING if name == "tv" else _at(hours)
        if scales:
            sched = sched.scaled(scale)
        sched = Schedule(sched.values, tz)
        gains.append(Appliance(schedule=sched, indoors=indoors, name=name))

    water = []
    if desc.water != "unknown":
        litres = 80.0 if people <= 2 else 100.0 if people <= 4 else 150.0
        draw = Schedule(hot_water_heat([v * scale for v in _HOT_WATER_2P]), tz)
        if desc.water == "electric":
            wh = WaterHeater(
                litres,
                power=1500.0 if people <= 2 else 2000.0,
                draw_schedule=draw,
                name="water_heater",
            )
        else:
            wh = WaterHeater(
                litres,
                power=8000.0,
                fuel="gas",
                efficiency=0.9,
                draw_schedule=draw,
                name="water_heater",
            )
        water.append((wh, "indoors"))

    twin = build_home(
        zone,
        gains=gains,
        conditioning=conditioning,
        water_heaters=water,
        backend=backend,
        name="your_home",
    )
    if overrides:
        twin.model.set_parameters(dict(overrides))
    return twin


def assumptions(desc: HomeDescription) -> list[str]:
    """What the twin starts from, in plain sentences. Calibration corrects these."""
    a = desc.area
    k = desc.envelope_ua + desc.ventilation_ua
    kind = {"flat": "flat", "terraced": "terraced house", "detached": "detached house"}
    era = {
        "pre1980": "built before 1980",
        "1980_2006": "built 1980–2006",
        "post2007": "built in 2007 or later",
    }
    out = [
        f"A typical {kind[desc.home_type]} of about {a:.0f} m², {era[desc.built]}, "
        f"loses about {k:.0f} W of heat for every °C between inside and outside.",
    ]
    if desc.heating == "heat_pump":
        out.append(
            f"A heat pump of about {max(3500.0, 60.0 * a) / 1000:.1f} kW, giving three "
            "units of heat per unit of electricity."
        )
    elif desc.heating == "electric":
        out.append(f"Electric heaters of about {100.0 * a / 1000:.1f} kW in total.")
    elif desc.heating == "gas":
        out.append(
            "A gas boiler. Its gas does not show on the electricity meter, so your "
            "electricity will tell us about your appliances, not your walls."
        )
    else:
        out.append("No heating.")
    night = "16 °C at night" if desc.night == "lower" else "the same at night"
    if desc.heating != "none":
        out.append(f"Heating set to {desc.thermostat} °C by day and {night}.")
    out.append(
        f"{desc.people_count} {'person' if desc.people_count == 1 else 'people'}, "
        f"{100 + 15 * desc.people_count:.0f} W always on (fridge, router, standby)."
    )
    out.append(
        "These are starting points. Calibration replaces them with what your own "
        "electricity shows."
    )
    return out
