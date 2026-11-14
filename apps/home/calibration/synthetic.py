"""Synthetic months: hourly data generated from a home whose parameters are known.

The way to check a calibration is to hand it data from a home whose answer
is known and see whether it finds it. :func:`synthetic_month` simulates a
twin on a fine grid (5-minute steps by default, much finer than the fit
uses), with a history of weather *before* the record, so the record starts
from a state the calibration does not know. It then integrates the meter
exactly over each hour and, optionally, adds the noise of a real meter and
a real household: a relative error, an absolute one, and rounding to the
watt-hour like Datadis.

:func:`winter_weather` is a deterministic synthetic winter month: daily
means wandering over a few days, a daily swing, coldest at dawn.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta

import numpy as np

from components import ZERO_CELSIUS, HomeTwin

from .data import HourlyData

__all__ = ["synthetic_month", "winter_weather"]


def winter_weather(
    mean_c: float = 7.0, swing_c: float = 4.5, seed: int = 0
) -> Callable[[np.ndarray], np.ndarray]:
    """A synthetic winter: ``f(t) -> °C`` for ``t`` in seconds from the record start.

    Daily means wander around ``mean_c`` by about ±4 °C over spells of three
    to ten days (a sum of slow waves with seeded phases); the daily swing is
    ``±swing_c``, coldest at 06:00. Negative ``t`` (the history before the
    record) continues the same weather.
    """
    rng = np.random.default_rng(seed)
    periods = np.array([3.3, 5.7, 9.1, 17.0]) * 86400.0
    amps = np.array([1.2, 1.6, 1.8, 1.4])
    phases = rng.uniform(0, 2 * np.pi, size=periods.size)

    def f(t: np.ndarray) -> np.ndarray:
        t = np.asarray(t, dtype=float)
        spells = sum(
            a * np.sin(2 * np.pi * t / p + ph)
            for a, p, ph in zip(amps, periods, phases, strict=True)
        )
        daily = -swing_c * np.cos(2 * np.pi * (t / 3600.0 - 6.0) / 24.0)
        return mean_c + spells + daily

    return f


def synthetic_month(
    twin: HomeTwin,
    *,
    start: datetime,
    outdoor_c: Callable[[np.ndarray], np.ndarray],
    days: int = 31,
    history_days: int = 60,
    steps_per_hour: int = 12,
    noise_relative: float = 0.0,
    noise_kwh: float = 0.0,
    round_wh: bool = True,
    seed: int = 0,
    measured: Mapping[str, Callable[[np.ndarray], np.ndarray]] | None = None,
) -> HourlyData:
    """Hourly electricity of ``twin`` over ``days`` from ``start``, as a meter records it.

    Args:
        twin: the home with its *true* parameters.
        start: first hour of the record (aware, on the hour).
        outdoor_c: the weather, ``f(t) -> °C``, ``t`` in seconds from ``start``.
        days: record length.
        history_days: days simulated before the record and discarded.
        steps_per_hour: simulation steps per hour (12: five minutes).
        noise_relative: standard deviation of a multiplicative error per hour.
        noise_kwh: standard deviation of an additive error per hour, kWh,
            standing in for appliance use the twin does not know about.
        round_wh: round each hour to 0.001 kWh, as Datadis does.
        seed: for the noise.
        measured: other inputs given as functions of time, by input name;
            they are also returned in the record, hourly.
    """
    hist = history_days * 24
    hours = hist + days * 24
    sub = int(steps_per_hour)
    t = np.arange(hours * sub + 1) * (3600.0 / sub)
    t_rel = t - hist * 3600.0  # seconds from the record start
    sim_start = start - timedelta(hours=hist)
    extra = {k: f(t_rel) for k, f in (measured or {}).items()}
    run = twin.simulate(
        t, start=sim_start, outdoor=ZERO_CELSIUS + outdoor_c(t_rel), **extra
    )
    watts = np.sum([run.step_mean[n] for n in twin.electric_outputs], axis=0)
    kwh = watts.reshape(hours, sub).mean(axis=1)[hist:] / 1000.0
    rng = np.random.default_rng(seed)
    if noise_relative:
        kwh = kwh * (1.0 + noise_relative * rng.standard_normal(kwh.size))
    if noise_kwh:
        kwh = kwh + noise_kwh * rng.standard_normal(kwh.size)
    kwh = np.maximum(kwh, 0.0)
    if round_wh:
        kwh = np.round(kwh, 3)
    hour_starts = np.arange(days * 24) * 3600.0
    outdoor = np.round(outdoor_c(hour_starts), 1)  # Open-Meteo gives 0.1 °C
    rec = {k: f(hour_starts) for k, f in (measured or {}).items()}
    return HourlyData(start, kwh, outdoor, rec)
