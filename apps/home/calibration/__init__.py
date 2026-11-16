"""Otwin Home calibration: a month of electricity in, a home you can trust out.

Give it one month of hourly electricity (Datadis, a distributor portal, read
by :mod:`ingest`) and the outdoor temperature (Open-Meteo), and it fits the
parameters of a home twin that the electricity meter can see: how fast the
home loses heat, how long it keeps its warmth, the size of the heating or
cooling machine, and the always-on load. Then it says, in plain words, how
far each number can be trusted: **good**, **usable** or **not enough data**.

::

    from calibration import HourlyData, calibrate
    data = HourlyData(start, electricity_kwh, outdoor_c)   # refuses < 28 days
    result = calibrate(twin, data)
    print(result.summary())

The search is :func:`otwin.hybrid.fit_parameters`, the engine's own;
:mod:`calibration.fit` supplies the exact hourly meter it fits against.
:mod:`calibration.synthetic` generates months from known homes, for tests
and demonstrations.
"""

from __future__ import annotations

from .calibrate import MIN_FULL_POWER_HOURS, START_OFFSET_K, Calibration, calibrate
from .data import MAX_MISSING_FRACTION, MIN_DAYS, GasBill, HourlyData, NotEnoughData
from .fit import HourlyMeter, calibration_parameters, fit_hourly
from .report import GOOD, NOT_ENOUGH_DATA, USABLE, VERDICTS, Finding
from .synthetic import (
    SyntheticRecord,
    synthetic_meters,
    synthetic_month,
    synthetic_record,
    winter_weather,
)

__all__ = [
    "calibrate",
    "Calibration",
    "Finding",
    "HourlyData",
    "GasBill",
    "NotEnoughData",
    "MIN_DAYS",
    "MAX_MISSING_FRACTION",
    "GOOD",
    "USABLE",
    "NOT_ENOUGH_DATA",
    "VERDICTS",
    "HourlyMeter",
    "calibration_parameters",
    "fit_hourly",
    "START_OFFSET_K",
    "MIN_FULL_POWER_HOURS",
    "synthetic_month",
    "synthetic_meters",
    "synthetic_record",
    "SyntheticRecord",
    "winter_weather",
]
