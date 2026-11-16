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
radiation to the sky                   ISO 13790 §11.4.6: the envelope faces air
                                       R_se·h_r·Δθ_er·F_r colder (0.04 m²K/W,
                                       4.6 W/m²K, 11 K); F_r is 0.5 for a flat's
                                       facades, about 0.6 for a house (roof 1,
                                       walls 0.5, ground floor 0): about 1.0 and
                                       1.2 K
heat pump                              60 W of heat per m², at least 3.5 kW;
                                       seasonal COP 3
electric heaters                       100 W per m²
gas boiler                             24 kW, 90 % on the gross calorific value
hot water                              170 L a day at 40 °C for two people, in
                                       proportion to people; a store of 80 L
                                       (1-2 people), 100 L (3-4) or 150 L (5+)
  electric *termo*                     1.5 kW (2 kW for 3+ people), 100 %
  heat-pump water heater               the same, 2.5 units of heat per unit of
                                       electricity
  the gas boiler, or a *calentador*    8 kW burner, 90 % (boiler) or 85 %
                                       (*calentador*), on the gas meter
cooking                                electric or induction hob: 0.9 kWh a
                                       day for two people; a gas hob burns
                                       twice that (about 45 % of a flame's
                                       heat reaches the pan, 85-90 % of an
                                       induction hob's); butane shows on no
                                       meter but still warms the kitchen
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
    GasAppliance,
    HeatGain,
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
from components.exchanges import VIEW_FACTOR, sky_depression

from .questions import PROVINCES, QUESTIONS

__all__ = ["HomeDescription", "build_twin", "assumptions", "home_summary", "FLOOR_AREA"]

#: Representative floor area of each size band, m².
FLOOR_AREA = {"s": 50.0, "m": 75.0, "l": 105.0, "xl": 140.0}
_UA_PER_M2 = {"pre1980": 2.6, "1980_2006": 2.0, "post2007": 1.1}  # flats, W/K per m²
_EXPOSURE = {"flat": 1.0, "terraced": 1.5, "detached": 2.0}
_VENT_PER_M2 = 0.45  # W/K per m²
#: Where each kind of home loses heat through its envelope, as shares of its
#: UA, for the radiation to the sky. A flat (not on the top floor) has only
#: its facades outside: its roof and floor are its neighbours'. A terraced
#: house has two facades, a roof and a ground floor; a detached one four
#: facades (more wall per m²), a roof and a ground floor.
SKY_VIEW: dict[str, dict[str, float]] = {
    "flat": {"wall": 1.0},
    "terraced": {"wall": 0.6, "roof": 0.3, "ground": 0.1},
    "detached": {"wall": 0.55, "roof": 0.3, "ground": 0.15},
}
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
    "tv": ({}, False, True),  # the living-room schedule
    "ev": ({1: 2000.0, 2: 2000.0, 3: 2000.0}, False, False),  # charged in the garage
}


#: The hob, W by hour for two people: what reaches the kitchen as heat. An
#: induction or ceramic hob draws this from the electricity meter; a gas
#: flame, about half as efficient at heating the pan, burns twice as much.
_HOB_2P = {14: 400.0, 21: 500.0}
_GAS_HOB_FACTOR = 2.0
#: Hot-water machines: (fuel, efficiency, standby loss W/K).
_WATER = {
    "electric": ("electricity", 1.0, 1.1),
    "heat_pump": ("electricity", 2.5, 1.1),
    "boiler": ("gas", 0.9, 0.5),  # heats on demand: no tank to lose heat from
    "gas": ("gas", 0.85, 0.5),
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
    cooking: str = "electric"
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
            apps = tuple(kw["appliances"])  # type: ignore[arg-type]
            if "hob" in apps:
                # answers saved before the hob had its own question
                apps = tuple(a for a in apps if a != "hob")
                kw.setdefault("cooking", "electric")
            kw["appliances"] = apps
        return cls(**kw)  # type: ignore[arg-type]

    @property
    def uses_gas(self) -> bool:
        """Does anything in the home run on piped gas (a gas bill to read)?"""
        return (
            self.heating == "gas"
            or self.water in ("boiler", "gas")
            or self.cooking == "gas"
        )

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
    def sky_view(self) -> float:
        """How much of the sky the envelope sees, weighted by where it loses
        heat (see :data:`SKY_VIEW`)."""
        return sum(
            share * VIEW_FACTOR[part] for part, share in SKY_VIEW[self.home_type].items()
        )

    @property
    def sky_depression(self) -> float:
        """The envelope's radiation to the sky as a temperature step, K."""
        return sky_depression(self.sky_view)

    @property
    def radiation_w(self) -> float:
        """Typical radiation loss to the sky, W: ``UA · depression``."""
        return self.envelope_ua * self.sky_depression

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
        sky=desc.sky_depression,
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

    tz_hob = Schedule(_at(_HOB_2P).scaled(scale).values, tz)
    if desc.cooking == "electric":
        gains.append(Appliance(schedule=tz_hob, name="hob"))
    elif desc.cooking == "gas":
        gains.append(
            GasAppliance(
                schedule=Schedule(tz_hob.scaled(_GAS_HOB_FACTOR).values, tz), name="hob"
            )
        )
    else:  # butane: on no meter, but the kitchen still gets the heat
        gains.append(
            HeatGain(
                schedule=Schedule(tz_hob.scaled(_GAS_HOB_FACTOR).values, tz), name="hob"
            )
        )

    water = []
    if desc.water != "unknown":
        litres = 80.0 if people <= 2 else 100.0 if people <= 4 else 150.0
        draw = Schedule(hot_water_heat([v * scale for v in _HOT_WATER_2P]), tz)
        fuel, eff, loss = _WATER[desc.water]
        power = (1500.0 if people <= 2 else 2000.0) if fuel == "electricity" else 8000.0
        wh = WaterHeater(
            litres,
            power=power,
            fuel=fuel,
            efficiency=eff,
            loss_ua=loss,
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


_KIND = {
    "flat": "A flat",
    "terraced": "A terraced or semi-detached house",
    "detached": "A detached house",
}
_BUILT = {
    "pre1980": "built before 1980",
    "1980_2006": "built between 1980 and 2006",
    "post2007": "built in 2007 or later",
}
_INSULATION = {
    "pre1980": "Probably little, as in most homes built before 1980.",
    "1980_2006": "Some, as in most homes built between 1980 and 2006.",
    "post2007": "Good, as required for homes built since 2007.",
}
_HEATING = {
    "heat_pump": "A heat pump",
    "electric": "Electric heaters",
    "gas": "A gas boiler",
}
_WATER_TEXT = {
    "boiler": "From the gas boiler that heats the home.",
    "gas": "From a gas water heater (calentador).",
    "electric": "From an electric water heater (termo).",
    "heat_pump": "From a heat-pump water heater.",
    "unknown": "Not counted: you were not sure what heats it.",
}
_COOKING_TEXT = {
    "electric": "On an electric or induction hob.",
    "gas": "On a gas hob, with piped gas.",
    "butane": "On a gas hob with bottled butane, which shows on no bill.",
}
_APPLIANCE_NAMES = {
    "dishwasher": "dishwasher",
    "washing_machine": "washing machine",
    "dryer": "tumble dryer",
    "oven": "electric oven",
    "tv": "TV and computers",
    "ev": "electric car",
}


def _join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _sky_text(desc: HomeDescription) -> str:
    w = round(desc.radiation_w / 10.0) * 10
    if desc.home_type == "flat":
        return (
            f"About {w:.0f} W, through the facades only: the roof and floor of a flat "
            "are its neighbours', and a wall sees just half of the sky."
        )
    return (
        f"About {w:.0f} W: the roof sees the whole cold night sky and the walls half "
        "of it, so a house loses much more this way than a flat."
    )


def home_summary(desc: HomeDescription, lang: str = "en") -> list[tuple[str, str]]:
    """The home as the householder described it, in plain words.

    One ``(topic, text)`` pair per line, for a general audience: no heat
    losses, no kilowatts. The last pair says which bills to bring.
    ``lang`` is ``"en"`` or ``"es"``.
    """
    if lang == "es":
        return _home_summary_es(desc)
    if lang != "en":
        raise ValueError(f"lang must be 'en' or 'es', not {lang!r}")
    province = next(p.label for p in PROVINCES if p.value == desc.province)
    n = desc.people_count
    people = (
        "1 person lives"
        if n == 1
        else f"{n} people live"
        if n < 5
        else ("5 or more people live")
    )
    rows = [
        (
            "Your home",
            f"{_KIND[desc.home_type]} of about {desc.area:.0f} m² in {province}, "
            f"{_BUILT[desc.built]}. {people} there.",
        ),
        ("Insulation", _INSULATION[desc.built]),
        ("Heat lost to the sky", _sky_text(desc)),
    ]
    if desc.heating == "none":
        rows.append(("Heating", "None."))
    else:
        night = "16 °C at night" if desc.night == "lower" else "the same at night"
        rows.append(
            (
                "Heating",
                f"{_HEATING[desc.heating]}, at {desc.thermostat} °C by day and {night}.",
            )
        )
    rows.append(("Hot water", _WATER_TEXT[desc.water]))
    rows.append(("Cooking", _COOKING_TEXT[desc.cooking]))
    rows.append(
        ("Air conditioning", "Yes, set to 25 °C." if desc.cooling == "yes" else "None.")
    )
    apps = ["Fridge"] + [_APPLIANCE_NAMES[a] for a in desc.appliances]
    rows.append(("Appliances", f"{', '.join(apps)}, plus what is always plugged in."))
    on_gas = [
        what
        for what, yes in (
            ("heating", desc.heating == "gas"),
            ("hot water", desc.water in ("boiler", "gas")),
            ("cooking", desc.cooking == "gas"),
        )
        if yes
    ]
    if on_gas:
        bills = (
            f"Your hourly electricity and a gas bill for the same month, because "
            f"your {_join(on_gas)} {'is' if len(on_gas) == 1 else 'are'} on gas. "
            "Your water bill too, if you have it."
        )
    else:
        bills = (
            "Your hourly electricity for one month. Everything runs on electricity, "
            "so no gas bill is needed. Your water bill too, if you have it."
        )
    rows.append(("Bills to bring", bills))
    return rows


_KIND_ES = {
    "flat": "Un piso",
    "terraced": "Una casa adosada o pareada",
    "detached": "Una casa independiente",
}
_BUILT_ES = {
    "pre1980": "construido antes de 1980",
    "1980_2006": "construido entre 1980 y 2006",
    "post2007": "construido en 2007 o después",
}
_INSULATION_ES = {
    "pre1980": "Probablemente poco, como en la mayoría de viviendas anteriores a 1980.",
    "1980_2006": "Algo, como en la mayoría de viviendas de 1980 a 2006.",
    "post2007": "Bueno, como se exige a las viviendas construidas desde 2007.",
}
_HEATING_ES = {
    "heat_pump": "Una bomba de calor",
    "electric": "Radiadores eléctricos",
    "gas": "Una caldera de gas",
}
_WATER_ES = {
    "boiler": "De la caldera de gas que calienta la casa.",
    "gas": "De un calentador de gas.",
    "electric": "De un termo eléctrico.",
    "heat_pump": "De un termo de bomba de calor.",
    "unknown": "No se cuenta: no sabías con qué se calienta.",
}
_COOKING_ES = {
    "electric": "En una placa eléctrica o de inducción.",
    "gas": "En una cocina de gas natural.",
    "butane": "En una cocina de butano, que no aparece en ninguna factura.",
}
_APPLIANCES_ES = {
    "dishwasher": "lavavajillas",
    "washing_machine": "lavadora",
    "dryer": "secadora",
    "oven": "horno eléctrico",
    "tv": "televisión y ordenadores",
    "ev": "coche eléctrico",
}


def _join_es(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def _home_summary_es(desc: HomeDescription) -> list[tuple[str, str]]:
    province = next(p.label for p in PROVINCES if p.value == desc.province)
    n = desc.people_count
    people = (
        "Vive 1 persona"
        if n == 1
        else f"Viven {n} personas"
        if n < 5
        else ("Viven 5 personas o más")
    )
    w = round(desc.radiation_w / 10.0) * 10
    sky = (
        f"Unos {w:.0f} W, solo por las fachadas: el techo y el suelo de un piso son "
        "los de los vecinos, y una pared ve solo la mitad del cielo."
        if desc.home_type == "flat"
        else f"Unos {w:.0f} W: el tejado ve todo el cielo frío de la noche y las "
        "paredes la mitad, así que una casa pierde mucho más así que un piso."
    )
    rows = [
        (
            "Tu casa",
            f"{_KIND_ES[desc.home_type]} de unos {desc.area:.0f} m² en {province}, "
            # a piso is masculine, a casa feminine
            + (
                _BUILT_ES[desc.built]
                if desc.home_type == "flat"
                else _BUILT_ES[desc.built].replace("construido", "construida")
            )
            + f". {people} en ella.",
        ),
        ("Aislamiento", _INSULATION_ES[desc.built]),
        ("Calor que se va al cielo", sky),
    ]
    if desc.heating == "none":
        rows.append(("Calefacción", "Ninguna."))
    else:
        night = "16 °C por la noche" if desc.night == "lower" else "lo mismo por la noche"
        rows.append(
            (
                "Calefacción",
                f"{_HEATING_ES[desc.heating]}, a {desc.thermostat} °C de día y {night}.",
            )
        )
    rows.append(("Agua caliente", _WATER_ES[desc.water]))
    rows.append(("Cocina", _COOKING_ES[desc.cooking]))
    rows.append(
        (
            "Aire acondicionado",
            "Sí, a 25 °C." if desc.cooling == "yes" else "No.",
        )
    )
    apps = ["Nevera"] + [_APPLIANCES_ES[a] for a in desc.appliances]
    rows.append(("Aparatos", f"{', '.join(apps)}, y lo que está siempre enchufado."))
    on_gas = [
        what
        for what, yes in (
            ("la calefacción", desc.heating == "gas"),
            ("el agua caliente", desc.water in ("boiler", "gas")),
            ("la cocina", desc.cooking == "gas"),
        )
        if yes
    ]
    if on_gas:
        verb = "funciona" if len(on_gas) == 1 else "funcionan"
        bills = (
            f"Tu consumo eléctrico por horas y una factura de gas del mismo mes, porque "
            f"{_join_es(on_gas)} {verb} con gas. También tu factura del agua, si la tienes."
        )
    else:
        bills = (
            "Tu consumo eléctrico por horas de un mes. Todo funciona con electricidad, "
            "así que no hace falta factura de gas. También tu factura del agua, si la tienes."
        )
    rows.append(("Qué facturas traer", bills))
    return rows


def assumptions(desc: HomeDescription) -> list[str]:
    """:func:`home_summary` as sentences, ending with what calibration will do."""
    out = [f"{topic}: {text}" for topic, text in home_summary(desc)]
    out.append(
        "These are typical figures for a home like yours. Your own bills will "
        "correct them."
    )
    return out
