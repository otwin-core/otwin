"""The wizard's sample files: one January of a home whose answer is known.

The "real" home is the survey's answers in ``home.json`` with four values
the survey cannot know set differently from its typical guesses (it loses
25 % more heat, stores 20 % less, has a 5.2 kW heat pump and a 175 W
always-on load). Its January 2026 is recorded the way the household would
export it:

* ``consumo_horario_enero_2026.csv``: hourly electricity, the CNMC/Datadis
  CSV shape (``CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion``), a real
  household's noise, a few estimated hours;
* ``estacion_meteo_enero_2026.csv``: a home weather station's export, a
  layout no parser knows: the wizard's column mapper reads it;
* ``open_meteo_enero_2026.json``: the same weather as Open-Meteo gives it,
  read without any mapping.

The wizard's "Try with example files" loads these, and the end-to-end checks
calibrate on them. Regenerate with::

    python apps/home/web/samples/make_samples.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from calibration import synthetic_month, winter_weather  # noqa: E402
from survey import PROVINCES, HomeDescription, build_twin  # noqa: E402

TZ = ZoneInfo("Europe/Madrid")
START = datetime(2026, 1, 1, tzinfo=TZ)
CUPS = "ES0021000000000001AB0F"  # fictitious
ANSWERS = {
    "province": "madrid",
    "home_type": "flat",
    "size": "m",
    "built": "1980_2006",
    "heating": "heat_pump",
    "cooling": "no",
    "thermostat": "20",
    "night": "lower",
    "people": "2",
    "water": "electric",
    "appliances": ["dishwasher", "washing_machine", "oven", "tv"],
}
#: What the real home is, against the survey's typical guesses.
TRUTH = {
    "zone.envelope.conductance": 1.25 * 150.0,
    "zone.air.capacity": 0.8 * 1.2e7,
    "heating.thermostat.power": 5200.0,
    "base.power": 175.0,
}


def generate() -> dict[str, bytes]:
    """Every sample file, by name."""
    desc = HomeDescription.from_answers(ANSWERS)
    real = build_twin(desc, backend="numpy", overrides=TRUTH)
    data = synthetic_month(
        real,
        start=START,
        outdoor_c=winter_weather(mean_c=6.0, seed=3),
        noise_relative=0.05,
        noise_kwh=0.08,
        seed=11,
    )
    files: dict[str, bytes] = {}

    # electricity: CNMC shape, hours 1..n of each local day, decimal comma
    lines = ["CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion"]
    t0 = data.start.astimezone(timezone.utc)
    day_hours: dict[str, int] = {}
    for k, kwh in enumerate(data.electricity_kwh):
        local = (t0 + timedelta(hours=k)).astimezone(TZ)
        day = f"{local:%d/%m/%Y}"
        day_hours[day] = day_hours.get(day, 0) + 1
        method = "E" if k % 97 == 41 else "R"
        lines.append(
            f"{CUPS};{day};{day_hours[day]};{kwh:.3f}".replace(".", ",") + f";{method}"
        )
    files["consumo_horario_enero_2026.csv"] = ("\r\n".join(lines) + "\r\n").encode()

    # weather station: unknown layout, local times, a humidity column to ignore
    rng = np.random.default_rng(5)
    lines = ["Fecha y hora;Temperatura exterior (ºC);Humedad relativa (%)"]
    for k, temp in enumerate(data.outdoor_c):
        local = (t0 + timedelta(hours=k)).astimezone(TZ)
        rh = int(np.clip(75 - 2.0 * temp + rng.normal(0, 4), 20, 100))
        lines.append(f"{local:%d/%m/%Y %H:%M};{temp:.1f}".replace(".", ",") + f";{rh}")
    files["estacion_meteo_enero_2026.csv"] = ("\n".join(lines) + "\n").encode("utf-8")

    # the same weather as Open-Meteo gives it (unix times, as the wizard asks)
    madrid = next(p for p in PROVINCES if p.value == "madrid")
    times = [int(t0.timestamp()) + 3600 * k for k in range(data.hours)]
    meteo = {
        "latitude": madrid.latitude,
        "longitude": madrid.longitude,
        "utc_offset_seconds": 3600,
        "timezone": "Europe/Madrid",
        "timezone_abbreviation": "GMT+1",
        "hourly_units": {"time": "unixtime", "temperature_2m": "°C"},
        "hourly": {
            "time": times,
            "temperature_2m": [round(float(v), 1) for v in data.outdoor_c],
        },
    }
    files["open_meteo_enero_2026.json"] = (json.dumps(meteo, indent=1) + "\n").encode()
    files["home.json"] = (json.dumps(ANSWERS, indent=2) + "\n").encode()
    return files


def main() -> None:
    """Write the samples next to this script."""
    for name, data in generate().items():
        (HERE / name).write_bytes(data)
        print(f"wrote {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
