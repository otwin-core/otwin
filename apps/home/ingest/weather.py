"""Hourly outside weather from Open-Meteo (ARCHITECTURE.md, "Ingest").

Two shapes are accepted: the API's JSON and the CSV the website offers for
download. Both carry hourly arrays with a unit per variable.

* ``temperature_2m`` (°C or °F) is instantaneous at each timestamp →
  ``outdoor_temperature``, kind ``instant``.
* ``shortwave_radiation`` (W/m²) is the mean over the *preceding* hour →
  ``solar_irradiance``, kind ``mean`` over ``[t − 1 h, t)``.

Other variables are ignored, and missing values (``null`` or an empty cell)
are gaps, not zeros.

**Time stamps.** Open-Meteo applies the UTC offset in force *at request time*
to the whole response and ignores DST changes inside the range. ISO local
times are therefore wrong by an hour on one side of every change. Unix times
(``timeformat=unixtime``) are always right. ISO times are accepted only when
the response is in UTC/GMT. Anything else is refused with the fix spelled out.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from ._table import decode, parse_number, read_table
from .errors import IngestError
from .schema import INSTANT, MEAN, REAL, Row, Series, series_from_rows
from .timeutil import parse_datetime, utc_seconds
from .units import parse_unit, to_si, unit_in_header

__all__ = ["parse_open_meteo_json", "parse_open_meteo_csv", "VARIABLES"]

#: Open-Meteo variable -> (quantity, kind, seconds the value looks back)
VARIABLES: dict[str, tuple[str, str, int]] = {
    "temperature_2m": ("outdoor_temperature", INSTANT, 0),
    "shortwave_radiation": ("solar_irradiance", MEAN, 3600),
}

_FIX = (
    "local ISO times from Open-Meteo are off by one hour across a DST change; "
    "download again with timeformat=unixtime (or timezone=GMT)"
)


def _times(
    raw: Sequence[object],
    utc_offset: int,
    tz_name: str,
    column: str,
    src: str,
    line_of,
    line_label: str,
) -> list[int]:
    out = []
    for i, v in enumerate(raw):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(int(v))
            continue
        text = str(v).strip()
        if text.isdigit():
            out.append(int(text))
            continue
        try:
            naive, is_utc = parse_datetime(text)
        except ValueError as exc:
            raise IngestError(
                str(exc),
                column=column,
                line=line_of(i),
                line_label=line_label,
                source=src,
            ) from None
        if not is_utc and (utc_offset != 0 or tz_name.upper() not in ("GMT", "UTC")):
            raise IngestError(
                _FIX, column=column, line=line_of(i), line_label=line_label, source=src
            )
        out.append(utc_seconds(naive))
    return out


def _series(
    channel: str,
    times: list[int],
    columns: dict[str, tuple[str, list[object], str]],  # var -> (unit text, values, col)
    src: str,
    time_col: str,
    line_of,
    line_label: str,
    decimal: str = ".",
) -> list[Series]:
    out = []
    for var, (unit_text, values, col) in columns.items():
        quantity, kind, lookback = VARIABLES[var]
        try:
            unit = parse_unit(unit_text)
        except ValueError as exc:
            raise IngestError(str(exc), column=col, source=src) from None
        if lookback:
            steps = {b - a for a, b in zip(times, times[1:], strict=False)}
            if steps and steps != {lookback}:
                raise IngestError(
                    f"{var} is a mean over the preceding hour, so the data must be "
                    "hourly",
                    column=time_col,
                    source=src,
                )
        rows = []
        for i, (ts, v) in enumerate(zip(times, values, strict=True)):
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            if isinstance(v, str):
                try:
                    num = parse_number(v, decimal)
                except ValueError as exc:
                    raise IngestError(
                        str(exc),
                        column=col,
                        line=line_of(i),
                        line_label=line_label,
                        source=src,
                    ) from None
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                num = float(v)
            else:
                raise IngestError(
                    f"{v!r} is not a number",
                    column=col,
                    line=line_of(i),
                    line_label=line_label,
                    source=src,
                )
            rows.append(Row(ts - lookback, ts, float(to_si(num, unit)), REAL, line_of(i)))
        if rows:
            out.append(
                series_from_rows(
                    rows,
                    quantity=quantity,
                    channel=channel,
                    kind=kind,
                    source=src,
                    value_column=col,
                    time_column=time_col,
                    line_label=line_label,
                )
            )
    if not out:
        raise IngestError(
            f"no usable variable; expected one of {list(VARIABLES)}", source=src
        )
    return out


def _channel(lat: object, lon: object) -> str:
    return f"{lat},{lon}"


def parse_open_meteo_json(data: bytes | str, *, source: str = "") -> list[Series]:
    """Open-Meteo forecast or archive API response (JSON)."""
    try:
        obj = json.loads(data)
    except ValueError as exc:
        raise IngestError(f"not JSON: {exc}", source=source) from None
    if not isinstance(obj, dict) or not isinstance(obj.get("hourly"), dict):
        raise IngestError(
            "no 'hourly' block; request hourly=temperature_2m",
            column="hourly",
            source=source,
        )
    hourly = obj["hourly"]
    units = obj.get("hourly_units") or {}
    if "time" not in hourly:
        raise IngestError("missing the time array", column="hourly.time", source=source)
    n = len(hourly["time"])
    columns = {}
    for var in VARIABLES:
        if var not in hourly:
            continue
        if var not in units:
            raise IngestError(
                f"no unit for {var}", column=f"hourly_units.{var}", source=source
            )
        values = hourly[var]
        if len(values) != n:
            raise IngestError(
                f"{len(values)} values for {n} times",
                column=f"hourly.{var}",
                source=source,
            )
        columns[var] = (str(units[var]), list(values), f"hourly.{var}")
    if not columns:
        raise IngestError(
            f"no usable variable; expected one of {list(VARIABLES)}",
            column="hourly",
            source=source,
        )

    def line_of(i: int) -> int:
        return i + 1

    times = _times(
        hourly["time"],
        int(obj.get("utc_offset_seconds", 0)),
        str(obj.get("timezone", "GMT")),
        "hourly.time",
        source,
        line_of,
        "record",
    )
    return _series(
        _channel(obj.get("latitude"), obj.get("longitude")),
        times,
        columns,
        source,
        "hourly.time",
        line_of,
        "record",
    )


def parse_open_meteo_csv(data: bytes | str, *, source: str = "") -> list[Series]:
    """Open-Meteo CSV download: a location block, a blank line, then hourly data.

    The data header names each variable with its unit, for example
    ``temperature_2m (°C)``.
    """
    text = decode(data)
    lines = text.splitlines()
    blank = next((i for i, ln in enumerate(lines) if not ln.strip()), None)
    if blank is None or blank < 2:
        raise IngestError(
            "expected a location block (latitude, longitude, ...), a blank line and "
            "the hourly data",
            source=source,
        )
    meta = read_table("\n".join(lines[:blank]), source, delimiter=",")
    if not meta.rows:
        raise IngestError("the location block has no values", source=source)
    m = dict(zip(meta.keys, meta.rows[0], strict=True))
    offset_text = m.get("utc_offset_seconds", "0").strip() or "0"
    if not offset_text.lstrip("+-").isdigit():
        raise IngestError(
            f"{offset_text!r} is not a number of seconds",
            column="utc_offset_seconds",
            line=2,
            source=source,
        )
    body_start = blank + 1
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1
    body = "\n".join(lines[body_start:])
    t = read_table(body, source, delimiter=",", decimal=".")
    t.lines = [n + body_start for n in t.lines]
    c_time = t.require("time", what="time")
    columns = {}
    for c, header in enumerate(t.headers):
        var = header.split("(")[0].strip()
        if var not in VARIABLES:
            continue
        unit = unit_in_header(header)
        if unit is None:
            raise IngestError(
                "the header does not give a unit, e.g. 'temperature_2m (°C)'",
                column=header,
                source=source,
            )
        columns[var] = (unit, [row[c] for row in t.rows], header)
    if not columns:
        raise IngestError(
            f"no usable variable; expected one of {list(VARIABLES)}; the columns are "
            f"{t.headers}",
            column=t.headers[-1],
            source=source,
        )

    def line_of(i: int) -> int:
        return t.lines[i]

    times = _times(
        [row[c_time] for row in t.rows],
        int(offset_text),
        m.get("timezone", "GMT").strip(),
        t.headers[c_time],
        source,
        line_of,
        "line",
    )
    return _series(
        _channel(m.get("latitude", "").strip(), m.get("longitude", "").strip()),
        times,
        columns,
        source,
        t.headers[c_time],
        line_of,
        "line",
    )
