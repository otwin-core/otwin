"""The wizard's sample files: homes whose answers are known.

**An all-electric flat, January 2026** (this folder). The "real" home is the
survey's answers in ``home.json`` with four values the survey cannot know
set differently from its typical guesses (it loses 25 % more heat, stores
20 % less, has a 5.2 kW heat pump and a 175 W always-on load):

* ``consumo_horario_enero_2026.csv``: hourly electricity, the CNMC/Datadis
  CSV shape (``CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion``), a real
  household's noise, a few estimated hours;
* ``estacion_meteo_enero_2026.csv``: a home weather station's export, a
  layout no parser knows: the wizard's column mapper reads it;
* ``open_meteo_enero_2026.json``: the same weather as Open-Meteo gives it,
  read without any mapping;
* ``termometro_interior_enero_2026.csv``: the interior thermometer's log, a
  reading every ten minutes.

**A gas home, three winter periods** (``gas_home/``). A 105 m² flat in
Madrid from before 1980, three people, a gas combi boiler for heating and
hot water and a gas hob (``gas_home/home.json``). The survey guesses it
loses 273 W per °C, as a flat of its age typically does; this one had its
windows replaced and loses 20 % less (218 W per °C), stores 20 % more heat,
and has a 160 W always-on load. Three billing periods of one heating season,
each simulated over its own weather (Madrid's normals with passing spells):

==================  ====================================  ======
folder              period (meter-reading dates)          days
==================  ====================================  ======
``15oct-15nov``     15 Oct 2025 to 15 Nov 2025            31 (the clocks go back on 26 Oct)
``15dic-15ene``     15 Dec 2025 to 15 Jan 2026            31
``15feb-15mar``     15 Feb 2026 to 15 Mar 2026            28
==================  ====================================  ======

Each folder holds five files to drop into the wizard together:

* ``consumo_horario_<period>.csv``: the hourly electricity, CNMC shape;
* ``factura_gas_<period>.csv``: the gas bill as printed: the two meter
  readings (whole m³), the conversion factor Fc and the calorific value
  PCS, and the kWh billed, which is m³ × Fc × PCS;
* ``factura_agua_<period>.csv``: the water bill, two readings in m³;
* ``open_meteo_<period>.json``: the outdoor temperature, Open-Meteo shape;
* ``termometro_interior_<period>.csv``: the interior thermometer's log, a
  reading every ten minutes, local time with its UTC offset.

**These are the records for each example's own answers** (``home.json``).
The real homes are in ``truth.json`` (how each differs from the survey's
guess), and :mod:`survey.example` simulates them. When the wizard
calibrates an example, it simulates the same real home again from the
answers on the page, so the electricity, the gas bills and the
thermometer follow the thermostat chosen there, by day and at night.

The wizard's "Try it with example files" loads these, and the end-to-end
checks calibrate on them. Regenerate with::

    python apps/home/web/samples/make_samples.py
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from calibration import winter_weather  # noqa: E402
from survey import PROVINCES, HomeDescription  # noqa: E402
from survey.example import (  # noqa: E402
    Truth,
    electricity_csv,
    example_period,
    gas_bill,
    thermometer_csv,
)

TZ = ZoneInfo("Europe/Madrid")
START = datetime(2026, 1, 1, tzinfo=TZ)
CUPS = "ES0021000000000001AB0F"  # fictitious
ANSWERS = {
    "province": "madrid",
    "home_type": "flat",
    "size": "m",
    "built": "1980_2006",
    "heating": "heat_pump",
    "heating_power": "5",  # the nameplate: a 5 kW split
    "cooling": "no",
    "thermostat": "20",
    "night": "lower",
    "people": "2",
    "water": "electric",
    "cooking": "electric",
    "appliances": ["dishwasher", "washing_machine", "oven", "tv"],
}
#: What the real home is, against the survey's typical guesses for the same
#: answers: it loses 25 % more heat, stores 20 % less, has a 5.2 kW heat pump
#: and a 175 W always-on load.
TRUTH = Truth(
    scale={"zone.envelope.conductance": 1.25, "zone.air.capacity": 0.8},
    set={"heating.thermostat.power": 5000.0, "base.power": 175.0},
    seed=11,
)

# ---------------------------------------------------------------- the gas home

GAS_ANSWERS = {
    "province": "madrid",
    "home_type": "flat",
    "size": "l",
    "built": "pre1980",
    "heating": "gas",
    "heating_power": "24",  # the nameplate: a 24 kW caldera mixta
    "cooling": "no",
    "thermostat": "21",
    "night": "lower",
    "people": "3",
    "water": "boiler",
    "cooking": "gas",
    "appliances": ["dishwasher", "washing_machine", "oven", "tv"],
}
#: The survey guesses 2.6 W/K per m² × 105 m² = 273 W per °C and 1.68e7 J/K;
#: this home had its windows replaced (20 % less) and stores 20 % more.
GAS_TRUTH = Truth(
    scale={"zone.envelope.conductance": 0.8, "zone.air.capacity": 1.2},
    set={"base.power": 160.0},
    seed=21,
)
GAS_CUPS = "ES0021000000000002CD0F"  # fictitious
SEASON = (datetime(2025, 10, 15, tzinfo=TZ), datetime(2026, 3, 15, tzinfo=TZ))
#: (folder, first reading date, last reading date, Fc, PCS kWh/m³ printed on
#: the bill, the gas meter's reading on the first date)
PERIODS = [
    ("15oct-15nov", date(2025, 10, 15), date(2025, 11, 15), 0.95, 11.71, 4321),
    ("15dic-15ene", date(2025, 12, 15), date(2026, 1, 15), 0.95, 11.66, 4660),
    ("15feb-15mar", date(2026, 2, 15), date(2026, 3, 15), 0.95, 11.62, 5162),
]
#: Madrid's normal monthly mean temperature, °C, on the 15th of each month.
_NORMALS = [
    (date(2025, 8, 15), 25.5),
    (date(2025, 9, 15), 21.0),
    (date(2025, 10, 15), 15.9),
    (date(2025, 11, 15), 10.4),
    (date(2025, 12, 15), 7.4),
    (date(2026, 1, 15), 6.3),
    (date(2026, 2, 15), 7.9),
    (date(2026, 3, 15), 11.2),
    (date(2026, 4, 15), 13.1),
]
WATER_LITRES_PER_PERSON_DAY = 118.0  # Spanish homes: about 130
WATER_EUR_PER_M3, WATER_EUR_PER_DAY = 1.85, 0.21
VAT_WATER = 0.10


def season_weather(start: datetime):
    """Madrid's normals through the season, with spells and a daily swing.

    ``f(t) -> °C`` for ``t`` in seconds from ``start`` (negative before it).
    """
    t0 = start.timestamp()
    knots = np.array(
        [
            datetime(d.year, d.month, d.day, 12, tzinfo=TZ).timestamp() - t0
            for d, _ in _NORMALS
        ]
    )
    means = np.array([m for _, m in _NORMALS])
    spells = winter_weather(mean_c=0.0, swing_c=4.5, seed=9)
    return lambda t: np.interp(np.asarray(t, float), knots, means) + spells(t)


def _open_meteo(t0: datetime, temps: np.ndarray) -> bytes:
    """The outdoor temperature as Open-Meteo gives it (unix times, as the wizard asks)."""
    madrid = next(p for p in PROVINCES if p.value == "madrid")
    first = int(t0.timestamp())
    offset = int(t0.utcoffset().total_seconds())  # type: ignore[union-attr]
    meteo = {
        "latitude": madrid.latitude,
        "longitude": madrid.longitude,
        "utc_offset_seconds": offset,
        "timezone": "Europe/Madrid",
        "timezone_abbreviation": f"GMT+{offset // 3600}",
        "hourly_units": {"time": "unixtime", "temperature_2m": "°C"},
        "hourly": {
            "time": [first + 3600 * k for k in range(temps.size)],
            "temperature_2m": [round(float(v), 1) for v in temps],
        },
    }
    return (json.dumps(meteo, indent=1) + "\n").encode()


def _comma(x: float, digits: int) -> str:
    return f"{x:.{digits}f}".replace(".", ",")


def _gas_home() -> dict[str, bytes]:
    desc = HomeDescription.from_answers(GAS_ANSWERS)
    weather = season_weather(SEASON[0])
    rng = np.random.default_rng(4)  # the water: independent of the thermostat
    water_m3 = 612.3
    files: dict[str, bytes] = {}
    for folder, d0, d1, fc, pcs, r0 in PERIODS:
        first = datetime(d0.year, d0.month, d0.day, tzinfo=TZ)
        last = datetime(d1.year, d1.month, d1.day, tzinfo=TZ)
        hours = int((last.timestamp() - first.timestamp()) // 3600)
        rel = first.timestamp() - SEASON[0].timestamp() + 3600.0 * np.arange(hours)
        outdoor = np.round(weather(rel), 1)  # as the weather file gives it
        rec = example_period(desc, GAS_TRUTH, start=first, outdoor_c=outdoor)
        days = (d1 - d0).days
        files[f"gas_home/{folder}/consumo_horario_{folder}.csv"] = electricity_csv(
            GAS_CUPS, first, rec.data.electricity_kwh
        )
        files[f"gas_home/{folder}/open_meteo_{folder}.json"] = _open_meteo(first, outdoor)
        files[f"gas_home/{folder}/factura_gas_{folder}.csv"] = gas_bill(
            first, last, r0, float(rec.gas_kwh.sum()), fc, pcs
        )[0]
        files[f"gas_home/{folder}/termometro_interior_{folder}.csv"] = thermometer_csv(
            rec.thermometer_utc, rec.thermometer_c, TZ
        )
        litres = 3 * WATER_LITRES_PER_PERSON_DAY * rng.uniform(0.85, 1.15, size=days)
        w0 = int(water_m3)
        water_m3 += litres.sum() / 1000.0
        w1 = int(water_m3)
        water_m3 += 3 * WATER_LITRES_PER_PERSON_DAY * 30 / 1000.0  # the month between
        weur = ((w1 - w0) * WATER_EUR_PER_M3 + days * WATER_EUR_PER_DAY) * (1 + VAT_WATER)
        files[f"gas_home/{folder}/factura_agua_{folder}.csv"] = (
            "inicio;fin;lectura_inicio_m3;lectura_fin_m3;tipo;importe_eur\n"
            f"{d0:%d/%m/%Y};{d1:%d/%m/%Y};{w0};{w1};real;{_comma(weur, 2)}\n"
        ).encode()
    files["gas_home/home.json"] = (json.dumps(GAS_ANSWERS, indent=2) + "\n").encode()
    files["gas_home/truth.json"] = (
        json.dumps(GAS_TRUTH.to_json(), indent=2) + "\n"
    ).encode()
    return files


def generate() -> dict[str, bytes]:
    """Every sample file, by path relative to this folder."""
    desc = HomeDescription.from_answers(ANSWERS)
    hours = 31 * 24
    outdoor = np.round(winter_weather(mean_c=6.0, seed=3)(3600.0 * np.arange(hours)), 1)
    rec = example_period(desc, TRUTH, start=START, outdoor_c=outdoor)
    files: dict[str, bytes] = {}
    files["consumo_horario_enero_2026.csv"] = electricity_csv(
        CUPS, START, rec.data.electricity_kwh
    )
    # weather station: unknown layout, local times, a humidity column to ignore
    t0 = START.astimezone(timezone.utc)
    rng = np.random.default_rng(5)
    lines = ["Fecha y hora;Temperatura exterior (ºC);Humedad relativa (%)"]
    for k, temp in enumerate(outdoor):
        local = (t0 + timedelta(hours=k)).astimezone(TZ)
        rh = int(np.clip(75 - 2.0 * temp + rng.normal(0, 4), 20, 100))
        lines.append(f"{local:%d/%m/%Y %H:%M};{temp:.1f}".replace(".", ",") + f";{rh}")
    files["estacion_meteo_enero_2026.csv"] = ("\n".join(lines) + "\n").encode("utf-8")
    files["open_meteo_enero_2026.json"] = _open_meteo(START, outdoor)
    files["termometro_interior_enero_2026.csv"] = thermometer_csv(
        rec.thermometer_utc, rec.thermometer_c, TZ
    )
    files["home.json"] = (json.dumps(ANSWERS, indent=2) + "\n").encode()
    files["truth.json"] = (json.dumps(TRUTH.to_json(), indent=2) + "\n").encode()
    files.update(_gas_home())
    return files


def main() -> None:
    """Write the samples next to this script."""
    for name, data in generate().items():
        path = HERE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
