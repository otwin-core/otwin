"""Any CSV, given a map of which column is what.

Households have meters and loggers no parser here knows. :func:`describe_csv`
looks at such a file and suggests what each column might be. The user (or the
app's import screen) confirms it as a :class:`ColumnMap`, and
:func:`parse_mapped` reads the file with the same unit, time and
plausibility checks as every built-in parser.

Example: a pulse logger on the water meter writing cumulative litres::

    Fecha y hora;Lectura (L)
    01/03/2025 00:00;1520300
    01/03/2025 00:15;1520342

    ColumnMap(quantity="water_volume", value="Lectura (L)",
              time="Fecha y hora", cumulative=True)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

from ._table import Table, normalize_header, parse_number, read_table
from .electricity import QUALITY
from .errors import IngestError
from .schema import INSTANT, INTERVAL, QUANTITIES, REAL, Row, Series, series_from_rows
from .timeutil import DEFAULT_TZ, FoldTracker, parse_datetime, utc_seconds, zone
from .units import dimension_of, parse_unit, to_si, unit_in_header

__all__ = ["ColumnMap", "parse_mapped", "describe_csv", "CsvDescription", "ColumnGuess"]


@dataclass(frozen=True)
class ColumnMap:
    """How to read one quantity out of an unknown CSV.

    Columns are named by their header exactly as written in the file (or in
    its normalised form, lower case without accents).

    Args:
        quantity: one of :data:`ingest.QUANTITIES`.
        value: the column holding the values.
        unit: the unit of ``value``. If omitted, it must be in the header,
            e.g. ``"Consumo (kWh)"`` or ``"Energia_kWh"``.
        time: a single time column. For intervals, ``label`` says which end
            of the interval it marks.
        start, end: two columns giving each interval explicitly, instead of
            ``time``.
        time_format: ``None`` to recognise the usual date and time layouts,
            ``"unix"`` or ``"unix_ms"`` for epoch numbers, or a ``strptime``
            pattern.
        timezone: zone of times written without an offset.
        label: ``"start"`` or ``"end"``, for intervals given by one time column.
        interval: interval length in seconds when ``time`` is a single column
            and ``cumulative`` is false. Inferred from the most common
            spacing if omitted.
        cumulative: the values are meter readings, and consecutive
            differences are the consumption between them.
        kind: ``"interval"``, ``"mean"`` or ``"instant"``. Defaults to the
            quantity's first kind.
        quality: optional column with ``R``/``E``/``real``/``estimada``.
        channel: the name the household gives this meter.
        delimiter, decimal: override detection.
    """

    quantity: str
    value: str
    unit: str | None = None
    time: str | None = None
    start: str | None = None
    end: str | None = None
    time_format: str | None = None
    timezone: str = DEFAULT_TZ
    label: str = "start"
    interval: int | None = None
    cumulative: bool = False
    kind: str | None = None
    quality: str | None = None
    channel: str = ""
    delimiter: str | None = None
    decimal: str | None = None


def _column(t: Table, name: str, role: str) -> int:
    if name in t.headers:
        return t.headers.index(name)
    key = normalize_header(name)
    if key in t.keys:
        return t.keys.index(key)
    raise IngestError(
        f"the {role} column is not in the file; the columns are {t.headers}",
        column=name,
        source=t.source,
    )


def _timestamp(text: str, fmt: str | None, folds: FoldTracker) -> int:
    t = text.strip()
    if fmt == "unix":
        return int(float(t))
    if fmt == "unix_ms":
        return int(float(t) // 1000)
    if fmt is not None:
        parsed = datetime.strptime(t, fmt)
        if parsed.tzinfo is not None:
            return int(parsed.astimezone(timezone.utc).timestamp())
        return folds.utc(parsed)
    naive, is_utc = parse_datetime(t)
    return utc_seconds(naive) if is_utc else folds.utc(naive)


def parse_mapped(data: bytes | str, cmap: ColumnMap, *, source: str = "") -> list[Series]:
    """Read ``data`` as described by ``cmap``; see :class:`ColumnMap`."""
    spec = QUANTITIES.get(cmap.quantity)
    if spec is None:
        raise ValueError(
            f"unknown quantity {cmap.quantity!r}; known: {', '.join(QUANTITIES)}"
        )
    kind = cmap.kind or spec.kinds[0]
    if kind not in spec.kinds:
        raise ValueError(f"{cmap.quantity} cannot be of kind {kind!r}")
    if cmap.label not in ("start", "end"):
        raise ValueError("label must be 'start' or 'end'")
    if (cmap.time is None) == (cmap.start is None):
        raise ValueError("give either time= or start= and end=")
    if (cmap.start is None) != (cmap.end is None):
        raise ValueError("start= and end= go together")
    if cmap.cumulative and kind != INTERVAL:
        raise ValueError("cumulative readings give intervals; kind must be 'interval'")

    t = read_table(data, source, delimiter=cmap.delimiter, decimal=cmap.decimal)
    c_v = _column(t, cmap.value, "value")
    unit_text = cmap.unit
    if unit_text is None:
        unit = unit_in_header(t.headers[c_v])
        if unit is None:
            raise IngestError(
                "the header does not say the unit; pass unit= (e.g. 'kWh', 'm3', '°C')",
                column=t.headers[c_v],
                source=source,
            )
    else:
        try:
            unit = parse_unit(unit_text)
        except ValueError as exc:
            raise IngestError(str(exc), column=t.headers[c_v], source=source) from None
    if dimension_of(unit) != spec.dimension:
        raise IngestError(
            f"{unit} is a unit of {dimension_of(unit)}, but {cmap.quantity} is "
            f"measured in {spec.dimension}",
            column=t.headers[c_v],
            source=source,
        )
    c_q = _column(t, cmap.quality, "quality") if cmap.quality else None
    tz = zone(cmap.timezone)
    folds = FoldTracker(tz)

    def stamp(r: int, c: int) -> int:
        try:
            return _timestamp(t.rows[r][c], cmap.time_format, folds)
        except ValueError as exc:
            raise t.error(r, c, str(exc)) from None

    if cmap.time is not None:
        c_t = _column(t, cmap.time, "time")
        times = [stamp(r, c_t) for r in range(len(t.rows))]
        time_col = t.headers[c_t]
    else:
        c_s, c_e = _column(t, cmap.start, "start"), _column(t, cmap.end, "end")  # type: ignore[arg-type]
        f_end = FoldTracker(tz)
        times = [stamp(r, c_s) for r in range(len(t.rows))]
        ends = []
        for r in range(len(t.rows)):
            try:
                ends.append(_timestamp(t.rows[r][c_e], cmap.time_format, f_end))
            except ValueError as exc:
                raise t.error(r, c_e, str(exc)) from None
        time_col = t.headers[c_s]

    values = []
    qualities = []
    for r, cells in enumerate(t.rows):
        try:
            values.append(parse_number(cells[c_v], t.decimal))
        except ValueError as exc:
            raise t.error(r, c_v, str(exc)) from None
        if c_q is not None:
            q = QUALITY.get(cells[c_q].strip().lower(), None)
            if q is None and cells[c_q].strip():
                raise t.error(r, c_q, f"{cells[c_q]!r} is neither real nor estimated")
            qualities.append(REAL if q is None else q)
        else:
            qualities.append(REAL)

    rows: list[Row] = []
    order = sorted(range(len(t.rows)), key=lambda i: times[i])
    if cmap.cumulative:
        for a, b in zip(order, order[1:], strict=False):
            delta = values[b] - values[a]
            if delta < 0:
                raise t.error(
                    b,
                    c_v,
                    f"the meter reading went down from {values[a]:g} to {values[b]:g}",
                )
            rows.append(
                Row(
                    times[a],
                    times[b],
                    float(to_si(delta, unit)),
                    qualities[b],
                    t.lines[b],
                )
            )
    elif cmap.start is not None:
        for i in order:
            rows.append(
                Row(
                    times[i],
                    ends[i],
                    float(to_si(values[i], unit)),
                    qualities[i],
                    t.lines[i],
                )
            )
    elif kind == INSTANT:
        for i in order:
            rows.append(
                Row(
                    times[i],
                    times[i],
                    float(to_si(values[i], unit)),
                    qualities[i],
                    t.lines[i],
                )
            )
    else:
        step = cmap.interval
        if step is None:
            diffs = Counter(
                times[b] - times[a]
                for a, b in zip(order, order[1:], strict=False)
                if times[b] > times[a]
            )
            if not diffs:
                raise IngestError(
                    "cannot infer the interval from fewer than two rows; pass interval=",
                    column=time_col,
                    source=source,
                )
            step = diffs.most_common(1)[0][0]
        for i in order:
            s = times[i] if cmap.label == "start" else times[i] - step
            rows.append(
                Row(s, s + step, float(to_si(values[i], unit)), qualities[i], t.lines[i])
            )
    if not rows:
        raise IngestError("no readings to build a series from", source=source)
    return [
        series_from_rows(
            rows,
            quantity=cmap.quantity,
            channel=cmap.channel,
            kind=kind,
            source=source,
            value_column=t.headers[c_v],
            time_column=time_col,
        )
    ]


@dataclass(frozen=True)
class ColumnGuess:
    """What a column of an unknown CSV looks like."""

    name: str
    role: str  # "time", "number" or "text"
    unit: str | None
    example: str


@dataclass(frozen=True)
class CsvDescription:
    """The layout of an unknown CSV, for an import screen to show."""

    delimiter: str
    decimal: str
    columns: list[ColumnGuess]
    n_rows: int


def describe_csv(
    data: bytes | str, *, source: str = "", sample: int = 50
) -> CsvDescription:
    """Guess the role and unit of each column of an unknown CSV.

    Nothing here is trusted: it only pre-fills the :class:`ColumnMap` the
    user confirms.
    """
    t = read_table(data, source)
    rows = t.rows[:sample]
    guesses = []
    for c, h in enumerate(t.headers):
        cells = [r[c] for r in rows if r[c].strip()]
        role = "text"
        if cells:
            if all(_is_time(x) for x in cells):
                role = "time"
            elif all(_is_number(x, t.decimal) for x in cells):
                role = "number"
        guesses.append(ColumnGuess(h, role, unit_in_header(h), cells[0] if cells else ""))
    return CsvDescription(t.delimiter, t.decimal, guesses, len(t.rows))


def _is_time(text: str) -> bool:
    try:
        parse_datetime(text)
        return True
    except ValueError:
        return False


def _is_number(text: str, decimal: str) -> bool:
    try:
        parse_number(text, decimal)
        return True
    except ValueError:
        return False
