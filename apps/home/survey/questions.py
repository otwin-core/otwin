"""The questions a householder answers about their home: selectors only.

Nobody is asked for a U-value, a heat-loss coefficient or a thermal mass.
Every question is something a householder knows (how big the home is, when
it was built, what heats it, which appliances they own) and every answer is
picked from a short list. :mod:`survey.twin` turns the answers into a twin
with typical values, and calibration then corrects those values from the
home's own electricity.

:data:`QUESTIONS` is the single source of truth: the web wizard renders its
first step from :func:`questions_json`, so the page and the mapping can
never disagree about what an answer means.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

__all__ = ["Option", "Question", "QUESTIONS", "PROVINCES", "Province", "questions_json"]


@dataclass(frozen=True)
class Option:
    """One answer: the value the code uses and the words the householder reads."""

    value: str
    label: str


@dataclass(frozen=True)
class Question:
    """One selector of the first step.

    ``kind`` is ``"single"`` (pick one) or ``"multi"`` (pick any).
    """

    id: str
    label: str
    help: str
    options: tuple[Option, ...]
    default: str | tuple[str, ...]
    kind: str = "single"

    def values(self) -> tuple[str, ...]:
        """The values an answer may take."""
        return tuple(o.value for o in self.options)


@dataclass(frozen=True)
class Province:
    """A Spanish province, by its capital: for the weather and the clock."""

    value: str
    label: str
    latitude: float
    longitude: float
    timezone: str = "Europe/Madrid"


#: Province capitals, rounded to 0.01° (about 1 km: the weather grid is ~10 km).
PROVINCES: tuple[Province, ...] = tuple(
    Province(v, label, lat, lon, tz)
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
        "m",
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
        "1980_2006",
    ),
    Question(
        "heating",
        "What heats your home?",
        "Pick the main source of heat.",
        _o(
            ("heat_pump", "Heat pump (split or aerotermia)"),
            ("electric", "Electric heaters or radiators"),
            ("gas", "Gas boiler"),
            ("none", "No heating"),
        ),
        "heat_pump",
    ),
    Question(
        "cooling",
        "Do you have air conditioning?",
        "",
        _o(("no", "No"), ("yes", "Yes")),
        "no",
    ),
    Question(
        "thermostat",
        "What temperature do you keep in winter?",
        "Your usual thermostat setting during the day.",
        _o(("19", "19 °C"), ("20", "20 °C"), ("21", "21 °C"), ("22", "22 °C")),
        "20",
    ),
    Question(
        "night",
        "And at night?",
        "",
        _o(("same", "The same"), ("lower", "Lower (about 16 °C, 23:00 to 07:00)")),
        "lower",
    ),
    Question(
        "people",
        "How many people live there?",
        "",
        _o(("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5 or more")),
        "2",
    ),
    Question(
        "water",
        "What heats your hot water?",
        "",
        _o(
            ("electric", "Electric water heater (termo)"),
            ("gas", "Gas (boiler or calentador)"),
            ("unknown", "Other or not sure"),
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
            ("hob", "Electric or induction hob"),
            ("tv", "TV and computers"),
            ("ev", "Electric car charged at home"),
        ),
        ("dishwasher", "washing_machine", "oven", "tv"),
        kind="multi",
    ),
)


def questions_json() -> dict:
    """The questions and provinces as plain data, for the web wizard."""
    return {
        "questions": [
            {
                "id": q.id,
                "label": q.label,
                "help": q.help,
                "kind": q.kind,
                "default": list(q.default) if isinstance(q.default, tuple) else q.default,
                "options": [asdict(o) for o in q.options],
            }
            for q in QUESTIONS
        ],
        "provinces": [asdict(p) for p in PROVINCES],
    }
