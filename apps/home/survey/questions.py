"""The questions a householder answers about their home: selectors only.

Nobody is asked for a U-value, a heat-loss coefficient or a thermal mass.
Every question is something a householder knows (how big the home is, when
it was built, what heats it, its hot water and the hob, which appliances
they own) and every answer is
picked from a short list. :mod:`survey.twin` turns the answers into a twin
with typical values, and calibration then corrects those values from the
home's own electricity.

:data:`QUESTIONS` is the single source of truth: the web wizard renders its
first step from :func:`questions_json`, so the page and the mapping can
never disagree about what an answer means.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = [
    "Option",
    "Question",
    "QUESTIONS",
    "PROVINCES",
    "Province",
    "questions_json",
    "SPANISH",
    "LANGUAGES",
]


@dataclass(frozen=True)
class Option:
    """One answer: the value the code uses and the words the householder reads."""

    value: str
    label: str


@dataclass(frozen=True)
class Question:
    """One selector of the first step.

    ``kind`` says how it is answered, and the page draws the same control
    for it everywhere (the questions, a simulation):

    * ``"single"``: pick one option (three or fewer: a three-way selector;
      more: a row of buttons; many: a list);
    * ``"multi"``: any of the options, one switch each;
    * ``"switch"``: two options, off and on;
    * ``"slider"``: a number between ``minimum`` and ``maximum`` in steps of
      ``step``, with ``unit``; the options, if any, are legacy names for
      numbers (``"m"`` for 75 m²) still accepted;
    * ``"gauge"``: a temperature, drawn as a semicircle from blue to red.
    """

    id: str
    label: str
    help: str
    options: tuple[Option, ...]
    default: str | tuple[str, ...]
    kind: str = "single"
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str = ""

    def values(self) -> tuple[str, ...]:
        """The values an answer may take, as options (not numbers)."""
        return tuple(o.value for o in self.options)

    @property
    def numeric(self) -> bool:
        return self.kind in ("slider", "gauge")

    def accepts(self, value: object) -> bool:
        """Is ``value`` an answer to this question?"""
        if value in self.values():
            return True
        if not self.numeric:
            return False
        try:
            v = float(str(value))
        except (TypeError, ValueError):
            return False
        return self.minimum <= v <= self.maximum  # type: ignore[operator]


@dataclass(frozen=True)
class Province:
    """A Spanish province, by its capital: for the weather and the clock."""

    value: str
    label: str
    latitude: float
    longitude: float
    timezone: str = "Europe/Madrid"
    #: A typical January's mean temperature in the capital, °C (approximate
    #: AEMET normals, rounded): only for the estimate before any data.
    january_c: float = 7.0


_JANUARY_C = {
    "a_coruna": 10.2,
    "alava": 4.6,
    "albacete": 4.6,
    "alicante": 11.6,
    "almeria": 12.5,
    "asturias": 7.6,
    "avila": 3.1,
    "badajoz": 8.7,
    "baleares": 11.6,
    "barcelona": 9.6,
    "bizkaia": 9.0,
    "burgos": 2.9,
    "caceres": 7.8,
    "cadiz": 12.8,
    "cantabria": 9.7,
    "castellon": 10.4,
    "ceuta": 13.0,
    "ciudad_real": 5.5,
    "cordoba": 9.5,
    "cuenca": 4.2,
    "gipuzkoa": 8.0,
    "girona": 6.6,
    "granada": 6.8,
    "guadalajara": 5.3,
    "huelva": 11.6,
    "huesca": 4.9,
    "jaen": 8.5,
    "la_rioja": 5.6,
    "las_palmas": 18.0,
    "leon": 3.2,
    "lleida": 5.2,
    "lugo": 5.7,
    "madrid": 6.3,
    "malaga": 12.1,
    "melilla": 13.2,
    "murcia": 11.0,
    "navarra": 4.9,
    "ourense": 7.4,
    "palencia": 3.9,
    "pontevedra": 9.5,
    "salamanca": 3.7,
    "santa_cruz": 18.2,
    "segovia": 3.6,
    "sevilla": 10.9,
    "soria": 2.7,
    "tarragona": 10.2,
    "teruel": 3.8,
    "toledo": 6.4,
    "valencia": 11.5,
    "valladolid": 4.1,
    "zamora": 4.1,
    "zaragoza": 6.6,
}

#: Province capitals, rounded to 0.01° (about 1 km: the weather grid is ~10 km).
PROVINCES: tuple[Province, ...] = tuple(
    Province(v, label, lat, lon, tz, _JANUARY_C[v])
    for v, label, lat, lon, tz in [
        ("a_coruna", "A Coruña", 43.36, -8.41, "Europe/Madrid"),
        ("alava", "Álava", 42.85, -2.67, "Europe/Madrid"),
        ("albacete", "Albacete", 38.99, -1.86, "Europe/Madrid"),
        ("alicante", "Alicante", 38.35, -0.48, "Europe/Madrid"),
        ("almeria", "Almería", 36.84, -2.46, "Europe/Madrid"),
        ("asturias", "Asturias", 43.36, -5.85, "Europe/Madrid"),
        ("avila", "Ávila", 40.66, -4.70, "Europe/Madrid"),
        ("badajoz", "Badajoz", 38.88, -6.97, "Europe/Madrid"),
        ("baleares", "Illes Balears", 39.57, 2.65, "Europe/Madrid"),
        ("barcelona", "Barcelona", 41.39, 2.17, "Europe/Madrid"),
        ("bizkaia", "Bizkaia", 43.26, -2.93, "Europe/Madrid"),
        ("burgos", "Burgos", 42.34, -3.70, "Europe/Madrid"),
        ("caceres", "Cáceres", 39.47, -6.37, "Europe/Madrid"),
        ("cadiz", "Cádiz", 36.53, -6.29, "Europe/Madrid"),
        ("cantabria", "Cantabria", 43.46, -3.80, "Europe/Madrid"),
        ("castellon", "Castellón", 39.99, -0.05, "Europe/Madrid"),
        ("ceuta", "Ceuta", 35.89, -5.32, "Europe/Madrid"),
        ("ciudad_real", "Ciudad Real", 38.99, -3.93, "Europe/Madrid"),
        ("cordoba", "Córdoba", 37.89, -4.78, "Europe/Madrid"),
        ("cuenca", "Cuenca", 40.07, -2.13, "Europe/Madrid"),
        ("gipuzkoa", "Gipuzkoa", 43.32, -1.98, "Europe/Madrid"),
        ("girona", "Girona", 41.98, 2.82, "Europe/Madrid"),
        ("granada", "Granada", 37.18, -3.60, "Europe/Madrid"),
        ("guadalajara", "Guadalajara", 40.63, -3.16, "Europe/Madrid"),
        ("huelva", "Huelva", 37.26, -6.94, "Europe/Madrid"),
        ("huesca", "Huesca", 42.14, -0.41, "Europe/Madrid"),
        ("jaen", "Jaén", 37.78, -3.79, "Europe/Madrid"),
        ("la_rioja", "La Rioja", 42.47, -2.45, "Europe/Madrid"),
        ("las_palmas", "Las Palmas", 28.12, -15.43, "Atlantic/Canary"),
        ("leon", "León", 42.60, -5.57, "Europe/Madrid"),
        ("lleida", "Lleida", 41.62, 0.62, "Europe/Madrid"),
        ("lugo", "Lugo", 43.01, -7.56, "Europe/Madrid"),
        ("madrid", "Madrid", 40.42, -3.70, "Europe/Madrid"),
        ("malaga", "Málaga", 36.72, -4.42, "Europe/Madrid"),
        ("melilla", "Melilla", 35.29, -2.94, "Europe/Madrid"),
        ("murcia", "Murcia", 37.99, -1.13, "Europe/Madrid"),
        ("navarra", "Navarra", 42.81, -1.64, "Europe/Madrid"),
        ("ourense", "Ourense", 42.34, -7.86, "Europe/Madrid"),
        ("palencia", "Palencia", 42.01, -4.53, "Europe/Madrid"),
        ("pontevedra", "Pontevedra", 42.43, -8.64, "Europe/Madrid"),
        ("salamanca", "Salamanca", 40.97, -5.66, "Europe/Madrid"),
        ("santa_cruz", "Santa Cruz de Tenerife", 28.46, -16.25, "Atlantic/Canary"),
        ("segovia", "Segovia", 40.95, -4.12, "Europe/Madrid"),
        ("sevilla", "Sevilla", 37.39, -5.98, "Europe/Madrid"),
        ("soria", "Soria", 41.76, -2.46, "Europe/Madrid"),
        ("tarragona", "Tarragona", 41.12, 1.25, "Europe/Madrid"),
        ("teruel", "Teruel", 40.34, -1.11, "Europe/Madrid"),
        ("toledo", "Toledo", 39.86, -4.03, "Europe/Madrid"),
        ("valencia", "Valencia", 39.47, -0.38, "Europe/Madrid"),
        ("valladolid", "Valladolid", 41.65, -4.72, "Europe/Madrid"),
        ("zamora", "Zamora", 41.50, -5.74, "Europe/Madrid"),
        ("zaragoza", "Zaragoza", 41.65, -0.89, "Europe/Madrid"),
    ]
)


def _o(*pairs: tuple[str, str]) -> tuple[Option, ...]:
    return tuple(Option(v, label) for v, label in pairs)


QUESTIONS: tuple[Question, ...] = (
    Question(
        "province",
        "Where is your home?",
        "Your province sets the weather and the clock. Nothing else is used.",
        tuple(Option(p.value, p.label) for p in PROVINCES),
        "madrid",
    ),
    Question(
        "home_type",
        "What kind of home is it?",
        "A flat shares walls with its neighbours, so it loses less heat.",
        _o(
            ("flat", "Flat"),
            ("terraced", "Terraced or semi-detached house"),
            ("detached", "Detached house"),
        ),
        "flat",
    ),
    Question(
        "size",
        "How big is it?",
        "The useful floor area, as on the deed or the energy certificate.",
        _o(
            ("s", "Under 60 m²"),
            ("m", "60–90 m²"),
            ("l", "90–120 m²"),
            ("xl", "Over 120 m²"),
        ),
        "75",
        kind="slider",
        minimum=30,
        maximum=250,
        step=5,
        unit="m²",
    ),
    Question(
        "built",
        "When was it built?",
        "Older buildings usually have little insulation.",
        _o(
            ("pre1980", "Before 1980"),
            ("1980_2006", "1980–2006"),
            ("post2007", "2007 or later"),
        ),
        "1995",
        kind="slider",
        minimum=1900,
        maximum=2026,
        step=1,
    ),
    Question(
        "heating",
        "What heats your home?",
        "Pick the main source of heat.",
        _o(
            ("heat_pump", "Heat pump (split or aerotermia)"),
            ("electric", "Electric heaters or radiators"),
            ("gas", "Gas boiler (natural gas)"),
            ("none", "No heating"),
        ),
        "heat_pump",
    ),
    Question(
        "heating_power",
        "How powerful is your heating?",
        "The useful heat output on the nameplate of the boiler, the heat pump or the sum of the heaters, in kW. Real homes have systems bigger or smaller than they need, and the twin is built on the one you have.",
        _o(
            ("auto", "I don't know: use a typical size"),
            *((str(k), f"{k} kW") for k in (3, 4, 5, 6, 8, 10, 12, 15, 18, 24, 30, 35)),
        ),
        "auto",
        kind="slider",
        minimum=0,
        maximum=40,
        step=1,
        unit="kW",
    ),
    Question(
        "cooling",
        "Do you have air conditioning?",
        "",
        _o(("no", "No"), ("yes", "Yes")),
        "no",
        kind="switch",
    ),
    Question(
        "cooling_setpoint",
        "What temperature do you set the air conditioning to?",
        "Only if you have air conditioning.",
        _o(*((str(c), f"{c} °C") for c in (23, 24, 25, 26, 27))),
        "25",
        kind="gauge",
        minimum=22,
        maximum=28,
        step=0.5,
        unit="°C",
    ),
    Question(
        "thermostat",
        "What temperature do you keep in winter?",
        "Your usual thermostat setting during the day.",
        _o(("19", "19 °C"), ("20", "20 °C"), ("21", "21 °C"), ("22", "22 °C")),
        "20",
        kind="gauge",
        minimum=16,
        maximum=26,
        step=0.5,
        unit="°C",
    ),
    Question(
        "night",
        "Lower at night?",
        "About 16 °C from 23:00 to 07:00, as most thermostats do when set to.",
        _o(("same", "No, the same"), ("lower", "Yes, lower")),
        "lower",
        kind="switch",
    ),
    Question(
        "people",
        "How many people live there?",
        "",
        _o(("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5 or more")),
        "2",
        kind="slider",
        minimum=1,
        maximum=6,
        step=1,
    ),
    Question(
        "water",
        "What heats your hot water?",
        "Showers, taps and the kitchen sink.",
        _o(
            ("boiler", "The gas boiler (the same one that heats the home)"),
            ("gas", "A separate gas water heater (calentador)"),
            ("electric", "Electric water heater (termo)"),
            ("heat_pump", "Heat-pump water heater (aerotermia)"),
            ("unknown", "Other or not sure"),
        ),
        "electric",
    ),
    Question(
        "cooking",
        "How do you cook?",
        "The hob you use most days.",
        _o(
            ("electric", "Electric or induction hob"),
            ("gas", "Gas hob, piped natural gas"),
            ("butane", "Gas hob, bottled butane"),
        ),
        "electric",
    ),
    Question(
        "appliances",
        "Which of these do you use regularly?",
        "The fridge is always counted. Pick the rest.",
        _o(
            ("dishwasher", "Dishwasher"),
            ("washing_machine", "Washing machine"),
            ("dryer", "Tumble dryer"),
            ("oven", "Electric oven"),
            ("tv", "TV and computers"),
            ("ev", "Electric car charged at home"),
        ),
        ("dishwasher", "washing_machine", "oven", "tv"),
        kind="multi",
    ),
)


#: The questions in Spanish: every English text above, as a Spanish
#: speaker reads it. A text missing here shows in English (and a test fails).
SPANISH: dict[str, str] = {
    "How powerful is your heating?": "¿Qué potencia tiene tu calefacción?",
    (
        "The useful heat output on the nameplate of the boiler, the heat pump or the "
        "sum of the heaters, in kW. Real homes have systems bigger or smaller than "
        "they need, and the twin is built on the one you have."
    ): (
        "La potencia útil que figura en la placa de la caldera, de la bomba de calor "
        "o la suma de los radiadores, en kW. En las casas reales hay sistemas más "
        "grandes o más pequeños de lo necesario, y el gemelo se construye con el que "
        "tienes."
    ),
    "I don't know: use a typical size": "No lo sé: usa un tamaño típico",
    "Lower at night?": "¿Más baja por la noche?",
    "About 16 °C from 23:00 to 07:00, as most thermostats do when set to.": (
        "Unos 16 °C de 23:00 a 07:00, como hacen casi todos los termostatos si se les pide."
    ),
    "No, the same": "No, la misma",
    "Yes, lower": "Sí, más baja",
    "What temperature do you set the air conditioning to?": (
        "¿A qué temperatura pones el aire acondicionado?"
    ),
    "Only if you have air conditioning.": "Solo si tienes aire acondicionado.",
    **{f"{c} °C": f"{c} °C" for c in (23, 24, 25, 26, 27)},
    **{f"{k} kW": f"{k} kW" for k in (3, 4, 5, 6, 8, 10, 12, 15, 18, 24, 30, 35)},
    "Where is your home?": "¿Dónde está tu casa?",
    "Your province sets the weather and the clock. Nothing else is used.": (
        "Tu provincia fija el tiempo y la hora. No se usa para nada más."
    ),
    "What kind of home is it?": "¿Qué tipo de vivienda es?",
    "A flat shares walls with its neighbours, so it loses less heat.": (
        "Un piso comparte paredes con los vecinos, así que pierde menos calor."
    ),
    "Flat": "Piso",
    "Terraced or semi-detached house": "Casa adosada o pareada",
    "Detached house": "Casa independiente",
    "How big is it?": "¿Qué tamaño tiene?",
    "The useful floor area, as on the deed or the energy certificate.": (
        "La superficie útil, como en la escritura o el certificado energético."
    ),
    "Under 60 m²": "Menos de 60 m²",
    "60–90 m²": "60–90 m²",
    "90–120 m²": "90–120 m²",
    "Over 120 m²": "Más de 120 m²",
    "When was it built?": "¿Cuándo se construyó?",
    "Older buildings usually have little insulation.": (
        "Los edificios antiguos suelen tener poco aislamiento."
    ),
    "Before 1980": "Antes de 1980",
    "1980–2006": "1980–2006",
    "2007 or later": "2007 o después",
    "What heats your home?": "¿Con qué calientas tu casa?",
    "Pick the main source of heat.": "Elige la fuente principal de calor.",
    "Heat pump (split or aerotermia)": "Bomba de calor (split o aerotermia)",
    "Electric heaters or radiators": "Radiadores o estufas eléctricas",
    "Gas boiler (natural gas)": "Caldera de gas natural",
    "No heating": "Sin calefacción",
    "Do you have air conditioning?": "¿Tienes aire acondicionado?",
    "No": "No",
    "Yes": "Sí",
    "What temperature do you keep in winter?": "¿A qué temperatura tienes la casa en invierno?",
    "Your usual thermostat setting during the day.": (
        "Lo que sueles poner en el termostato durante el día."
    ),
    "19 °C": "19 °C",
    "20 °C": "20 °C",
    "21 °C": "21 °C",
    "22 °C": "22 °C",
    "And at night?": "¿Y por la noche?",
    "The same": "Igual",
    "Lower (about 16 °C, 23:00 to 07:00)": "Más baja (unos 16 °C, de 23:00 a 07:00)",
    "How many people live there?": "¿Cuántas personas viven en ella?",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5 or more": "5 o más",
    "What heats your hot water?": "¿Con qué calientas el agua caliente?",
    "Showers, taps and the kitchen sink.": "Duchas, grifos y el fregadero.",
    "The gas boiler (the same one that heats the home)": (
        "La caldera de gas (la misma de la calefacción)"
    ),
    "A separate gas water heater (calentador)": "Un calentador de gas aparte",
    "Electric water heater (termo)": "Termo eléctrico",
    "Heat-pump water heater (aerotermia)": "Termo de bomba de calor (aerotermia)",
    "Other or not sure": "Otro o no lo sé",
    "How do you cook?": "¿Cómo cocinas?",
    "The hob you use most days.": "La placa que usas casi todos los días.",
    "Electric or induction hob": "Placa eléctrica o de inducción",
    "Gas hob, piped natural gas": "Cocina de gas natural (de red)",
    "Gas hob, bottled butane": "Cocina de gas butano (bombona)",
    "Which of these do you use regularly?": "¿Cuáles de estos usas habitualmente?",
    "The fridge is always counted. Pick the rest.": (
        "La nevera siempre se cuenta. Elige el resto."
    ),
    "Dishwasher": "Lavavajillas",
    "Washing machine": "Lavadora",
    "Tumble dryer": "Secadora",
    "Electric oven": "Horno eléctrico",
    "TV and computers": "Televisión y ordenadores",
    "Electric car charged at home": "Coche eléctrico cargado en casa",
}
LANGUAGES = ("en", "es")


def _tr(text: str, lang: str) -> str:
    if lang == "es" and text:
        return SPANISH.get(text, text)
    return text


def questions_json(lang: str = "en") -> dict:
    """The questions and provinces as plain data, for the web wizard, in
    ``lang`` (``"en"`` or ``"es"``)."""
    if lang not in LANGUAGES:
        raise ValueError(f"lang must be one of {LANGUAGES}, not {lang!r}")
    return {
        "questions": [
            {
                "id": q.id,
                "label": _tr(q.label, lang),
                "help": _tr(q.help, lang),
                "kind": q.kind,
                "minimum": q.minimum,
                "maximum": q.maximum,
                "step": q.step,
                "unit": q.unit,
                "default": list(q.default) if isinstance(q.default, tuple) else q.default,
                "options": [
                    {"value": o.value, "label": _tr(o.label, lang)} for o in q.options
                ],
            }
            for q in QUESTIONS
        ],
        "provinces": [asdict(p) for p in PROVINCES],
    }
