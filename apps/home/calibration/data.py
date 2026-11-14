"""The data a calibration needs: one month of hourly electricity and weather.

:class:`HourlyData` holds, for each hour of the record:

* the electricity the home took from the grid in that hour, kWh. That is
  what Datadis and the distributor portals give, read by :mod:`ingest`;
* the outdoor temperature at the start of the hour, °C (Open-Meteo).

Construction checks everything a fit relies on and refuses, in words a
householder can act on, a record that cannot support one: shorter than
:data:`MIN_DAYS`, too many missing hours, missing weather, negative
readings, temperatures that are plainly in the wrong unit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

__all__ = ["HourlyData", "GasBill", "NotEnoughData", "MIN_DAYS", "MAX_MISSING_FRACTION"]

#: The shortest record a calibration accepts: four weeks, about one month.
#: Shorter, and a fortnight of mild weather can hide how the home behaves
#: when it is cold, which is the whole point.
MIN_DAYS = 28
#: The largest share of hours that may lack an electricity reading.
MAX_MISSING_FRACTION = 0.10
#: Gaps in the outdoor temperature up to this many hours are interpolated.
MAX_WEATHER_GAP_HOURS = 3


class NotEnoughData(ValueError):
    """The record cannot support a calibration. The message says why and what
    to download instead."""


def _days_and_hours(hours: int) -> str:
    d, h = divmod(int(hours), 24)
    parts = []
    if d:
        parts.append(f"{d} day{'s' if d != 1 else ''}")
    if h or not d:
        parts.append(f"{h} hour{'s' if h != 1 else ''}")
    return " and ".join(parts)


@dataclass(frozen=True)
class GasBill:
    """One gas bill, placed on the record's hours.

    ``start``/``end`` are hour indices into the record (end exclusive): the
    bill covers local midnight of its first reading date to local midnight of
    its last. ``kwh`` is the energy billed (m³ × Fc × PCS, as printed).
    """

    start: int
    end: int
    kwh: float
    estimated: bool = False
    label: str = ""

    @property
    def days(self) -> float:
        """Length of the bill, days."""
        return (self.end - self.start) / 24.0


@dataclass(frozen=True)
class HourlyData:
    """One record of hourly electricity and outdoor temperature.

    Args:
        start: the first hour, a timezone-aware datetime on the hour.
        electricity_kwh: electricity taken from the grid in each hour, kWh.
            ``NaN`` marks an hour without a reading.
        outdoor_c: outdoor temperature at the start of each hour, °C.
        measured: further hourly series the home's twin takes as inputs,
            by input name, in the input's unit (W for a plug, say). Optional.
        gas_bills: gas bills inside the record (:class:`GasBill`). With bills,
            the record may be a whole year and the hourly electricity may
            cover only part of it: the bills then carry the heating.

    Raises:
        NotEnoughData: the record is too short or too incomplete.
        ValueError: the record is inconsistent (lengths, units, signs).
    """

    start: datetime
    electricity_kwh: np.ndarray
    outdoor_c: np.ndarray
    measured: Mapping[str, np.ndarray] = field(default_factory=dict)
    gas_bills: tuple[GasBill, ...] = ()

    def __post_init__(self) -> None:
        if self.start.tzinfo is None:
            raise ValueError("start must be timezone-aware (for example UTC)")
        if self.start.minute or self.start.second or self.start.microsecond:
            raise ValueError(f"start must be on the hour, not {self.start:%H:%M:%S}")
        e = np.asarray(self.electricity_kwh, dtype=float).ravel()
        o = np.asarray(self.outdoor_c, dtype=float).ravel()
        object.__setattr__(self, "electricity_kwh", e)
        object.__setattr__(self, "outdoor_c", o)
        if e.shape != o.shape:
            raise ValueError(
                f"electricity has {e.size} hours but the outdoor temperature has {o.size}"
            )
        measured = {}
        for name, arr in self.measured.items():
            a = np.asarray(arr, dtype=float).ravel()
            if a.shape != e.shape:
                raise ValueError(
                    f"measured input {name!r} has {a.size} hours, not {e.size}"
                )
            measured[name] = a
        object.__setattr__(self, "measured", measured)
        n = e.size
        need = MIN_DAYS * 24
        bills = tuple(sorted(self.gas_bills, key=lambda b: b.start))
        object.__setattr__(self, "gas_bills", bills)
        for a, b in zip(bills, bills[1:], strict=False):
            if b.start < a.end:
                raise ValueError(f"gas bills overlap: {a.label or a.start} and {b.label or b.start}")
        for b in bills:
            if not 0 <= b.start < b.end <= n:
                raise ValueError(f"gas bill {b.label or b.start} lies outside the record")
            if b.kwh < 0:
                raise ValueError(f"gas bill {b.label or b.start} has negative energy")
        if n < need:
            raise NotEnoughData(
                f"Calibration needs at least {MIN_DAYS} days of hourly electricity, "
                f"about one month; this record covers {_days_and_hours(n)}. "
                "Download a full month from Datadis or your distributor's website "
                "and try again."
            )
        bad = np.flatnonzero(np.isfinite(e) & (e < 0))
        if bad.size:
            i = int(bad[0])
            raise ValueError(
                f"electricity cannot be negative: {e[i]:g} kWh in the hour starting "
                f"{self.hour_label(i)}"
            )
        missing = ~np.isfinite(e)
        n_missing = int(missing.sum())
        billed_hours = sum(b.end - b.start for b in bills)
        if bills and billed_hours < need and n - n_missing < need:
            raise NotEnoughData(
                f"Your gas bills cover {_days_and_hours(billed_hours)} and your hourly "
                f"electricity {_days_and_hours(n - n_missing)}; calibration needs at least "
                f"{MIN_DAYS} days of one or the other. Add more bills."
            )
        # With bills, the bills carry the record and electricity may cover part of it.
        if not bills and n_missing > MAX_MISSING_FRACTION * n:
            first = int(np.flatnonzero(missing)[0])
            raise NotEnoughData(
                f"{n_missing} of the {n} hours have no electricity reading "
                f"({100 * n_missing / n:.0f}%); calibration needs readings for at "
                f"least {100 * (1 - MAX_MISSING_FRACTION):.0f}% of the hours. The "
                f"first missing hour starts {self.hour_label(first)}."
            )
        if not bills and n - n_missing < need:
            raise NotEnoughData(
                f"Only {_days_and_hours(n - n_missing)} of this record have electricity "
                f"readings; calibration needs at least {MIN_DAYS} days. Download a "
                "longer period."
            )
        if not bills and np.all(e[~missing] == 0):
            raise NotEnoughData(
                "Every electricity reading is zero; nothing to calibrate."
            )
        gaps = ~np.isfinite(o)
        if gaps.any():
            first = int(np.flatnonzero(gaps)[0])
            raise NotEnoughData(
                f"The outdoor temperature is missing for {int(gaps.sum())} hours, the "
                f"first starting {self.hour_label(first)}. Download the weather for "
                "the whole period (Open-Meteo, timeformat=unixtime)."
            )
        lo, hi = float(o.min()), float(o.max())
        if lo < -45.0 or hi > 55.0:
            hint = " It looks like kelvin; give °C." if lo > 200 else ""
            raise ValueError(
                f"outdoor temperatures from {lo:g} to {hi:g} °C are not plausible for "
                f"Spain.{hint}"
            )

    # ------------------------------------------------------------------ view
    @property
    def hours(self) -> int:
        """Number of hours in the record."""
        return int(self.electricity_kwh.size)

    @property
    def days(self) -> float:
        """Length of the record in days."""
        return self.hours / 24.0

    @property
    def t(self) -> np.ndarray:
        """Start of each hour in model seconds from :attr:`start`."""
        return np.arange(self.hours) * 3600.0

    @property
    def observed(self) -> np.ndarray:
        """Boolean mask of the hours that have an electricity reading."""
        return np.isfinite(self.electricity_kwh)

    def hour_label(self, i: int) -> str:
        """The start of hour ``i``, readable, in the record's own time zone."""
        when = self.start + timedelta(hours=int(i))
        return f"{when:%d/%m/%Y %H:%M}"

    # ---------------------------------------------------------------- build
    @classmethod
    def from_series(
        cls,
        electricity,
        outdoor,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        timezone_name: str = "Europe/Madrid",
        gas=None,
    ) -> HourlyData:
        """Align an :mod:`ingest` electricity series with an outdoor temperature.

        Args:
            electricity: an ``ingest.Series`` of hourly ``electricity_import``,
                or ``None`` when gas bills carry the record.
            outdoor: an ``ingest.Series`` of ``outdoor_temperature``.
            gas: optional ``ingest.Series`` of ``gas_energy`` (from the gas
                bill parser). Bills wholly inside the record become
                :class:`GasBill` s; bills sticking out of it are left out.
            start, end: optional bounds (aware datetimes on the hour); the
                electricity record's first and last hour otherwise.
            timezone_name: the zone hour labels in messages are shown in.

        Hours without a reading become missing values; outdoor gaps up to
        :data:`MAX_WEATHER_GAP_HOURS` are interpolated linearly, longer ones
        are left missing (and refused by the constructor).
        """
        from zoneinfo import ZoneInfo

        if electricity is None and gas is None:
            raise ValueError("give the electricity, the gas bills, or both")
        if electricity is not None and electricity.quantity != "electricity_import":
            raise ValueError(f"expected electricity_import, got {electricity.quantity}")
        if outdoor.quantity != "outdoor_temperature":
            raise ValueError(f"expected outdoor_temperature, got {outdoor.quantity}")
        if gas is not None and gas.quantity != "gas_energy":
            raise ValueError(f"expected gas_energy, got {gas.quantity}")
        if electricity is not None:
            dur = electricity.end - electricity.start
            if dur.size and not np.all(dur == 3600):
                raise ValueError("electricity must be hourly; aggregate quarter-hours first")
        spans = [s for s in (electricity, gas) if s is not None and len(s)]
        t0 = min(int(s.start[0]) for s in spans) if start is None else int(start.timestamp())
        t1 = max(int(s.end[-1]) for s in spans) if end is None else int(end.timestamp())
        if t0 % 3600 or t1 % 3600:
            raise ValueError("start and end must fall on whole hours")
        hours = np.arange(t0, t1, 3600, dtype=np.int64)
        kwh = np.full(hours.size, np.nan)
        if electricity is not None:
            idx = np.searchsorted(hours, electricity.start)
            ok = (idx < hours.size) & (
                hours[np.minimum(idx, hours.size - 1)] == electricity.start
            )
            kwh[idx[ok]] = electricity.value[ok] / 3.6e6
        bills = []
        if gas is not None:
            for s_, e_, v, q in zip(gas.start, gas.end, gas.value, gas.quality, strict=True):
                if s_ >= t0 and e_ <= t1:
                    bills.append(GasBill(int((s_ - t0) // 3600), int((e_ - t0) // 3600),
                                         float(v) / 3.6e6, bool(q), f"bill {len(bills) + 1}"))
        # outdoor: instants (or hourly means, read at their start) in K
        o_t = outdoor.start.astype(float)
        o_v = outdoor.value - 273.15
        temp = np.full(hours.size, np.nan)
        exact = np.searchsorted(o_t, hours)
        hit = (exact < o_t.size) & (o_t[np.minimum(exact, o_t.size - 1)] == hours)
        temp[hit] = o_v[exact[hit]]
        if (~hit).any() and o_t.size >= 2:
            interp = np.interp(hours, o_t, o_v, left=np.nan, right=np.nan)
            # distance to the nearest real sample on each side, in hours
            right = np.searchsorted(o_t, hours)
            left_gap = (hours - o_t[np.clip(right - 1, 0, o_t.size - 1)]) / 3600.0
            right_gap = (o_t[np.clip(right, 0, o_t.size - 1)] - hours) / 3600.0
            small = (left_gap + right_gap) <= MAX_WEATHER_GAP_HOURS + 1
            fill = ~hit & small & np.isfinite(interp)
            temp[fill] = interp[fill]
        zone_ = ZoneInfo(timezone_name)
        start_dt = datetime.fromtimestamp(t0, timezone.utc).astimezone(zone_)
        return cls(start_dt, kwh, temp, gas_bills=tuple(bills))
