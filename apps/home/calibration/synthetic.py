"""Synthetic months: hourly data generated from a home whose parameters are known.

The way to check a calibration is to hand it data from a home whose answer
is known and see whether it finds it. :func:`synthetic_month` simulates a
twin on a fine grid (5-minute steps by default, much finer than the fit
uses), with a history of weather *before* the record, so the record starts
from a state the calibration does not know. It then integrates the meter
exactly over each hour and, optionally, adds the noise of a real meter and
a real household: a relative error, an absolute one, and rounding to the
watt-hour like Datadis.

:func:`synthetic_meters` does the same for any number of hours and returns
the gas meter too, hour by hour, exactly (a gas bill is the sum of it).

:func:`synthetic_record` is what the example homes are made of: given the
hourly weather of a period (as a weather file has it), it returns the
electricity, the gas and the interior thermometer's readings, every one from
the same simulation, with the thermometer read the way a real one is.

:func:`winter_weather` is a deterministic synthetic winter month: daily
means wandering over a few days, a daily swing, coldest at dawn.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np

from components import ZERO_CELSIUS, HomeTwin

from .data import HourlyData

__all__ = [
    "synthetic_month",
    "synthetic_meters",
    "synthetic_record",
    "SyntheticRecord",
    "winter_weather",
]


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
    data, _ = synthetic_meters(
        twin,
        start=start,
        outdoor_c=outdoor_c,
        hours=days * 24,
        history_days=history_days,
        steps_per_hour=steps_per_hour,
        noise_relative=noise_relative,
        noise_kwh=noise_kwh,
        round_wh=round_wh,
        seed=seed,
        measured=measured,
    )
    return data


def synthetic_meters(
    twin: HomeTwin,
    *,
    start: datetime,
    outdoor_c: Callable[[np.ndarray], np.ndarray],
    hours: int,
    history_days: int = 60,
    steps_per_hour: int = 12,
    noise_relative: float = 0.0,
    noise_kwh: float = 0.0,
    round_wh: bool = True,
    seed: int = 0,
    measured: Mapping[str, Callable[[np.ndarray], np.ndarray]] | None = None,
) -> tuple[HourlyData, np.ndarray]:
    """Like :func:`synthetic_month`, over ``hours``, with the gas meter too.

    Returns the record (electricity as a meter records it, with the noise
    asked for) and the gas the home burned in each hour, kWh, exact: a gas
    meter is read once a bill, so its hourly detail never carries noise.
    """
    hist = history_days * 24
    total = hist + int(hours)
    sub = int(steps_per_hour)
    t = np.arange(total * sub + 1) * (3600.0 / sub)
    t_rel = t - hist * 3600.0  # seconds from the record start
    sim_start = start.astimezone(timezone.utc) - timedelta(
        hours=hist
    )  # elapsed, not wall-clock
    extra = {k: f(t_rel) for k, f in (measured or {}).items()}
    run = twin.simulate(
        t, start=sim_start, outdoor=ZERO_CELSIUS + outdoor_c(t_rel), **extra
    )

    def meter(names: list[str]) -> np.ndarray:
        if not names:
            return np.zeros(int(hours))
        watts = np.sum([run.step_mean[n] for n in names], axis=0)
        return watts.reshape(total, sub).mean(axis=1)[hist:] / 1000.0

    kwh = meter(twin.electric_outputs)
    gas = meter(twin.gas_outputs)
    rng = np.random.default_rng(seed)
    if noise_relative:
        kwh = kwh * (1.0 + noise_relative * rng.standard_normal(kwh.size))
    if noise_kwh:
        kwh = kwh + noise_kwh * rng.standard_normal(kwh.size)
    kwh = np.maximum(kwh, 0.0)
    if round_wh:
        kwh = np.round(kwh, 3)
    hour_starts = np.arange(int(hours)) * 3600.0
    outdoor = np.round(outdoor_c(hour_starts), 1)  # Open-Meteo gives 0.1 °C
    rec = {k: f(hour_starts) for k, f in (measured or {}).items()}
    return HourlyData(start, kwh, outdoor, rec), gas


@dataclass(frozen=True)
class SyntheticRecord:
    """One period of a home whose parameters are known, as its files would be.

    Attributes:
        data: the record: hourly electricity as a meter records it, the
            outdoor temperature, and the hourly mean indoor temperature.
        gas_kwh: gas burned in each hour, kWh, exact (a bill is a sum of it).
        thermometer_utc: when the interior thermometer read, Unix seconds.
        thermometer_c: what it read, °C, to its 0.1 °C resolution.
        duty: the fraction of each hour the heating ran (0 to 1), or ``None``
            for a home with no thermostat-controlled heating.
    """

    data: HourlyData
    gas_kwh: np.ndarray
    thermometer_utc: np.ndarray
    thermometer_c: np.ndarray
    duty: np.ndarray | None


def synthetic_record(
    twin: HomeTwin,
    *,
    start: datetime,
    outdoor_c: np.ndarray,
    spinup_weeks: int = 6,
    steps_per_hour: int = 6,
    noise_relative: float = 0.05,
    noise_kwh: float = 0.08,
    thermometer_bias_k: float | None = None,
    thermometer_drift_k: float = 0.15,
    seed: int = 0,
) -> SyntheticRecord:
    """A period of ``twin``, from its hourly weather, as the household's files would be.

    Args:
        twin: the home with its *true* parameters, its thermostat schedule
            the one the householder chose.
        start: the first hour (aware, on the hour).
        outdoor_c: the outdoor temperature at the start of each hour, °C, as a
            weather file gives it; its length is the period's length.
        spinup_weeks: the period's first week is replayed this many times
            before it, so the home enters the period warmed up as it would be.
        steps_per_hour: simulation steps per hour; the thermometer reads once
            a step, in its middle (six: every ten minutes, as home sensors log).
        noise_relative, noise_kwh, seed: the electricity's noise, as in
            :func:`synthetic_month`.
        thermometer_bias_k: the thermometer's fixed calibration error, K: the
            same device reads the same amount off in every period. ``None``
            draws one (standard deviation 0.2 K) from ``seed``.
        thermometer_drift_k: standard deviation of a slow wander, K, with a
            time constant of about an hour: the sun on the sensor, a door
            left open, the oven. What a single sensor sees but the twin's
            one-node room does not.
    """
    hours = int(np.asarray(outdoor_c).size)
    sub = int(steps_per_hour)
    week = min(7 * 24, hours)
    prefix = spinup_weeks * week
    total = prefix + hours
    t = np.arange(total * sub + 1) * (3600.0 / sub)
    hourly = np.concatenate([np.tile(outdoor_c[:week], spinup_weeks), outdoor_c])
    outdoor = np.interp(t / 3600.0, np.arange(total, dtype=float), hourly)
    sim_start = start.astimezone(timezone.utc) - timedelta(hours=prefix)  # elapsed
    thermo = twin.thermometer
    machines = [n for n in twin.model.output_names if n.endswith(".thermostat.duty")]
    duty_name = next((n for n in machines if not n.startswith("water_heater")), None)
    track = [thermo] + ([duty_name] if duty_name else [])
    run = twin.simulate(t, start=sim_start, outdoor=ZERO_CELSIUS + outdoor, track=track)

    def hourly_mean(names: list[str]) -> np.ndarray:
        if not names:
            return np.zeros(hours)
        watts = np.sum([run.step_mean[n] for n in names], axis=0)
        return watts.reshape(total, sub).mean(axis=1)[prefix:]

    rng = np.random.default_rng(seed)
    kwh = hourly_mean(list(twin.electric_outputs)) / 1000.0
    gas = hourly_mean(list(twin.gas_outputs)) / 1000.0
    if noise_relative:
        kwh = kwh * (1.0 + noise_relative * rng.standard_normal(kwh.size))
    if noise_kwh:
        kwh = kwh + noise_kwh * rng.standard_normal(kwh.size)
    kwh = np.round(np.maximum(kwh, 0.0), 3)

    # The thermometer logs the room once a step, at the middle of it (:05,
    # :15, ... :55), so an hour's six readings average to the hour's mean
    # temperature: what the twin's meter compares them with.
    temps = np.asarray(run[thermo])[prefix * sub :] - ZERO_CELSIUS
    true_c = (temps[1:] + temps[:-1]) / 2.0
    n = true_c.size
    phi = np.exp(-1.0 / sub)  # one hour of memory
    shocks = rng.standard_normal(n) * thermometer_drift_k * np.sqrt(1 - phi**2)
    drift = np.empty(n)
    acc = rng.standard_normal() * thermometer_drift_k
    for k in range(n):
        acc = phi * acc + shocks[k]
        drift[k] = acc
    drawn = rng.standard_normal() * 0.2
    bias = drawn if thermometer_bias_k is None else float(thermometer_bias_k)
    read = np.round(true_c + bias + drift, 1)
    t0 = int(start.timestamp())
    step = 3600 // sub
    read_utc = t0 + step // 2 + step * np.arange(n, dtype=np.int64)
    hour_of = (read_utc - t0) // 3600
    indoor = np.bincount(hour_of, weights=read, minlength=hours) / np.bincount(
        hour_of, minlength=hours
    )
    data = HourlyData(
        start,
        kwh,
        np.round(np.asarray(outdoor_c, dtype=float), 1),
        indoor_c=indoor,
        check_length=False,
    )
    duty = hourly_mean([duty_name]) if duty_name else None
    return SyntheticRecord(data, gas, read_utc, read, duty)
