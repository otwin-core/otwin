"""Home Assistant exports: long-term statistics and the History panel CSV.

**Long-term statistics** (ARCHITECTURE.md, "Ingest") are hourly and kept forever. The
``homeassistant-statistics`` integration exports them as CSV or TSV with
columns ``statistic_id, unit, start, min, max, mean, sum, state`` (and
optionally ``delta``). ``start`` is the start of the hour, written either in
ISO 8601 or as ``dd.mm.yyyy HH:MM`` in the time zone chosen for the export.

* Energy and volume statistics carry ``sum``, a running total at the *end*
  of each hour. Energy over an hour is the difference between consecutive
  sums: row *k* minus row *k−1* is the energy over
  ``[start_{k-1} + 1 h, start_k + 1 h)``. That stays correct across missing
  hours and meter resets, which HA already folds into ``sum``. The first row
  has no predecessor and yields no value.
* Measurement statistics (temperature, power) carry ``mean`` over the hour.

**History CSV** (History panel → *Download data*) has ``entity_id, state,
last_changed`` with UTC timestamps and no units. The units must therefore be
given (``units={"sensor.fridge_energy": "kWh"}``). Cumulative sensors
(energy, volume) become intervals between consecutive readings. A drop is
read as a reset to zero. ``unavailable`` and ``unknown`` are skipped.

Which household quantity a statistic is follows from its unit unless
``quantities`` says otherwise: energy → ``plug_energy``, power →
``plug_power``, temperature → ``indoor_temperature``. Volume is refused
without a mapping, because m³ may be gas or water.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from ._table import Table, read_table
from .errors import IngestError
from .schema import (
    INSTANT,
    INTERVAL,
    MEAN,
    QUANTITIES,
    REAL,
    Row,
    Series,
    series_from_rows,
)
from .timeutil import DEFAULT_TZ, FoldTracker, parse_datetime, utc_seconds, zone
from .units import dimension_of, parse_unit, to_si

__all__ = ["parse_ha_statistics", "parse_ha_history"]

_DEFAULT_QUANTITY = {
    "energy": "plug_energy",
    "power": "plug_power",
    "temperature": "indoor_temperature",
}
_SKIP_STATES = {"", "unavailable", "unknown", "none", "nan"}


def _quantity_for(
    entity: str, unit: str, quantities: Mapping[str, str] | None, where: dict
) -> str:
    dim = dimension_of(unit)
    q = (quantities or {}).get(entity)
    if q is None:
        q = _DEFAULT_QUANTITY.get(dim)
    if q is None:
        raise IngestError(
            f"{entity} is in {unit}; say which quantity it is, for example "
            f"quantities={{'{entity}': 'gas_volume'}} or 'water_volume'",
            **where,
        )
    spec = QUANTITIES.get(q)
    if spec is None:
        raise IngestError(f"unknown quantity {q!r} for {entity}", **where)
    if spec.dimension != dim:
        raise IngestError(
            f"{entity} is in {unit} ({dim}) but {q} is measured in {spec.dimension}",
            **where,
        )
    return q


def _start_utc(text: str, folds: FoldTracker) -> int:
    naive, is_utc = parse_datetime(text)
    return utc_seconds(naive) if is_utc else folds.utc(naive)


def parse_ha_statistics(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
    quantities: Mapping[str, str] | None = None,
) -> list[Series]:
    """Home Assistant long-term statistics (CSV or TSV) to one :class:`Series` each."""
    tz = zone(timezone)
    t = read_table(data, source)
    c_id = t.require("statistic_id", what="statistic_id")
    c_unit = t.require("unit", "unit_of_measurement", what="unit")
    c_start = t.require("start", what="start")
    c_sum = t.find("sum")
    c_mean = t.find("mean")
    groups: dict[str, list[int]] = defaultdict(list)
    for r, cells in enumerate(t.rows):
        groups[cells[c_id].strip()].append(r)
    out: list[Series] = []
    for entity, idx in groups.items():
        where = {"column": t.headers[c_unit], "line": t.lines[idx[0]], "source": source}
        units = {t.rows[r][c_unit].strip() for r in idx}
        if len(units) > 1:
            raise IngestError(f"{entity} changes unit: {sorted(units)}", **where)
        try:
            unit = parse_unit(units.pop())
        except ValueError as exc:
            raise IngestError(str(exc), **where) from None
        quantity = _quantity_for(entity, unit, quantities, where)
        folds = FoldTracker(tz)
        starts = []
        for r in idx:
            try:
                starts.append(_start_utc(t.rows[r][c_start], folds))
            except ValueError as exc:
                raise t.error(r, c_start, str(exc)) from None
        order = sorted(range(len(idx)), key=lambda k: starts[k])
        rows: list[Row] = []
        if dimension_of(unit) in ("energy", "volume"):
            if c_sum is None:
                raise IngestError(
                    f"{entity} is cumulative ({unit}) but the file has no 'sum' column",
                    column="sum",
                    source=source,
                )
            prev: tuple[int, float] | None = None
            for k in order:
                r = idx[k]
                total = _cell_number(t, r, c_sum)
                if prev is not None:
                    p_start, p_total = prev
                    rows.append(
                        Row(
                            p_start + 3600,
                            starts[k] + 3600,
                            float(to_si(total - p_total, unit)),
                            REAL,
                            t.lines[r],
                        )
                    )
                prev = (starts[k], total)
            kind, value_col = INTERVAL, t.headers[c_sum]
        else:
            if c_mean is None:
                raise IngestError(
                    f"{entity} is a measurement ({unit}) but the file has no 'mean' column",
                    column="mean",
                    source=source,
                )
            for k in order:
                r = idx[k]
                v = float(to_si(_cell_number(t, r, c_mean), unit))
                rows.append(Row(starts[k], starts[k] + 3600, v, REAL, t.lines[r]))
            kind, value_col = MEAN, t.headers[c_mean]
        if rows:
            out.append(
                series_from_rows(
                    rows,
                    quantity=quantity,
                    channel=entity,
                    kind=kind,
                    source=source,
                    value_column=value_col,
                    time_column=t.headers[c_start],
                )
            )
    if not out:
        raise IngestError("the file has no statistics", source=source)
    return out


def _cell_number(t: Table, r: int, c: int) -> float:
    if not t.rows[r][c].strip():
        raise t.error(r, c, "the value is empty")
    return t.number(r, c)


def parse_ha_history(
    data: bytes | str,
    *,
    units: Mapping[str, str],
    source: str = "",
    quantities: Mapping[str, str] | None = None,
) -> list[Series]:
    """The History panel's *Download data* CSV to one :class:`Series` per entity.

    Args:
        units: the unit of every entity to read, as shown in Home Assistant.
            Entities in the file but not in ``units`` are an error, so that
            nothing is dropped silently.
    """
    t = read_table(data, source)
    c_id = t.require("entity_id", what="entity_id")
    c_state = t.require("state", what="state")
    c_time = t.require("last_changed", "last_updated", what="last_changed")
    groups: dict[str, list[int]] = defaultdict(list)
    for r, cells in enumerate(t.rows):
        groups[cells[c_id].strip()].append(r)
    out: list[Series] = []
    for entity, idx in groups.items():
        where = {"column": t.headers[c_id], "line": t.lines[idx[0]], "source": source}
        if entity not in units:
            raise IngestError(
                f"no unit given for {entity}; pass units={{'{entity}': 'kWh'}} "
                "(or whatever Home Assistant shows for it)",
                **where,
            )
        try:
            unit = parse_unit(units[entity])
        except ValueError as exc:
            raise IngestError(str(exc), **where) from None
        quantity = _quantity_for(entity, unit, quantities, where)
        samples: list[tuple[int, float, int]] = []
        for r in idx:
            state = t.rows[r][c_state].strip()
            if state.lower() in _SKIP_STATES:
                continue
            try:
                naive, is_utc = parse_datetime(t.rows[r][c_time])
                if not is_utc:
                    raise ValueError("expected a UTC timestamp (ending in Z or +00:00)")
            except ValueError as exc:
                raise t.error(r, c_time, str(exc)) from None
            samples.append((utc_seconds(naive), t.number(r, c_state), t.lines[r]))
        samples.sort()
        rows: list[Row] = []
        if dimension_of(unit) in ("energy", "volume"):
            for (t0, v0, _), (t1, v1, line) in zip(samples, samples[1:], strict=False):
                delta = v1 - v0 if v1 >= v0 else v1  # a drop is a reset to zero
                rows.append(Row(t0, t1, float(to_si(delta, unit)), REAL, line))
            kind = INTERVAL
        else:
            rows = [Row(ts, ts, float(to_si(v, unit)), REAL, ln) for ts, v, ln in samples]
            kind = INSTANT
        if rows:
            out.append(
                series_from_rows(
                    rows,
                    quantity=quantity,
                    channel=entity,
                    kind=kind,
                    source=source,
                    value_column=t.headers[c_state],
                    time_column=t.headers[c_time],
                )
            )
    if not out:
        raise IngestError("the file has no usable readings", source=source)
    return out
