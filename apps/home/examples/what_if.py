"""What-ifs on a calibrated home: calibrate on a month, then ask five questions.

Runs offline. The "real" home is a heat-pump flat with a night setback and
a dishwasher running at 21:00; a synthetic January is recorded as a smart
meter would record it. The householder's rough twin is calibrated on that
month (see calibrate_month.py), and the calibrated twin answers:

1. What if January were 3 °C colder?
2. What if I turned the heating down by 1 °C?
3. What if I ran the dishwasher at 02:00 instead of 21:00?
4. What if I insulated the 40 m² facade with R 2 m²·K/W boards?
5. What if I switched to a flat-price tariff?

    python apps/home/examples/what_if.py
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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
from scenarios import (  # noqa: E402
    ElectricityTariff,
    Insulation,
    MoveAppliance,
    OutdoorShift,
    ScenarioStudy,
    SetpointChange,
    Tariff,
    TariffChange,
)

START = datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/Madrid"))
SETBACK = Schedule([ZERO_CELSIUS + (20.0 if 7 <= h < 23 else 16.0) for h in range(24)])
DISHWASHER = Schedule([1200.0 if h == 21 else 0.0 for h in range(24)])

#: The household's contract: 2.0TD, 4.6 kW (illustrative 2026 prices).
MY_TARIFF = Tariff(
    ElectricityTariff(
        "2.0TD",
        {"P1": 0.19, "P2": 0.12, "P3": 0.08},
        power_kw=4.6,
        power_eur_per_kw_day=0.0885,
        meter_eur_per_day=0.0266,
    )
)
#: An offer the household is considering: one price at every hour.
FLAT_OFFER = Tariff(
    ElectricityTariff(
        "Tarifa Plana",
        0.135,
        power_kw=4.6,
        power_eur_per_kw_day=0.0885,
        meter_eur_per_day=0.0266,
    )
)


def flat(ua: float, capacity: float, heater: float, base: float, backend: str = "auto"):
    """The heat-pump flat with a dishwasher whose heat goes down the drain."""
    return build_home(
        ThermalZone(ua, capacity, ventilation=30.0, temperature=ZERO_CELSIUS + 19.0),
        gains=[
            BaseLoad(base),
            Appliance(schedule=KITCHEN, name="kitchen"),
            Appliance(schedule=LIVING, name="living"),
            Appliance(schedule=DISHWASHER, indoors=False, name="dishwasher"),
        ],
        conditioning=[
            HeatPump(
                heater, cop=3.0, setpoint=None, setpoint_schedule=SETBACK, name="heating"
            )
        ],
        backend=backend,
    )


def main(backend: str = "auto"):
    """Calibrate, then run and print the five what-ifs; returns the results."""
    data = synthetic_month(
        flat(180.0, 1.2e7, 4500.0, 150.0, backend),
        start=START,
        outdoor_c=winter_weather(seed=1),
        noise_relative=0.05,
        noise_kwh=0.08,
        seed=7,
    )
    calibration = calibrate(flat(270.0, 0.6e7, 6750.0, 75.0, backend), data)
    print(f"Calibrated on January 2026: {calibration.verdict}.\n")
    study = ScenarioStudy.from_calibration(calibration, data, MY_TARIFF)
    base = study.baseline
    print(
        f"As it is: {base.electricity_kwh_per_month:.0f} kWh of electricity, "
        f"€{base.eur_per_month:.2f} {base.period}.\n"
    )
    results = study.run_all(
        [
            OutdoorShift(-3.0),
            SetpointChange(-1.0),
            MoveAppliance("dishwasher", from_hours=(21,), to_hours=(2,)),
            Insulation(r_value=2.0, area_m2=40.0, envelope_area_m2=120.0),
            TariffChange(FLAT_OFFER),
        ]
    )
    for r in results:
        print(f"• {r.sentence}")
    print()
    print(results[3].table())
    return results


if __name__ == "__main__":
    main()
