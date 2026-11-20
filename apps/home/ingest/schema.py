"""The one time-series shape every parser produces.

A :class:`Series` is one measured quantity on one channel (a supply point, a
plug, a bill, a weather cell) as columns of equal length:

``start``, ``end``
    UTC instants in integer seconds since 1970. For an *interval* quantity
    (energy, volume, money) the value is the total over ``[start, end)``. For
    a *mean* quantity (Open-Meteo irradiance, a Home Assistant hourly mean
    temperature) it is the average over ``[start, end)``. For an *instant*
    quantity (a thermometer reading) ``start == end``.
``value``
    float, always in the SI unit of the quantity (:data:`QUANTITIES`).
``quality``
    :data:`REAL` or :data:`ESTIMATED`, as the file said.

Construction validates everything a downstream fit relies on: a known
quantity, a matching kind, finite values, sorted and non-overlapping
intervals, no negative energy, and values that are physically plausible for a
household. That last check is what catches a unit mix-up. A file in Wh read
as kWh shows an hourly import of 161 kWh, which is an average draw of 161 kW,
far above any domestic supply. A temperature in °C read as kelvin shows an
outdoor temperature of 4 K.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from .errors import IngestError
from .units import SI_UNIT, dimension_of, from_si, parse_unit

__all__ = [
    "INTERVAL",
    "MEAN",
    "INSTANT",
    "REAL",
    "ESTIMATED",
    "QuantitySpec",
    "QUANTITIES",
    "SchemaError",
    "Series",
    "Row",
    "series_from_rows",
    "merge",
]

INTERVAL = "interval"
MEAN = "mean"
INSTANT = "instant"

REAL = 0
ESTIMATED = 1


@dataclass(frozen=True)
class QuantitySpec:
    """What a quantity is and which values are plausible for one household.

    ``max_rate`` bounds an interval quantity's value divided by the interval
    length, in SI per second (W for energy, m^3/s for volume). ``bounds``
    limits a mean or instant value. ``None`` means unchecked.
    """

    name: str
    dimension: str
    kinds: tuple[str, ...]
    display_unit: str
    nonnegative: bool = True
    max_rate: float | None = None
    bounds: tuple[float, float] | None = None
    description: str = ""


_HOUSE_ELECTRIC_MAX_W = 50e3  # domestic supplies are <= 15 kW; generous margin

#: Every quantity a Series may carry.
QUANTITIES: dict[str, QuantitySpec] = {
    q.name: q
    for q in [
        QuantitySpec(
            "electricity_import",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=_HOUSE_ELECTRIC_MAX_W,
            description="energy taken from the grid at the supply point",
        ),
        QuantitySpec(
            "electricity_export",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=_HOUSE_ELECTRIC_MAX_W,
            description="energy fed into the grid (solar surplus)",
        ),
        QuantitySpec(
            "electricity_self_consumption",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=_HOUSE_ELECTRIC_MAX_W,
            description="solar energy used in the house without passing the meter",
        ),
        QuantitySpec(
            "plug_energy",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=_HOUSE_ELECTRIC_MAX_W,
            description="energy through a smart plug or a sub-meter",
        ),
        QuantitySpec(
            "plug_power",
            "power",
            (INSTANT, MEAN),
            "W",
            bounds=(0.0, _HOUSE_ELECTRIC_MAX_W),
            description="power through a smart plug at an instant",
        ),
        QuantitySpec(
            "gas_energy",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=100e3,  # domestic boilers are 24-35 kW
            description="gas energy as billed (m^3 x Fc x PCS)",
        ),
        QuantitySpec(
            "gas_volume",
            "volume",
            (INTERVAL,),
            "m^3",
            max_rate=10.0 / 3600.0,
            description="gas volume as read on the meter",
        ),
        QuantitySpec(
            "water_volume",
            "volume",
            (INTERVAL,),
            "m^3",
            max_rate=5.0 / 3600.0,
            description="water volume as read on the meter",
        ),
        QuantitySpec(
            "electricity_billed",
            "energy",
            (INTERVAL,),
            "kWh",
            max_rate=_HOUSE_ELECTRIC_MAX_W,
            description="electricity as billed over a billing period",
        ),
        QuantitySpec(
            "electricity_cost",
            "currency",
            (INTERVAL,),
            "EUR",
            nonnegative=False,
        ),
        QuantitySpec("gas_cost", "currency", (INTERVAL,), "EUR", nonnegative=False),
        QuantitySpec("water_cost", "currency", (INTERVAL,), "EUR", nonnegative=False),
        QuantitySpec(
            "outdoor_temperature",
            "temperature",
            (INSTANT, MEAN),
            "degC",
            bounds=(223.15, 333.15),  # -50 to +60 degC
            description="air temperature outside the house",
        ),
        QuantitySpec(
            "indoor_temperature",
            "temperature",
            (INSTANT, MEAN),
            "degC",
            bounds=(263.15, 323.15),  # -10 to +50 degC
            description="air temperature inside the house",
        ),
        QuantitySpec(
            "solar_irradiance",
            "irradiance",
            (MEAN, INSTANT),
            "W/m^2",
            bounds=(0.0, 1500.0),
            description="global horizontal irradiance",
        ),
    ]
}


class SchemaError(ValueError):
    """A Series that breaks a rule. ``index`` is the offending position, and
    ``field`` is ``"value"`` or ``"time"`` depending on which column is at fault."""

    def __init__(self, message: str, index: int | None = None, field: str = "value"):
        super().__init__(message)
        self.index = index
        self.field = field


def _first(mask: np.ndarray) -> int | None:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if idx.size else None


@dataclass(frozen=True, eq=False)
class Series:
    """One quantity on one channel as aligned columns; see the module docstring."""

    quantity: str
    channel: str
    kind: str
    start: np.ndarray
    end: np.ndarray
    value: np.ndarray
    quality: np.ndarray = field(default=None)  # type: ignore[assignment]
    source: str = ""

    def __post_init__(self) -> None:
        spec = QUANTITIES.get(self.quantity)
        if spec is None:
            raise SchemaError(
                f"unknown quantity {self.quantity!r}; known: {', '.join(QUANTITIES)}"
            )
        if self.kind not in spec.kinds:
            raise SchemaError(
                f"{self.quantity} cannot be of kind {self.kind!r}; allowed: {spec.kinds}"
            )
        start = np.asarray(self.start, dtype=np.int64).ravel()
        end = np.asarray(self.end, dtype=np.int64).ravel()
        value = np.asarray(self.value, dtype=float).ravel()
        quality = (
            np.zeros(value.shape, dtype=np.int8)
            if self.quality is None
            else np.asarray(self.quality, dtype=np.int8).ravel()
        )
        if not (start.shape == end.shape == value.shape == quality.shape):
            raise SchemaError("start, end, value and quality differ in length")
        for name, arr in (("start", start), ("end", end), ("value", value)):
            object.__setattr__(self, name, arr)
            arr.setflags(write=False)
        object.__setattr__(self, "quality", quality)
        quality.setflags(write=False)
        self._validate(spec)

    def _validate(self, spec: QuantitySpec) -> None:
        s, e, v = self.start, self.end, self.value
        if (i := _first(~np.isfinite(v))) is not None:
            raise SchemaError("value is not a finite number", i)
        if (i := _first(~np.isin(self.quality, (REAL, ESTIMATED)))) is not None:
            raise SchemaError("quality is neither real nor estimated", i)
        if self.kind == INSTANT:
            if (i := _first(e != s)) is not None:
                raise SchemaError("an instant reading must have end == start", i, "time")
        elif (i := _first(e <= s)) is not None:
            raise SchemaError("the interval ends before it starts", i, "time")
        if s.size > 1:
            if (i := _first(s[1:] < s[:-1])) is not None:
                raise SchemaError("readings are not in time order", i + 1, "time")
            if self.kind == INSTANT:
                if (i := _first(s[1:] == s[:-1])) is not None:
                    raise SchemaError("two readings at the same instant", i + 1, "time")
            elif (i := _first(s[1:] < e[:-1])) is not None:
                raise SchemaError(
                    "this interval overlaps the previous one", i + 1, "time"
                )
        if spec.nonnegative and (i := _first(v < 0)) is not None:
            raise SchemaError(f"{self.quantity} cannot be negative ({v[i]:g})", i)
        if self.kind == INTERVAL and spec.max_rate is not None and v.size:
            rate = v / (e - s)
            if (i := _first(rate > spec.max_rate)) is not None:
                shown = from_si(v[i], parse_unit(spec.display_unit))
                hours = (e[i] - s[i]) / 3600
                raise SchemaError(
                    f"{shown:g} {spec.display_unit} in {hours:g} h is not plausible "
                    f"for a household; check the unit of this column",
                    i,
                )
        if spec.bounds is not None and v.size:
            lo, hi = spec.bounds
            if (i := _first((v < lo) | (v > hi))) is not None:
                unit = parse_unit(spec.display_unit)
                shown = float(from_si(v[i], unit))
                lo_s, hi_s = (float(from_si(b, unit)) for b in spec.bounds)
                raise SchemaError(
                    f"{shown:g} {spec.display_unit} is outside the plausible range "
                    f"[{lo_s:g}, {hi_s:g}]; check the unit of this column",
                    i,
                )

    # ------------------------------------------------------------------ view
    @property
    def unit(self) -> str:
        """The SI unit the values are stored in."""
        return SI_UNIT[QUANTITIES[self.quantity].dimension]

    def __len__(self) -> int:
        return int(self.value.size)

    def values_in(self, unit: str) -> np.ndarray:
        """The values converted to ``unit`` (any spelling :func:`parse_unit` knows)."""
        canonical = parse_unit(unit)
        spec = QUANTITIES[self.quantity]
        if dimension_of(canonical) != spec.dimension:
            raise ValueError(f"{unit!r} is not a unit of {spec.dimension}")
        return from_si(self.value, canonical)

    def __repr__(self) -> str:
        n = len(self)
        span = ""
        if n:
            a = datetime.fromtimestamp(int(self.start[0]), timezone.utc)
            b = datetime.fromtimestamp(int(self.end[-1]), timezone.utc)
            span = f", {a:%Y-%m-%d %H:%M}Z..{b:%Y-%m-%d %H:%M}Z"
        est = int(np.count_nonzero(self.quality == ESTIMATED))
        return (
            f"Series({self.quantity}, channel={self.channel!r}, kind={self.kind}, "
            f"n={n}{span}, estimated={est})"
        )


@dataclass
class Row:
    """One reading as a parser collects it, with the file position it came from."""

    start: int
    end: int
    value: float  # SI
    quality: int = REAL
    line: int | None = None


def series_from_rows(
    rows: Sequence[Row],
    *,
    quantity: str,
    channel: str,
    kind: str,
    source: str,
    value_column: str | None,
    time_column: str | None,
    line_label: str = "line",
) -> Series:
    """Sort ``rows`` by time and build a :class:`Series`.

    A schema violation becomes an :class:`IngestError` naming the file line
    and the column at fault: ``value_column`` for a bad value, ``time_column``
    for a bad or overlapping time.
    """
    ordered = sorted(rows, key=lambda r: (r.start, r.end))
    try:
        return Series(
            quantity=quantity,
            channel=channel,
            kind=kind,
            start=np.array([r.start for r in ordered], dtype=np.int64),
            end=np.array([r.end for r in ordered], dtype=np.int64),
            value=np.array([r.value for r in ordered], dtype=float),
            quality=np.array([r.quality for r in ordered], dtype=np.int8),
            source=source,
        )
    except SchemaError as exc:
        line = ordered[exc.index].line if exc.index is not None else None
        column = time_column if exc.field == "time" else value_column
        raise IngestError(
            str(exc), column=column, line=line, line_label=line_label, source=source
        ) from None


def merge(*series: Series, rtol: float = 1e-9) -> Series:
    """Join series of the same quantity and channel, dropping exact repeats.

    Overlapping exports (a Tapo workbook every week, a Datadis download every
    month) repeat the same intervals. A repeat with the same value is dropped.
    A repeat with a *different* value is a conflict and raises, because
    silently picking one would hide a problem in the data.
    """
    if not series:
        raise ValueError("merge needs at least one series")
    first = series[0]
    for s in series[1:]:
        if (s.quantity, s.channel, s.kind) != (first.quantity, first.channel, first.kind):
            raise ValueError(
                f"cannot merge {s.quantity}/{s.channel}/{s.kind} into "
                f"{first.quantity}/{first.channel}/{first.kind}"
            )
    start = np.concatenate([s.start for s in series])
    end = np.concatenate([s.end for s in series])
    value = np.concatenate([s.value for s in series])
    quality = np.concatenate([s.quality for s in series])
    order = np.lexsort((end, start))
    start, end, value, quality = start[order], end[order], value[order], quality[order]
    keep = np.ones(start.size, dtype=bool)
    same = (start[1:] == start[:-1]) & (end[1:] == end[:-1])
    for i in np.flatnonzero(same) + 1:
        if not np.isclose(value[i], value[i - 1], rtol=rtol, atol=0.0):
            raise ValueError(
                f"conflicting values for the same interval starting at {start[i]}: "
                f"{value[i - 1]:g} and {value[i]:g}"
            )
        keep[i] = False
        quality[i - 1] = min(quality[i - 1], quality[i])  # a real reading wins
    sources = sorted({s.source for s in series if s.source})
    return Series(
        quantity=first.quantity,
        channel=first.channel,
        kind=first.kind,
        start=start[keep],
        end=end[keep],
        value=value[keep],
        quality=quality[keep],
        source="; ".join(sources),
    )
