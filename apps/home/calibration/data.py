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
from dataclasses import dataclass, field, replace
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
        periods: for a record made of several separate periods (three
            winter months with gaps between them), the hour index and the
            start of each period after the first, ``((744, start2), ...)``.
            The hours are joined end to end; the twin simulates each period
            on its own, from its own spin-up. Build it with :meth:`join`.
        indoor_c: the indoor temperature, °C, the hourly mean of what an
            interior thermometer read; ``NaN`` where it read nothing. It shows
            how the home warms and cools, which no meter does.
        check_length: ``False`` for one piece of a longer record: the piece
            may then be shorter than :data:`MIN_DAYS` (the joined record is
            checked as a whole). Consistency is checked either way.

    Raises:
        NotEnoughData: the record is too short or too incomplete.
        ValueError: the record is inconsistent (lengths, units, signs).
    """

    start: datetime
    electricity_kwh: np.ndarray
    outdoor_c: np.ndarray
    measured: Mapping[str, np.ndarray] = field(default_factory=dict)
    gas_bills: tuple[GasBill, ...] = ()
    periods: tuple[tuple[int, datetime], ...] = ()
    indoor_c: np.ndarray | None = None
    check_length: bool = field(default=True, repr=False, compare=False)

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
        if self.indoor_c is not None:
            ti = np.asarray(self.indoor_c, dtype=float).ravel()
            if ti.shape != e.shape:
                raise ValueError(
                    f"the indoor temperature has {ti.size} hours, not {e.size}"
                )
            seen = ti[np.isfinite(ti)]
            if seen.size and (seen.min() < -10.0 or seen.max() > 45.0):
                hint = " It looks like kelvin; give °C." if seen.min() > 200 else ""
                raise ValueError(
                    f"indoor temperatures from {seen.min():g} to {seen.max():g} °C are "
                    f"not plausible.{hint}"
                )
            object.__setattr__(self, "indoor_c", ti if seen.size else None)
        n = e.size
        need = MIN_DAYS * 24
        periods = tuple((int(i), when) for i, when in self.periods)
        object.__setattr__(self, "periods", periods)
        prev_i, prev_t = 0, self.start.timestamp()
        for i, when in periods:
            if when.tzinfo is None or when.minute or when.second or when.microsecond:
                raise ValueError("each period must start on the hour, timezone-aware")
            if not prev_i < i < n:
                raise ValueError(
                    f"period starts must be inside the record, in order: {i}"
                )
            if when.timestamp() < prev_t + 3600 * (i - prev_i):
                raise ValueError(
                    f"the period starting {when:%d/%m/%Y} overlaps the one before"
                )
            prev_i, prev_t = i, when.timestamp()
        bills = tuple(sorted(self.gas_bills, key=lambda b: b.start))
        object.__setattr__(self, "gas_bills", bills)
        for a, b in zip(bills, bills[1:], strict=False):
            if b.start < a.end:
                raise ValueError(
                    f"gas bills overlap: {a.label or a.start} and {b.label or b.start}"
                )
        edges = [0, *[i for i, _ in periods], n]
        for b in bills:
            if not 0 <= b.start < b.end <= n:
                raise ValueError(f"gas bill {b.label or b.start} lies outside the record")
            if any(b.start < x < b.end for x in edges[1:-1]):
                raise ValueError(f"gas bill {b.label or b.start} spans two periods")
            if b.kwh < 0:
                raise ValueError(f"gas bill {b.label or b.start} has negative energy")
        if self.check_length and n < need:
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
        if self.check_length and bills and billed_hours < need and n - n_missing < need:
            raise NotEnoughData(
                f"Your gas bills cover {_days_and_hours(billed_hours)} and your hourly "
                f"electricity {_days_and_hours(n - n_missing)}; calibration needs at least "
                f"{MIN_DAYS} days of one or the other. Add more bills."
            )
        # With bills, the bills carry the record and electricity may cover part of it.
        if self.check_length and not bills and n_missing > MAX_MISSING_FRACTION * n:
            first = int(np.flatnonzero(missing)[0])
            raise NotEnoughData(
                f"{n_missing} of the {n} hours have no electricity reading "
                f"({100 * n_missing / n:.0f}%); calibration needs readings for at "
                f"least {100 * (1 - MAX_MISSING_FRACTION):.0f}% of the hours. The "
                f"first missing hour starts {self.hour_label(first)}."
            )
        if self.check_length and not bills and n - n_missing < need:
            raise NotEnoughData(
                f"Only {_days_and_hours(n - n_missing)} of this record have electricity "
                f"readings; calibration needs at least {MIN_DAYS} days. Download a "
                "longer period."
            )
        if self.check_length and not bills and np.all(e[~missing] == 0):
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
    def indoor_observed(self) -> np.ndarray:
        """Boolean mask of the hours with an indoor temperature."""
        if self.indoor_c is None:
            return np.zeros(self.hours, dtype=bool)
        return np.isfinite(self.indoor_c)

    @property
    def observed(self) -> np.ndarray:
        """Boolean mask of the hours that have an electricity reading."""
        return np.isfinite(self.electricity_kwh)

    @property
    def spans(self) -> list[tuple[int, int, datetime]]:
        """Each period as ``(first hour, end hour, start)``; one for a plain record."""
        starts = [(0, self.start), *self.periods]
        ends = [i for i, _ in self.periods] + [self.hours]
        return [(i, j, when) for (i, when), j in zip(starts, ends, strict=True)]

    def timestamps(self) -> np.ndarray:
        """The UTC instant (Unix seconds) each hour starts, period by period."""
        out = np.empty(self.hours, dtype=np.int64)
        for i, j, when in self.spans:
            out[i:j] = int(when.timestamp()) + 3600 * np.arange(j - i)
        return out

    def hour_label(self, i: int) -> str:
        """The start of hour ``i``, readable, in the record's own time zone."""
        # elapsed hours, so a label after a clock change is the real local hour
        i0, _, when0 = next(sp for sp in reversed(self.spans) if sp[0] <= int(i))
        when = (when0.astimezone(timezone.utc) + timedelta(hours=int(i) - i0)).astimezone(
            self.start.tzinfo
        )
        return f"{when:%d/%m/%Y %H:%M}"

    def period(self, k: int) -> HourlyData:
        """Period ``k`` alone, as a plain record (its bills, its hours)."""
        i, j, when = self.spans[k]
        bills = tuple(
            replace(b, start=b.start - i, end=b.end - i)
            for b in self.gas_bills
            if i <= b.start and b.end <= j
        )
        return HourlyData(
            when,
            self.electricity_kwh[i:j],
            self.outdoor_c[i:j],
            {name: v[i:j] for name, v in self.measured.items()},
            bills,
            indoor_c=None if self.indoor_c is None else self.indoor_c[i:j],
            check_length=False,
        )

    @classmethod
    def join(cls, records: list[HourlyData]) -> HourlyData:
        """Separate periods as one record: their hours end to end, each period
        simulated on its own. Records must be in time order, not overlapping."""
        if not records:
            raise ValueError("give at least one record")
        records = sorted(records, key=lambda r: r.start.timestamp())
        if len(records) == 1:
            return records[0]
        names = set(records[0].measured)
        if any(set(r.measured) != names for r in records):
            raise ValueError("every period must carry the same measured inputs")
        offsets = np.cumsum([0] + [r.hours for r in records])
        periods = []
        bills = []
        for r, off in zip(records, offsets[:-1], strict=False):
            if off:
                periods.append((int(off), r.start))
            for b in r.gas_bills:
                bills.append(replace(b, start=b.start + int(off), end=b.end + int(off)))
            for sub in r.periods:
                periods.append((sub[0] + int(off), sub[1]))
        return cls(
            records[0].start,
            np.concatenate([r.electricity_kwh for r in records]),
            np.concatenate([r.outdoor_c for r in records]),
            {n: np.concatenate([r.measured[n] for r in records]) for n in names},
            tuple(bills),
            tuple(sorted(periods)),
            indoor_c=(
                None
                if all(r.indoor_c is None for r in records)
                else np.concatenate(
                    [
                        np.full(r.hours, np.nan) if r.indoor_c is None else r.indoor_c
                        for r in records
                    ]
                )
            ),
        )

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
        indoor=None,
        check_length: bool = True,
    ) -> HourlyData:
        """Align an :mod:`ingest` electricity series with an outdoor temperature.

        Args:
            electricity: an ``ingest.Series`` of hourly ``electricity_import``,
                or ``None`` when gas bills carry the record.
            outdoor: an ``ingest.Series`` of ``outdoor_temperature``.
            indoor: optional ``ingest.Series`` of ``indoor_temperature`` (an
                interior thermometer): readings are averaged hour by hour, an
                hour with none is missing.
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
        if indoor is not None and indoor.quantity != "indoor_temperature":
            raise ValueError(f"expected indoor_temperature, got {indoor.quantity}")
        if gas is not None and gas.quantity != "gas_energy":
            raise ValueError(f"expected gas_energy, got {gas.quantity}")
        if electricity is not None:
            dur = electricity.end - electricity.start
            if dur.size and not np.all(dur == 3600):
                raise ValueError(
                    "electricity must be hourly; aggregate quarter-hours first"
                )
        spans = [s for s in (electricity, gas) if s is not None and len(s)]
        t0 = (
            min(int(s.start[0]) for s in spans)
            if start is None
            else int(start.timestamp())
        )
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
            for s_, e_, v, q in zip(
                gas.start, gas.end, gas.value, gas.quality, strict=True
            ):
                if s_ >= t0 and e_ <= t1:
                    bills.append(
                        GasBill(
                            int((s_ - t0) // 3600),
                            int((e_ - t0) // 3600),
                            float(v) / 3.6e6,
                            bool(q),
                            f"bill {len(bills) + 1}",
                        )
                    )
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
        indoor_c = None
        if indoor is not None and len(indoor):
            # the mean of the readings that fall in each hour
            bins = (np.asarray(indoor.start, dtype=np.int64) - t0) // 3600
            ok = (bins >= 0) & (bins < hours.size)
            sums = np.bincount(
                bins[ok], weights=indoor.value[ok] - 273.15, minlength=hours.size
            )
            counts = np.bincount(bins[ok], minlength=hours.size)
            with np.errstate(invalid="ignore", divide="ignore"):
                indoor_c = np.where(counts > 0, sums / counts, np.nan)
        return cls(
            start_dt,
            kwh,
            temp,
            gas_bills=tuple(bills),
            indoor_c=indoor_c,
            check_length=check_length,
        )
