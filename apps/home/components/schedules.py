"""Schedules: the clock-driven inputs of a home. Not physics.

A home's behaviour repeats by the clock: the fridge always, the oven at
lunch and dinner, the shower in the morning, the thermostat set back at
night. A :class:`Schedule` holds one value per local hour, either 24 values
(every day the same) or 168 (Monday 00:00 first), in whatever unit the input
expects. :meth:`Schedule.sample` turns it into the input array a compiled
model takes on its time grid.

Schedules are *inputs*, not part of the compiled equations. The same input
can therefore be fed a measured series instead (a Shelly or Tapo export
read by :mod:`ingest`), and a calibrated twin uses what was measured. The
schedule is the default when nothing was.

Model time is seconds since ``start``, a UTC instant. The local hour of each
sample is read in the schedule's time zone, so a schedule keeps its meaning on
the 23- and 25-hour days of the DST changes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import numpy.typing as npt

from .stores import WATER_HEAT_CAPACITY

__all__ = ["Schedule", "ClimateSchedule", "hot_water_heat", "WATER_HEAT_CAPACITY"]


@dataclass(frozen=True)
class Schedule:
    """One value per local hour: 24 (daily) or 168 (weekly, Monday first).

    Args:
        values: the hourly values, in the unit the input expects (W for a
            gain, K for a setpoint, W of heat for a hot-water draw).
        timezone: the zone whose clock the hours follow.
    """

    values: tuple[float, ...]
    timezone: str = "Europe/Madrid"

    def __init__(self, values: Sequence[float], timezone: str = "Europe/Madrid") -> None:
        vals = tuple(float(v) for v in values)
        if len(vals) not in (24, 168):
            raise ValueError(
                f"a schedule has 24 hourly values (daily) or 168 (weekly), not {len(vals)}"
            )
        if not all(np.isfinite(vals)):
            raise ValueError("schedule values must be finite")
        object.__setattr__(self, "values", vals)
        object.__setattr__(self, "timezone", timezone)
        ZoneInfo(timezone)  # fail now on an unknown zone

    @classmethod
    def constant(cls, value: float, timezone: str = "Europe/Madrid") -> Schedule:
        """The same value at every hour."""
        return cls([value] * 24, timezone)

    @property
    def weekly(self) -> bool:
        """True for a 168-hour schedule."""
        return len(self.values) == 168

    def scaled(self, factor: float) -> Schedule:
        """Every value multiplied by ``factor``."""
        return Schedule([v * factor for v in self.values], self.timezone)

    def daily_sum(self, weekday: int = 0) -> float:
        """Sum of the 24 values of one day (Monday = 0). For a gain in W
        this is the day's energy in Wh on a 24-hour day."""
        if not self.weekly:
            return float(sum(self.values))
        return float(sum(self.values[24 * weekday : 24 * weekday + 24]))

    def sample(self, t: npt.ArrayLike, *, start: datetime | int) -> np.ndarray:
        """The schedule on a model time grid.

        Args:
            t: model times, seconds since ``start``.
            start: the UTC instant of model time zero, as an aware datetime
                or Unix seconds.

        Returns:
            The value of the local hour each ``t`` falls in, so held over a
            grid aligned to the hour it reproduces the schedule exactly.
        """
        t0 = _as_unix(start)
        tz = ZoneInfo(self.timezone)
        ts = np.asarray(t, dtype=float).ravel()
        # One lookup per distinct local hour, not per sample.
        hours = np.floor((t0 + ts) / 3600.0).astype(np.int64)
        values = np.asarray(self.values)
        out = np.empty(ts.shape)
        for h in np.unique(hours):
            local = datetime.fromtimestamp(int(h) * 3600, tz)
            idx = local.hour + (24 * local.weekday() if self.weekly else 0)
            out[hours == h] = values[idx]
        return out


class ClimateSchedule(Schedule):
    """A value that follows the calendar, not just the clock: the sun through
    the windows, which depends on the season as much as on the hour.

    ``profile(local_datetimes) -> values`` is called for the distinct local
    hours a simulation touches. Built for :func:`survey.climate.solar_at`;
    the 24 ``values`` a plain schedule carries are the profile's mean day,
    kept so code that reads them (a daily sum, say) still gets a number.
    """

    def __init__(
        self,
        profile,
        timezone: str = "Europe/Madrid",
        mean_day: Sequence[float] | None = None,
    ) -> None:
        super().__init__(mean_day if mean_day is not None else [0.0] * 24, timezone)
        object.__setattr__(self, "profile", profile)

    def scaled(self, factor: float) -> Schedule:
        return ClimateSchedule(
            lambda stamps, f=factor, p=self.profile: p(stamps) * f,
            self.timezone,
            [v * factor for v in self.values],
        )

    def sample(self, t: npt.ArrayLike, *, start: datetime | int) -> np.ndarray:
        t0 = _as_unix(start)
        tz = ZoneInfo(self.timezone)
        ts = np.asarray(t, dtype=float).ravel()
        hours = np.floor((t0 + ts) / 3600.0).astype(np.int64)
        distinct = np.unique(hours)
        stamps = [datetime.fromtimestamp(int(h) * 3600, tz) for h in distinct]
        values = np.asarray(self.profile(stamps), dtype=float)
        lookup = dict(zip(distinct.tolist(), values.tolist(), strict=True))
        out = np.empty(ts.shape)
        for h in distinct:
            out[hours == h] = lookup[int(h)]
        return out


def _as_unix(start: datetime | int) -> int:
    if isinstance(start, datetime):
        if start.tzinfo is None:
            raise ValueError("start must be timezone-aware (for example UTC)")
        return int(start.astimezone(timezone.utc).timestamp())
    return int(start)


def hot_water_heat(
    litres_per_hour: npt.ArrayLike,
    *,
    tap: float = 313.15,
    cold: float = 288.15,
) -> np.ndarray:
    """Heat drawn from a water heater, in W, by a hot-water flow.

    ``litres_per_hour`` of water delivered at ``tap`` (K) and replaced in the
    tank by mains water at ``cold`` (K) take ρ c V̇ (tap − cold) of heat. This
    is the energy-demand method of EN 15316-3. The draw is the heat the user
    needs, whatever the tank temperature, and the tank model reports whether
    it could still deliver it (``<heater>.temperature`` above ``tap``).

    >>> float(hot_water_heat(60.0, tap=313.15, cold=288.15))  # 60 L/h at 40 °C from 15 °C
    1744.1666666666667
    """
    lph = np.asarray(litres_per_hour, dtype=float)
    if np.any(lph < 0):
        raise ValueError("hot-water flow cannot be negative")
    if tap <= cold:
        raise ValueError("the tap temperature must be above the cold-water temperature")
    return lph / 3600.0 * WATER_HEAT_CAPACITY * (tap - cold)
