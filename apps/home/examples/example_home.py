"""The catalogue's Madrid flat through a January week, and three what-ifs.

Runs offline: the outdoor temperature is a synthetic Madrid January (6 °C
mean, ±5 °C daily swing, coldest at 06:00), not a download. The home is
:func:`components.catalogue.madrid_flat`: a 90 m² flat with a gas combi
boiler, an 80 L electric *termo* and a typical day of appliance use.

    python apps/home/examples/example_home.py

Scenarios: the home as it is, the envelope insulated (160 → 100 W/K), and a
cold spell 6 °C colder all week.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components import ZERO_CELSIUS, madrid_flat  # noqa: E402

#: Monday 12 January 2026, 00:00 in Madrid (CET, UTC+1).
START = datetime(2026, 1, 11, 23, 0, tzinfo=timezone.utc)
DAYS = 7
STEP = 600.0  # 10 minutes


def outdoor(t: np.ndarray, shift: float = 0.0) -> np.ndarray:
    """Synthetic January outdoor air in K: coldest at 06:00, warmest at 18:00."""
    hours = t / 3600.0
    return ZERO_CELSIUS + 6.0 + shift - 5.0 * np.cos(2 * np.pi * (hours - 6.0) / 24.0)


def run_week(backend: str = "auto", *, ua: float | None = None, shift: float = 0.0):
    """Simulate the Madrid flat for a week; returns ``(twin, run)``."""
    twin = madrid_flat(backend=backend)
    if ua is not None:
        twin.model.set_parameters({"zone.envelope.conductance": ua})
    t = np.arange(0, DAYS * 86400 + 1, STEP)
    return twin, twin.simulate(t, start=START, outdoor=outdoor(t, shift))


def main(backend: str = "auto") -> dict[str, tuple[float, float]]:
    """Print the week and the scenarios; returns kWh by scenario."""
    twin, base = run_week(backend)
    local = START.astimezone(ZoneInfo("Europe/Madrid"))
    print(
        f"Madrid flat on the {twin.model.backend} backend, "
        f"{DAYS} days from {local:%A %d %B %Y}"
    )
    print(f"  inputs: {', '.join(twin.input_names)}")
    print("\n  day  indoor min-max °C   electricity kWh   gas kWh")
    for d in range(DAYS):
        window = (d * 86400.0, (d + 1) * 86400.0)
        inside = (base.t >= window[0]) & (base.t <= window[1])
        T = base.indoor_temperature[inside] - ZERO_CELSIUS
        e = base.energy_kwh("electricity", between=window)
        g = base.energy_kwh("gas", between=window)
        print(
            f"  {d + 1:>3}  {T.min():6.1f} - {T.max():4.1f}      {e:10.1f}      {g:8.1f}"
        )
    results = {"as built": (base.energy_kwh("electricity"), base.energy_kwh("gas"))}
    _, ins = run_week(backend, ua=100.0)
    results["insulated envelope"] = (ins.energy_kwh("electricity"), ins.energy_kwh("gas"))
    _, cold = run_week(backend, shift=-6.0)
    results["cold spell, -6 °C"] = (
        cold.energy_kwh("electricity"),
        cold.energy_kwh("gas"),
    )
    print("\n  scenario               electricity kWh   gas kWh")
    for name, (e, g) in results.items():
        print(f"  {name:<22} {e:12.1f}   {g:9.1f}")
    return results


if __name__ == "__main__":
    main()
