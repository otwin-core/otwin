"""Smart-plug and sub-meter energy exports: Shelly (local CSV) and Tapo (app workbook).

**Shelly** Gen2+ energy meters store per-interval records and serve them as
CSV from the local web server (ARCHITECTURE.md)::

    http://<ip>/em1data/<id>/data.csv?add_keys=true   (single phase: Pro EM, EM Gen3)
    http://<ip>/emdata/<id>/data.csv?add_keys=true    (three phase: Pro 3EM)

With ``add_keys=true`` the first line names the columns. The parser needs
``timestamp`` (UTC unix seconds at the start of each record) and at least
one active-energy column: ``total_act_energy`` (single phase) or
``a_/b_/c_total_act_energy`` (three phase, summed). Energies are in Wh per
record. Returned (exported) energy columns, ``*_total_act_ret_energy``, are
ignored. The record length is the spacing between timestamps, so a device
offline for ten minutes leaves a ten-minute gap rather than one long
interval.

**Tapo** P110/P115 plugs export an Excel workbook from the app (ARCHITECTURE.md): hourly energy for the last 7 days, daily for the last 3 months,
monthly for the last 12 months, and a sheet of instantaneous power. Sheet
names and headers vary with app version and language, so each sheet is
recognised by its contents rather than its name. That means a header row
with a time column and a column whose header declares ``kWh``/``Wh``
(energy) or ``W`` (power). Each sheet becomes its own :class:`Series`,
because the same days appear in several sheets at different resolutions;
use :func:`ingest.merge` to join overlapping exports of the *same* sheet.
Labels are local time at the *start* of each hour, day or month. The
column names in the fixtures are a best reading of public descriptions,
pending a real export (ARCHITECTURE.md).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from ._table import parse_number, read_table
from ._xlsx import Cell, XlsxError, read_xlsx
from .errors import IngestError
from .schema import INSTANT, INTERVAL, REAL, Row, Series, series_from_rows
from .timeutil import (
    DEFAULT_TZ,
    FoldTracker,
    midnight_utc,
    parse_datetime,
    parse_year_month,
    zone,
)
from .units import dimension_of, to_si, unit_in_header

__all__ = ["parse_shelly_csv", "parse_tapo_xlsx"]


def parse_shelly_csv(
    data: bytes | str,
    *,
    source: str = "",
    channel: str = "shelly",
    quantity: str = "plug_energy",
    period: int | None = None,
) -> list[Series]:
    """Shelly EM1Data/EMData CSV (with ``add_keys=true``) to one energy :class:`Series`.

    Args:
        channel: the name the household gives this plug or circuit.
        quantity: ``plug_energy`` by default. Use ``electricity_import`` for
            a meter on the mains.
        period: record length in seconds. If omitted it is the most common
            spacing between timestamps, which needs at least two records.
    """
    t = read_table(data, source)
    c_ts = t.require("timestamp", "ts", what="timestamp")
    energy = [
        i
        for i, k in enumerate(t.keys)
        if k.endswith("total_act_energy") and "ret" not in k
    ]
    if not energy:
        raise IngestError(
            "no active-energy column (total_act_energy or a_total_act_energy, ...); "
            f"the columns are {t.headers}. Download with add_keys=true.",
            column="total_act_energy",
            source=source,
        )
    stamps: list[int] = []
    for r, cells in enumerate(t.rows):
        txt = cells[c_ts].strip()
        if not txt.isdigit():
            raise t.error(r, c_ts, f"{txt!r} is not a unix timestamp in seconds")
        stamps.append(int(txt))
    if period is None:
        diffs = Counter(
            b - a
            for a, b in zip(sorted(stamps), sorted(stamps)[1:], strict=False)
            if b > a
        )
        if not diffs:
            raise IngestError(
                "cannot infer the record length from fewer than two records; "
                "pass period= in seconds",
                column=t.headers[c_ts],
                source=source,
            )
        period = diffs.most_common(1)[0][0]
    rows = []
    for r in range(len(t.rows)):
        wh = sum(t.number(r, c) for c in energy)
        rows.append(
            Row(stamps[r], stamps[r] + period, float(to_si(wh, "Wh")), REAL, t.lines[r])
        )
    return [
        series_from_rows(
            rows,
            quantity=quantity,
            channel=channel,
            kind=INTERVAL,
            source=source,
            value_column=t.headers[energy[0]],
            time_column=t.headers[c_ts],
        )
    ]


# ---------------------------------------------------------------- Tapo

_EXCEL_EPOCH = datetime(1899, 12, 30)


def _label(cell: Cell) -> tuple[str, datetime]:
    """``("month" | "date" | "time", naive local datetime)`` for a Tapo time cell."""
    if isinstance(cell, float):
        naive = _EXCEL_EPOCH + timedelta(seconds=round(cell * 86400))
        has_time = naive.hour or naive.minute or naive.second or cell % 1
        return ("time" if has_time else "date"), naive
    text = (cell or "").strip()
    try:
        y, m = parse_year_month(text)
        return "month", datetime(y, m, 1)
    except ValueError:
        pass
    naive, is_utc = parse_datetime(text)
    if is_utc:
        raise ValueError(f"{text!r}: expected local time without an offset")
    has_time = any(ch == ":" for ch in text)
    return ("time" if has_time else "date"), naive


def _find_header(rows: list[list[Cell]]) -> tuple[int, int, int, str, str] | None:
    """(header row, time column, value column, unit, kind) of a Tapo sheet."""
    for r, row in enumerate(rows[:15]):
        texts = [c if isinstance(c, str) else "" for c in row]
        for v, h in enumerate(texts):
            unit = unit_in_header(h) if h else None
            if unit is None:
                continue
            dim = dimension_of(unit)
            if dim not in ("energy", "power"):
                continue
            others = [i for i, x in enumerate(texts) if x.strip() and i != v]
            if not others:
                continue
            return r, others[0], v, unit, dim
    return None


def _next_month(d: datetime) -> datetime:
    return datetime(d.year + (d.month == 12), d.month % 12 + 1, 1)


def parse_tapo_xlsx(
    data: bytes,
    *,
    source: str = "",
    channel: str = "tapo",
    timezone: str = DEFAULT_TZ,
) -> list[Series]:
    """A Tapo energy workbook to one :class:`Series` per recognised sheet.

    Energy sheets become ``plug_energy`` intervals of an hour, a day or a
    month, depending on how the sheet labels its rows. A power sheet becomes
    ``plug_power`` instants. Sheets that hold neither are skipped, but a
    workbook with no recognisable sheet at all is an error.
    """
    tz = zone(timezone)
    try:
        sheets = read_xlsx(data)
    except XlsxError as exc:
        raise IngestError(str(exc), source=source) from None
    out: list[Series] = []
    for name, rows in sheets.items():
        found = _find_header(rows)
        if found is None:
            continue
        h, c_t, c_v, unit, dim = found
        headers = rows[h]
        t_col, v_col = str(headers[c_t]), str(headers[c_v])
        sheet_src = f"{source}#{name}" if source else f"#{name}"
        labels: list[tuple[str, datetime, int, float]] = []
        for r in range(h + 1, len(rows)):
            row = rows[r]
            tcell = row[c_t] if c_t < len(row) else None
            vcell = row[c_v] if c_v < len(row) else None
            if tcell in (None, "") and vcell in (None, ""):
                continue
            line = r + 1  # spreadsheet row number
            try:
                grain, naive = _label(tcell)
            except ValueError as exc:
                raise IngestError(
                    str(exc), column=t_col, line=line, line_label="row", source=sheet_src
                ) from None
            if isinstance(vcell, float):
                value = vcell
            else:
                try:
                    value = parse_number(
                        str(vcell or ""), "," if "," in str(vcell) else "."
                    )
                except ValueError as exc:
                    raise IngestError(
                        str(exc),
                        column=v_col,
                        line=line,
                        line_label="row",
                        source=sheet_src,
                    ) from None
            labels.append((grain, naive, line, value))
        if not labels:
            continue
        grains = {g for g, *_ in labels}
        if len(grains) > 1:
            g0 = labels[0][0]
            odd = next(x for x in labels if x[0] != g0)
            raise IngestError(
                f"this row is labelled by {odd[0]} but earlier rows by {g0}",
                column=t_col,
                line=odd[2],
                line_label="row",
                source=sheet_src,
            )
        grain = labels[0][0]
        folds = FoldTracker(tz)
        built: list[Row] = []
        for _, naive, line, value in labels:
            try:
                if grain == "month":
                    start = midnight_utc(naive.date(), tz)
                    end = midnight_utc(_next_month(naive).date(), tz)
                elif grain == "date":
                    start = midnight_utc(naive.date(), tz)
                    end = midnight_utc(naive.date() + timedelta(days=1), tz)
                else:
                    start = folds.utc(naive)
                    end = start if dim == "power" else start + 3600
            except ValueError as exc:
                raise IngestError(
                    str(exc), column=t_col, line=line, line_label="row", source=sheet_src
                ) from None
            built.append(Row(start, end, float(to_si(value, unit)), REAL, line))
        if dim == "power":
            if grain != "time":
                raise IngestError(
                    "a power sheet must be labelled with times of day",
                    column=t_col,
                    source=sheet_src,
                )
            quantity, kind = "plug_power", INSTANT
        else:
            quantity, kind = "plug_energy", INTERVAL
        out.append(
            series_from_rows(
                built,
                quantity=quantity,
                channel=channel,
                kind=kind,
                source=sheet_src,
                value_column=v_col,
                time_column=t_col,
                line_label="row",
            )
        )
    if not out:
        raise IngestError(
            "no sheet has a time column next to an energy (kWh) or power (W) column",
            source=source,
        )
    return out
