"""Calibrate a home twin to one month of hourly electricity, and read the verdict.

Runs offline. The "real" home is simulated: a 1R1C flat heated by a heat
pump with a night setback, and a January of synthetic weather, recorded the
way a smart meter records it (hourly kWh, a real household's noise). The
householder's twin starts from rough guesses, each 50 % off, and the
calibration finds the home from the electricity alone.

    python apps/home/examples/calibrate_month.py

With real data, build the record from the ingest layer instead::

    elec = ingest.load(open("datadis.csv", "rb").read())[0]
    weather = ingest.load(open("open_meteo.json", "rb").read())[0]
    data = HourlyData.from_series(elec, weather)
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from calibration import calibrate, synthetic_month, winter_weather  # noqa: E402
from components import (  # noqa: E402
    ZERO_CELSIUS,
    Appliance,
    BaseLoad,
    HeatPump,
    Schedule,
    ThermalZone,
    build_home,
)
from components.catalogue import KITCHEN, LIVING  # noqa: E402

START = datetime(2026, 1, 1, tzinfo=timezone.utc)
SETBACK = Schedule([ZERO_CELSIUS + (20.0 if 7 <= h < 23 else 16.0) for h in range(24)])


def heat_pump_flat(
    ua: float, capacity: float, heater: float, base: float, backend: str = "auto"
):
    """The flat's twin with the given heat loss, storage, heater size and base load."""
    return build_home(
        ThermalZone(ua, capacity, ventilation=30.0, temperature=ZERO_CELSIUS + 19.0),
        gains=[
            BaseLoad(base),
            Appliance(schedule=KITCHEN, name="kitchen"),
            Appliance(schedule=LIVING, name="living"),
        ],
        conditioning=[
            HeatPump(
                heater, cop=3.0, setpoint=None, setpoint_schedule=SETBACK, name="heating"
            )
        ],
        backend=backend,
    )


def main(backend: str = "auto"):
    """Generate the month, calibrate the rough twin, print the report."""
    real = heat_pump_flat(180.0, 1.2e7, 4500.0, 150.0, backend)
    data = synthetic_month(
        real,
        start=START,
        outdoor_c=winter_weather(seed=1),
        noise_relative=0.05,
        noise_kwh=0.08,
        seed=7,
    )
    rough = heat_pump_flat(270.0, 0.6e7, 6750.0, 75.0, backend)
    result = calibrate(rough, data)
    print(
        f"{data.days:.0f} days of hourly electricity, "
        f"{data.electricity_kwh.sum():.0f} kWh in total\n"
    )
    print(result.summary())
    print("\n  value                          rough guess   calibrated   (the real home)")
    truth = {
        "zone.envelope.conductance": 180.0,
        "zone.air.capacity": 1.2e7,
        "heating.thermostat.power": 4500.0,
        "base.power": 150.0,
    }
    for name, true in truth.items():
        print(
            f"  {name:<30} {rough.model.parameters[name]:11.4g} "
            f"{result.values[name]:12.4g}   {true:10.4g}"
        )
    return result


if __name__ == "__main__":
    main()
