"""A Seville house through a whole year: the electricity bill peaks in summer.

Runs offline on a synthetic Seville climate (11 °C January mean, 28 °C July
mean, ±5.5 °C daily swing). The home is
:func:`components.catalogue.seville_house`: everything electric, one
reversible split unit that heats mildly in winter (heat pump, COP 3.2) and
cools hard in summer (EER 2.8, set to 25 °C).

    python apps/home/examples/seville_summer.py

The monthly table shows what the household feels: a flat bill most of the
year and a jump in July and August, when the air conditioner becomes the
biggest load in the house. The scenario raises the cooling setpoint to
26 °C, the cheapest kilowatt-hours there are.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import ZERO_CELSIUS, seville_house  # noqa: E402

TZ = ZoneInfo("Europe/Madrid")
#: 1 January 2026, 00:00 in Seville (CET).
START = datetime(2026, 1, 1, tzinfo=TZ)
PRICE = 0.25  # EUR per kWh, flat
FIXED = 0.35  # EUR per day of standing charge
STEP = 3600.0  # hourly


def month_windows() -> list[tuple[str, float, float]]:
    """(name, t0, t1) of each month of the year, in model seconds."""
    out = []
    for m in range(1, 13):
        a = datetime(2026, m, 1, tzinfo=TZ)
        b = datetime(2026 + (m == 12), m % 12 + 1, 1, tzinfo=TZ)
        out.append((f"{a:%b}", (a - START).total_seconds(), (b - START).total_seconds()))
    return out


def outdoor(t: np.ndarray, *, heatwave: float = 0.0) -> np.ndarray:
    """Synthetic Seville air in K: annual wave peaking 23 July, daily ±5.5 °C."""
    day = t / 86400.0
    annual = 19.4 - 8.9 * np.cos(2 * np.pi * (day - 22.0) / 365.0)
    daily = -5.5 * np.cos(2 * np.pi * (t / 3600.0 - 6.0) / 24.0)
    august = (day >= 212) & (day < 243)
    return ZERO_CELSIUS + annual + daily + np.where(august, heatwave, 0.0)


def run_year(
    backend: str = "auto", *, cooling_setpoint: float | None = None, heatwave: float = 0.0
):
    """Simulate the year; returns ``(twin, run)``."""
    twin = seville_house(backend=backend)
    if cooling_setpoint is not None:
        twin.model.set_parameters(
            {"aircon.setpoint.temperature": ZERO_CELSIUS + cooling_setpoint}
        )
    end = (datetime(2027, 1, 1, tzinfo=TZ) - START).total_seconds()
    t = np.arange(0.0, end + 1, STEP)
    return twin, twin.simulate(t, start=START, outdoor=outdoor(t, heatwave=heatwave))


def main(backend: str = "auto") -> dict[str, float]:
    """Print the year by months and the scenarios; returns EUR by scenario."""
    twin, base = run_year(backend)
    print(f"Seville house on the {twin.model.backend} backend, the year 2026")
    print(f"  inputs: {', '.join(twin.input_names)}   gas meter: none")
    print("\n  month   outdoor °C   electricity kWh   of it cooling   heating   cost EUR")
    year_eur = 0.0
    for name, t0, t1 in month_windows():
        w = (t0, t1)
        mean_out = float(np.mean(outdoor(np.arange(t0, t1, STEP)))) - ZERO_CELSIUS
        kwh = base.energy_kwh("electricity", between=w)
        cool = base.energy_j("aircon.fuel_power", between=w) / 3.6e6
        heat = base.energy_j("heatpump.fuel_power", between=w) / 3.6e6
        eur = base.cost_eur("electricity", PRICE, fixed_eur_per_day=FIXED, between=w)
        year_eur += eur
        print(
            f"  {name:<6} {mean_out:9.1f} {kwh:15.0f} {cool:13.0f} {heat:11.0f} {eur:10.2f}"
        )
    results = {"as built, 25 °C": year_eur}

    def year_cost(run) -> float:
        return run.cost_eur("electricity", PRICE, fixed_eur_per_day=FIXED)

    _, mild = run_year(backend, cooling_setpoint=26.0)
    results["cooling at 26 °C"] = year_cost(mild)
    _, wave = run_year(backend, heatwave=4.0)
    results["August heatwave, +4 °C"] = year_cost(wave)
    print("\n  scenario                 electricity EUR/year")
    for name, eur in results.items():
        print(f"  {name:<26} {eur:10.2f}")
    print(
        "\n  summer (Jun-Sep) is "
        f"{100 * _summer_share(base):.0f}% of the as-built annual kWh"
    )
    return results


def _summer_share(run) -> float:
    months = month_windows()
    summer = sum(
        run.energy_kwh("electricity", between=(t0, t1)) for name, t0, t1 in months[5:9]
    )
    return summer / run.energy_kwh("electricity")


if __name__ == "__main__":
    main()
