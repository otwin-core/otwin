"""Hourly smart-meter electricity: Datadis and the distributor portals.

Three layouts are accepted (ARCHITECTURE.md, "Ingest"):

* **CNMC family** (CSV): one row per hour with ``CUPS``, a date column
  (``Fecha``/``Data``), an hour number (``Hora``) and an energy column. The
  energy column is ``Consumo_kWh`` (CNMC, most portals), ``Consumo`` (UFD) or
  ``AE_kWh`` (e-distribución, with optional ``AS_KWh`` export and
  ``AE_AUTOCONS_kWh`` self-consumption). The method column is
  ``Metodo_obtencion``, ``REAL/ESTIMADO`` or ``LECTURA REAL/ESTIMADA``.
* **Datadis JSON** (API or web download): records with ``cups``, ``date``,
  ``time``, ``consumptionKWh``, ``obtainMethod`` and optionally
  ``surplusEnergyKWh`` and ``selfConsumptionEnergyKWh``.
* **i-DE** (CSV): ``CUPS;FECHA-HORA;INV / VER;CONSUMO Wh;GENERACION Wh;``,
  where the energy is in Wh and the time is the local clock time at which the
  hour *ends*. ``INV / VER`` is 1 in summer time and 0 in winter time, and is
  what tells the two hours ending at 02:00 on the October change day apart.

**Hour numbers.** CNMC-family and Datadis files number the hours of each
local day. Sources disagree on whether the numbering starts at 1 (the hour
*ending* at that time, the CNMC convention) or at 0 (the hour *starting*
then). The parser reads the convention from the data: a 0 means 0-based and
a 24 or 25 means 1-based. If neither appears, it refuses and asks for
``hour_convention``. Within a day the numbers count elapsed hours from local
midnight, so a 23-hour March day and a 25-hour October day map exactly onto
UTC. A 0-based file that labels by wall-clock time instead (skipping 2 in
March, repeating 2 in October) is recognised as such.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from ._table import Table, normalize_header, read_table
from .errors import IngestError
from .schema import ESTIMATED, INTERVAL, REAL, Row, Series, series_from_rows
from .timeutil import (
    DEFAULT_TZ,
    FoldTracker,
    day_hours,
    midnight_utc,
    parse_date,
    parse_datetime,
    utc_seconds,
    zone,
)
from .units import dimension_of, to_si, unit_in_header

__all__ = ["parse_distributor_csv", "parse_datadis_json", "parse_ide_csv", "QUALITY"]

#: How each source spells a real or an estimated reading.
QUALITY: dict[str, int] = {
    "r": REAL,
    "real": REAL,
    "e": ESTIMATED,
    "estimada": ESTIMATED,
    "estimado": ESTIMATED,
    "estimated": ESTIMATED,
    "s": ESTIMATED,  # "sustituida": a substituted (estimated) reading
}

_CUPS = ("cups",)
_DATE = ("fecha", "data", "date")
_HOUR = ("hora", "time", "hour")
_IMPORT = (
    "consumo_kwh",
    "ae_kwh",
    "consumo_wh",
    "ae_wh",
    "consumptionkwh",
    "consumo",
)
_EXPORT = ("as_kwh", "as_wh", "surplusenergykwh", "energia_vertida_kwh")
_SELF = ("ae_autocons_kwh", "selfconsumptionenergykwh")
_METHOD = (
    "metodo_obtencion",
    "real_estimado",
    "lectura_real_estimada",
    "obtainmethod",
    "metodo",
)


def _quality(text: str) -> int | None:
    key = text.strip().lower()
    if not key:
        return REAL
    return QUALITY.get(key)


def _energy_unit(header: str) -> str:
    """kWh unless the header says otherwise. UFD's bare ``Consumo`` is kWh."""
    unit = unit_in_header(header) or "kWh"
    if dimension_of(unit) != "energy":
        raise ValueError(f"the header declares {unit}, which is not an energy unit")
    return unit


def _hour_label(text: str) -> int:
    t = text.strip()
    if ":" in t:
        hh, _, mm = t.partition(":")
        if not hh.isdigit() or mm[:2] != "00" or mm[2:].strip(":0"):
            raise ValueError(f"{text!r} is not a whole hour")
        return int(hh)
    if not t.isdigit():
        raise ValueError(f"{text!r} is not an hour number")
    return int(t)


@dataclass
class _Hourly:
    """Rows of a CNMC-family or Datadis file, before the hour convention is known."""

    cups: str
    day: date
    label: int
    line: int
    values: dict[str, tuple[float, str]]  # quantity -> (SI value, column)
    quality: int


def _convention(entries: Sequence[_Hourly], given: str | None, hour_col: str, src: str):
    if given is not None:
        if given not in ("start", "end"):
            raise ValueError("hour_convention must be 'start' or 'end'")
        return given
    labels = {e.label for e in entries}
    if 0 in labels and labels & {24, 25}:
        raise IngestError(
            "hour numbers include both 0 and 24, so they are neither 0-based nor "
            "1-based; pass hour_convention='start' or 'end'",
            column=hour_col,
            source=src,
        )
    if 0 in labels:
        return "start"
    if labels & {24, 25}:
        return "end"
    raise IngestError(
        "cannot tell whether hour 1 is the first or the second hour of the day "
        "(no hour 0 or 24 in the file); pass hour_convention='start' if hours "
        "are numbered from 0, or 'end' if from 1",
        column=hour_col,
        source=src,
    )


def _hours_to_utc(
    entries: list[_Hourly],
    convention: str,
    tz,
    hour_col: str,
    src: str,
    line_label: str,
) -> list[tuple[_Hourly, int]]:
    base = 0 if convention == "start" else 1
    by_day: dict[tuple[str, date], list[_Hourly]] = defaultdict(list)
    for e in entries:
        by_day[(e.cups, e.day)].append(e)
    out: list[tuple[_Hourly, int]] = []
    for (_, day), group in by_day.items():
        n = day_hours(day, tz)
        labels = [e.label for e in group]
        midnight = midnight_utc(day, tz)
        elapsed_ok = len(set(labels)) == len(labels) and all(
            base <= h < base + n for h in labels
        )
        if elapsed_ok:
            out.extend((e, midnight + (e.label - base) * 3600) for e in group)
            continue
        if convention == "start" and n != 24 and all(0 <= h <= 23 for h in labels):
            # 0-based wall-clock labels: 2 is missing in March, repeated in October.
            folds = FoldTracker(tz)
            for e in group:
                naive = datetime(day.year, day.month, day.day, e.label)
                try:
                    out.append((e, folds.utc(naive)))
                except ValueError as exc:
                    raise IngestError(
                        str(exc),
                        column=hour_col,
                        line=e.line,
                        line_label=line_label,
                        source=src,
                    ) from None
            continue
        bad = next(
            (
                e
                for e in group
                if not base <= e.label < base + n or labels.count(e.label) > 1
            ),
            group[0],
        )
        why = (
            "appears twice"
            if labels.count(bad.label) > 1
            else f"is outside {base}..{base + n - 1}"
        )
        raise IngestError(
            f"hour {bad.label} on {day:%d/%m/%Y} {why}; that day has {n} hours "
            f"in {tz.key}",
            column=hour_col,
            line=bad.line,
            line_label=line_label,
            source=src,
        )
    return out


def _build(
    pairs: list[tuple[_Hourly, int]],
    quantity_columns: dict[str, str],
    time_col: str,
    src: str,
    line_label: str,
) -> list[Series]:
    rows: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for e, start in pairs:
        for quantity, (value, _) in e.values.items():
            rows[(e.cups, quantity)].append(
                Row(start, start + 3600, value, e.quality, e.line)
            )
    out = []
    for (cups, quantity), rs in sorted(rows.items()):
        out.append(
            series_from_rows(
                rs,
                quantity=quantity,
                channel=cups,
                kind=INTERVAL,
                source=src,
                value_column=quantity_columns[quantity],
                time_column=time_col,
                line_label=line_label,
            )
        )
    return out


def _from_table(
    t: Table,
    *,
    tz_name: str,
    hour_convention: str | None,
    line_label: str = "line",
) -> list[Series]:
    tz = zone(tz_name)
    c_cups = t.require(*_CUPS, what="CUPS")
    c_date = t.require(*_DATE, what="date")
    c_hour = t.require(*_HOUR, what="hour")
    c_imp = t.require(*_IMPORT, what="energy")
    c_exp = t.find(*_EXPORT)
    c_self = t.find(*_SELF)
    c_meth = t.find(*_METHOD)
    energy_cols: dict[str, tuple[int, str]] = {}
    for quantity, col in (
        ("electricity_import", c_imp),
        ("electricity_export", c_exp),
        ("electricity_self_consumption", c_self),
    ):
        if col is None:
            continue
        try:
            energy_cols[quantity] = (col, _energy_unit(t.headers[col]))
        except ValueError as exc:
            raise IngestError(str(exc), column=t.headers[col], source=t.source) from None
    entries: list[_Hourly] = []
    for r, cells in enumerate(t.rows):
        try:
            day = parse_date(cells[c_date])
        except ValueError as exc:
            raise t.error(r, c_date, str(exc)) from None
        try:
            label = _hour_label(cells[c_hour])
        except ValueError as exc:
            raise t.error(r, c_hour, str(exc)) from None
        values: dict[str, tuple[float, str]] = {}
        for quantity, (col, unit) in energy_cols.items():
            if quantity != "electricity_import" and not cells[col].strip():
                continue  # e-distribución leaves AE_AUTOCONS empty when there is none
            values[quantity] = (float(to_si(t.number(r, col), unit)), t.headers[col])
        quality = REAL
        if c_meth is not None:
            q = _quality(cells[c_meth])
            if q is None:
                raise t.error(
                    r,
                    c_meth,
                    f"{cells[c_meth]!r} is neither a real (R) nor an "
                    "estimated (E) reading",
                )
            quality = q
        cups = cells[c_cups].strip()
        if not cups:
            raise t.error(r, c_cups, "the CUPS is empty")
        entries.append(_Hourly(cups, day, label, t.lines[r], values, quality))
    if not entries:
        raise IngestError("the file has a header but no readings", source=t.source)
    hour_col = t.headers[c_hour]
    conv = _convention(entries, hour_convention, hour_col, t.source)
    pairs = _hours_to_utc(entries, conv, tz, hour_col, t.source, line_label)
    columns = {q: t.headers[c] for q, (c, _) in energy_cols.items()}
    return _build(pairs, columns, hour_col, t.source, line_label)


def parse_distributor_csv(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
    hour_convention: str | None = None,
) -> list[Series]:
    """CNMC-family hourly CSV (CNMC, UFD, e-distribución, most portals).

    Returns one :class:`Series` per CUPS and quantity: always
    ``electricity_import``, plus ``electricity_export`` and
    ``electricity_self_consumption`` when the file has those columns.
    """
    return _from_table(
        read_table(data, source), tz_name=timezone, hour_convention=hour_convention
    )


def _datadis_records(obj) -> list:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for key in ("timeCurve", "response", "data"):
            if key in obj:
                return _datadis_records(obj[key])
    raise ValueError("expected a list of Datadis consumption records")


def parse_datadis_json(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
    hour_convention: str | None = None,
) -> list[Series]:
    """Datadis consumption JSON, from the private API or the web download.

    Errors name the record number (1-based) and the JSON field.
    """
    try:
        obj = json.loads(data)
        records = _datadis_records(obj)
    except (ValueError, TypeError) as exc:
        raise IngestError(f"not Datadis JSON: {exc}", source=source) from None
    if not records:
        raise IngestError("the file has no consumption records", source=source)
    fields: list[str] = []
    for rec in records:
        if not isinstance(rec, dict):
            raise IngestError("every record must be a JSON object", source=source)
        fields.extend(k for k in rec if k not in fields)
    keys = [normalize_header(f) for f in fields]
    rows = []
    for rec in records:
        row = []
        for f in fields:
            v = rec.get(f)
            row.append(
                ""
                if v is None
                else (
                    repr(float(v))
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                    else str(v)
                )
            )
        rows.append(row)
    t = Table(
        headers=fields,
        keys=keys,
        rows=rows,
        lines=list(range(1, len(records) + 1)),
        delimiter=",",
        decimal=".",
        source=source,
    )
    try:
        return _from_table(
            t, tz_name=timezone, hour_convention=hour_convention, line_label="record"
        )
    except IngestError as exc:
        if exc.line is not None:
            exc.line_label = "record"
        raise


def parse_ide_csv(
    data: bytes | str,
    *,
    source: str = "",
    timezone: str = DEFAULT_TZ,
) -> list[Series]:
    """i-DE (Iberdrola distribution) hourly CSV; see the module docstring.

    The time labels the *end* of each hour. ``GENERACION`` is read as energy
    fed to the grid (``electricity_export``).
    """
    tz = zone(timezone)
    t = read_table(data, source)
    c_cups = t.require("cups", what="CUPS")
    c_time = t.require("fecha_hora", what="date and time")
    c_flag = t.require("inv_ver", what="winter/summer flag")
    c_imp = t.require("consumo_wh", "consumo_kwh", "consumo", what="consumption")
    c_gen = t.find("generacion_wh", "generacion_kwh", "generacion")
    cols = {"electricity_import": c_imp}
    if c_gen is not None:
        cols["electricity_export"] = c_gen
    units = {}
    for q, c in cols.items():
        unit = unit_in_header(t.headers[c])
        if unit is None:
            raise IngestError(
                "the header does not say whether the values are Wh or kWh",
                column=t.headers[c],
                source=source,
            )
        if dimension_of(unit) != "energy":
            raise IngestError(
                f"the header declares {unit}, which is not an energy unit",
                column=t.headers[c],
                source=source,
            )
        units[q] = unit
    rows: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for r, cells in enumerate(t.rows):
        try:
            naive, is_utc = parse_datetime(cells[c_time])
            if is_utc:
                raise ValueError("expected local time without an offset")
        except ValueError as exc:
            raise t.error(r, c_time, str(exc)) from None
        flag = cells[c_flag].strip()
        if flag not in ("0", "1"):
            raise t.error(r, c_flag, f"{flag!r} must be 1 (summer) or 0 (winter)")
        summer = flag == "1"
        # The flag fixes the UTC offset of the label: standard time, plus one
        # hour in summer. That decodes the October change day whichever way
        # the hour ending at 01:00 UTC is written ("03:00" summer or "02:00"
        # winter), with no guessing about repeated wall-clock times.
        std = _standard_offset(naive, tz)
        end = utc_seconds(naive) - std - (3600 if summer else 0)
        offsets = {_offset_at(end, tz), _offset_at(end - 1, tz)}
        if std + (3600 if summer else 0) not in offsets:
            in_dst = _offset_at(end - 1, tz) != std
            raise t.error(
                r,
                c_flag,
                f"flag {flag} disagrees with {cells[c_time].strip()}, which is "
                f"{'summer' if in_dst else 'winter'} time in {tz.key}",
            )
        cups = cells[c_cups].strip()
        for q, c in cols.items():
            if q != "electricity_import" and not cells[c].strip():
                continue
            v = float(to_si(t.number(r, c), units[q]))
            rows[(cups, q)].append(Row(end - 3600, end, v, REAL, t.lines[r]))
    if not rows:
        raise IngestError("the file has a header but no readings", source=source)
    return [
        series_from_rows(
            rs,
            quantity=q,
            channel=cups,
            kind=INTERVAL,
            source=source,
            value_column=t.headers[cols[q]],
            time_column=t.headers[c_time],
        )
        for (cups, q), rs in sorted(rows.items())
    ]


def _offset_at(ts: int, tz) -> int:
    """UTC offset in seconds of ``tz`` at UTC instant ``ts``."""
    off = datetime.fromtimestamp(ts, tz).utcoffset()
    assert off is not None
    return int(off.total_seconds())


def _standard_offset(naive: datetime, tz) -> int:
    """The zone's standard (winter) UTC offset around ``naive``, in seconds."""
    aware = naive.replace(tzinfo=tz)
    off, dst = aware.utcoffset(), aware.dst()
    assert off is not None and dst is not None
    return int((off - dst).total_seconds())
