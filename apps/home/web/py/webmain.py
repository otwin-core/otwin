"""What the browser calls: the wizard's session, over plain JSON.

This module runs inside Pyodide, unpacked to ``/app`` next to ``otwin`` and
the Otwin Home packages, and is the only surface ``runtime.js`` talks to.
The page calls :func:`dispatch` with a function name, keyword arguments and,
for files, the raw bytes; everything comes back as JSON-sized dicts with
plain sentences ready to show. Files are read here, in the browser's own
memory, and kept in :data:`SESSION`; nothing is sent anywhere.

The wizard's three steps map to:

1. :func:`questions`, :func:`assumptions` — the home, by selectors only;
2. :func:`read_file`, :func:`map_file`, :func:`add_bill`, :func:`remove_file`,
   :func:`data_status`, :func:`load_samples`, :func:`demo_home` — the data,
   by drag and drop, with the column mapper for CSVs no parser knows, a form
   for bills typed in by hand, and the bills a photo or a PDF was read into
   (:func:`read_invoice`);
3. :func:`calibrate_home` — the one-click fit and its plain-language report,
   with the gas and water bills set against the twin.

**Gas bills** carry the energy the bill charges (m³ × Fc × PCS, the
conversion printed on it, checked by :mod:`ingest.bills`). When the heating
runs on gas, the bills inside the record are fitted together with the hourly
electricity, and they are what measures how fast the home loses heat. When
only the hot water or the hob runs on gas, the bill is compared with the
twin's typical use instead. **Water bills** are compared with what a
household of that size typically uses.
"""

from __future__ import annotations

import inspect
import json
import re
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from texts import MONTHS, num, t
from texts import TEXTS as _TEXT_KEYS

import ingest
from calibration import MIN_DAYS, HourlyData, HourlyMeter, NotEnoughData, calibrate
from calibration.fit import auto_substeps
from ingest._table import read_table
from ingest.units import dimension_of
from scenarios import Tariff
from survey import PROVINCES, HomeDescription, build_twin, home_summary, questions_json
from survey import assumptions as _assumptions
from survey.climate import typical_year
from survey.example import (
    Truth,
    electricity_csv,
    example_period,
    gas_bill,
    thermometer_csv,
)

#: The language of every sentence the session writes: "en" or "es".
LANG = "en"


def _t(key: str, **values: object) -> str:
    return t(key, LANG, **values)


def _n(x: float, digits: int = 0) -> str:
    return num(x, LANG, digits)


#: The engine in the browser is the NumPy backend; tests may switch it.
BACKEND = "numpy"
#: The example files: next to this module in the bundle (/app/samples), in
#: web/samples/ when run from the repository.
_HERE = Path(__file__).resolve().parent
SAMPLES = _HERE / "samples" if (_HERE / "samples").is_dir() else _HERE.parent / "samples"
#: The example homes: label, answers file, files dropped (relative to SAMPLES).
SAMPLE_SETS: dict[str, tuple[str, str, list[str]]] = {
    "electric": (
        "All-electric flat, January 2026",
        "home.json",
        [
            "consumo_horario_enero_2026.csv",
            "estacion_meteo_enero_2026.csv",
            "termometro_interior_enero_2026.csv",
        ],
    ),
    **{
        key: (
            f"Gas home, {label}",
            "gas_home/home.json",
            [
                f"gas_home/{folder}/{what}_{folder}.{ext}"
                for what, ext in (
                    ("consumo_horario", "csv"),
                    ("factura_gas", "csv"),
                    ("factura_agua", "csv"),
                    ("open_meteo", "json"),
                    ("termometro_interior", "csv"),
                )
            ],
        )
        for key, folder, label in (
            ("gas_dec_jan", "15dic-15ene", "15 Dec to 15 Jan"),
            ("gas_feb_mar", "15feb-15mar", "15 Feb to 15 Mar"),
            ("gas_oct_nov", "15oct-15nov", "15 Oct to 15 Nov"),
        )
    },
    "gas_winter": (
        "Gas home, the whole winter (3 periods)",
        "gas_home/home.json",
        [
            f"gas_home/{folder}/{what}_{folder}.{ext}"
            for folder in ("15oct-15nov", "15dic-15ene", "15feb-15mar")
            for what, ext in (
                ("consumo_horario", "csv"),
                ("factura_gas", "csv"),
                ("factura_agua", "csv"),
                ("open_meteo", "json"),
                ("termometro_interior", "csv"),
            )
        ],
    ),
}
#: Water a Spanish household uses, litres per person per day (INE, about 130).
TYPICAL_WATER_L_PER_PERSON = 130.0
#: How long one period of gas bills may span when they carry the heating.
MAX_GAS_RECORD_DAYS = 62
#: The shortest period worth a spin-up of its own, days.
MIN_PERIOD_DAYS = 7
#: At most this many periods are calibrated together (the most recent): each
#: is simulated on its own, and the browser should answer within a minute.
MAX_PERIODS = 4

_FORMATS = {
    "datadis_json": "Datadis download",
    "distributor_csv": "hourly electricity from Datadis or your distributor",
    "ide_csv": "i-DE (Iberdrola) consumption file",
    "shelly_csv": "Shelly meter export",
    "tapo_xlsx": "Tapo plug export",
    "ha_statistics": "Home Assistant statistics",
    "ha_history": "Home Assistant history",
    "gas_bills": "gas bills",
    "water_bills": "water bills",
    "typed_gas": "a gas bill typed in",
    "typed_water": "a water bill typed in",
    "open_meteo_json": "Open-Meteo weather",
    "open_meteo_csv": "Open-Meteo weather",
    "mapped": "your own columns",
}
_QUANTITIES = {
    "electricity_import": "electricity from the grid",
    "electricity_export": "electricity sent to the grid",
    "electricity_self_consumption": "solar electricity used at home",
    "plug_energy": "smart-plug energy",
    "plug_power": "smart-plug power",
    "gas_energy": "gas (kWh billed)",
    "gas_volume": "gas (m³)",
    "water_volume": "water",
    "electricity_cost": "electricity cost",
    "gas_cost": "gas cost",
    "water_cost": "water cost",
    "outdoor_temperature": "outdoor temperature",
    "indoor_temperature": "indoor temperature (interior thermometer)",
    "solar_irradiance": "sunshine",
}
#: What the column mapper offers, and the units it lets each one be in.
MAPPABLE = {
    "electricity_import": ("electricity from the grid", ["kWh", "Wh"]),
    "outdoor_temperature": ("outdoor temperature", ["°C", "K", "°F"]),
    "indoor_temperature": ("indoor temperature", ["°C", "K", "°F"]),
    "plug_energy": ("an appliance's energy (smart plug)", ["kWh", "Wh"]),
    "gas_volume": ("gas (m³)", ["m³", "L"]),
    "water_volume": ("water (m³)", ["m³", "L"]),
}
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


@dataclass
class FileEntry:
    """One file the householder dropped, as the session knows it."""

    name: str
    data: bytes
    status: str  # "ok", "needs_mapping", "error"
    format: str = ""
    series: list = field(default_factory=list)
    message: str = ""
    mapping: dict | None = None
    #: what went wrong, as a text key and its values, so it reads in any language
    problem: tuple[str, dict] | None = None


SESSION: dict[str, FileEntry] = {}
#: The example home loaded with load_samples, if any: its key, its truth,
#: and the answers its files in SESSION were made for.
EXAMPLE: dict[str, Any] = {}


# ---------------------------------------------------------------- helpers


def _day(ts: int, tz: str) -> str:
    d = datetime.fromtimestamp(int(ts), ZoneInfo(tz))
    return f"{d.day} {MONTHS[LANG][d.month - 1]} {d.year}"


def _describe_series(s, tz: str) -> str:
    what = _t(f"q_{s.quantity}") if f"q_{s.quantity}" in _TEXT_KEYS else s.quantity
    span = (
        f"{_day(s.start[0], tz)} {_t('to')} {_day(s.end[-1] - 1, tz)}"
        if len(s)
        else _t("no_readings")
    )
    if s.kind == "interval" and s.quantity.endswith(
        ("_import", "_export", "consumption", "energy")
    ):
        total = f", {_n(s.values_in('kWh').sum())} kWh"
    elif s.quantity.endswith("_volume"):
        total = f", {_n(s.values_in('m3').sum(), 1)} m³"
    elif s.quantity.endswith("temperature"):
        v = s.values_in("degC")
        total = _t("range_c", lo=f"{v.min():.0f}", hi=f"{v.max():.0f}")
    else:
        total = ""
    step = ""
    if s.kind != "instant" and len(s):
        h = float(np.median(s.end - s.start)) / 3600.0
        step = _t("hourly_") if h == 1 else _t("quarter_hourly_") if h == 0.25 else ""
    return _t("readings_from", step=step, what=what, n=len(s), span=span, total=total)


def _describe_bills(e: FileEntry, tz: str) -> str:
    """Bills as printed: reading dates, m³ and, for gas, the kWh charged."""
    parts = []
    for s in e.series:
        if not s.quantity.endswith("_volume"):
            continue
        kwh = {
            (int(a), int(b)): v / 3.6e6
            for k in e.series
            if k.quantity == "gas_energy"
            for a, b, v in zip(k.start, k.end, k.value, strict=True)
        }
        for a, b, v in zip(s.start, s.end, s.values_in("m3"), strict=True):
            text = _t(
                "bill_line", first=_day(int(a), tz), last=_day(int(b), tz), m3=_n(v)
            )
            k = kwh.get((int(a), int(b)))
            if k is not None:
                text += _t("charged_as", kwh=_n(k))
            parts.append(text)
    n = len(parts)
    what = _t("gas") if any(s.quantity == "gas_volume" for s in e.series) else _t("water")
    return _t(
        "read_bills",
        n=n,
        what=what,
        bills=_t("bill") if n == 1 else _t("bills"),
        leidas="Leída" if n == 1 else "Leídas",
        parts="; ".join(parts),
    )


def _describe_electricity_bill(e: FileEntry, tz: str) -> str:
    kwh = next(s for s in e.series if s.quantity == "electricity_billed")
    cost = next((s for s in e.series if s.quantity == "electricity_cost"), None)
    eur = _t("for_eur", eur=_n(float(cost.value[0]), 2)) if cost is not None else ""
    return _t(
        "read_electricity_bill",
        first=_day(int(kwh.start[0]), tz),
        last=_day(int(kwh.end[0]) - 1, tz),
        kwh=_n(float(kwh.values_in("kWh")[0])),
        eur=eur,
    )


def _format_name(fmt: str) -> str:
    return _t(f"fmt_{fmt}") if f"fmt_{fmt}" in _TEXT_KEYS else _FORMATS.get(fmt, fmt)


def _summary(file_id: str, e: FileEntry, tz: str) -> dict[str, Any]:
    out: dict[str, Any] = {"id": file_id, "name": e.name, "status": e.status}
    if e.status == "ok" and e.format == "typed_electricity":
        out["format"] = _format_name(e.format)
        out["message"] = _describe_electricity_bill(e, tz)
    elif e.status == "ok" and e.format in (
        "gas_bills",
        "water_bills",
        "typed_gas",
        "typed_water",
    ):
        out["format"] = _format_name(e.format)
        out["message"] = _describe_bills(e, tz)
    elif e.status == "ok":
        order = list(_QUANTITIES)
        ranked = sorted(
            e.series,
            key=lambda s: order.index(s.quantity) if s.quantity in order else len(order),
        )
        parts = [_describe_series(s, tz) for s in ranked]
        out["format"] = _format_name(e.format)
        out["message"] = _t("read_as", format=out["format"], parts="; ".join(parts))
    elif e.problem is not None:
        out["message"] = _t(e.problem[0], **e.problem[1])
    else:
        out["message"] = e.message
    if e.mapping is not None:
        out["mapping"] = e.mapping
    return out


#: Words in a column's name that say a temperature is indoors.
_INDOOR_WORDS = (
    "interior",
    "indoor",
    "inside",
    "salón",
    "salon",
    "dentro",
    "room",
    "habitación",
)


def _guess_mapping(raw: bytes) -> dict[str, Any]:
    """What the column mapper shows: the columns, a preview, and a first guess."""
    d = ingest.describe_csv(raw)
    table = read_table(raw)  # the same reader the parsers use
    preview = [row for row in table.rows[:5]]
    cols = [
        {"name": c.name, "role": c.role, "unit": c.unit, "example": c.example}
        for c in d.columns
    ]
    time_col = next((c.name for c in d.columns if c.role == "time"), None)
    value = next((c for c in d.columns if c.role == "number" and c.unit), None) or next(
        (c for c in d.columns if c.role == "number"), None
    )
    quantity, unit = "outdoor_temperature", "°C"
    if value is not None and value.unit:
        dim = dimension_of(value.unit)
        indoors = any(w in value.name.lower() for w in _INDOOR_WORDS)
        quantity = {
            "temperature": "indoor_temperature" if indoors else "outdoor_temperature",
            "energy": "electricity_import",
            "volume": "water_volume",
            "power": "plug_energy",
        }.get(dim, quantity)
        unit = {"degC": "°C", "degF": "°F", "m^3": "m³"}.get(value.unit, value.unit)
    return {
        "columns": cols,
        "preview": preview,
        "headers": [c.name for c in d.columns],
        "rows": d.n_rows,
        "quantities": [
            {"value": k, "label": v[0], "units": v[1]} for k, v in MAPPABLE.items()
        ],
        # a temperature column whose name says indoors or outdoors, with a
        # time column: the page reads it with this guess by itself
        "confident": bool(
            time_col
            and value is not None
            and quantity.endswith("temperature")
            and (
                any(w in value.name.lower() for w in _INDOOR_WORDS)
                or any(
                    w in value.name.lower() for w in ("exterior", "outdoor", "outside")
                )
            )
        ),
        "guess": {
            "time": time_col,
            "value": value.name if value is not None else None,
            "quantity": quantity,
            "unit": unit,
            "cumulative": False,
            "label": "start",
        },
    }


def _parse(name: str, data: bytes, tz: str) -> FileEntry:
    try:
        fmt = ingest.detect_format(data)
    except ingest.IngestError as exc:
        text = str(exc)
        if "unrecognised file" in text and data[:4] != b"PK\x03\x04":
            try:
                mapping = _guess_mapping(data)
            except Exception:
                return FileEntry(
                    name,
                    data,
                    "error",
                    message=f"This file could not be read: {exc}",
                    problem=("file_unreadable", {"detail": str(exc)}),
                )
            return FileEntry(
                name,
                data,
                "needs_mapping",
                message="We don't know this layout. Tell us which column is which.",
                problem=("file_layout", {}),
                mapping=mapping,
            )
        return FileEntry(
            name,
            data,
            "error",
            message=f"This file could not be read: {exc}",
            problem=("file_unreadable", {"detail": str(exc)}),
        )
    parser = ingest.FORMATS[fmt]
    options: dict[str, Any] = {}
    params = inspect.signature(parser).parameters
    if "timezone" in params:
        options["timezone"] = tz
    if fmt == "ha_history":
        return FileEntry(
            name,
            data,
            "error",
            problem=("ha_history", {}),
            message=(
                "Home Assistant history files carry no units. Export long-term statistics "
                "instead (they include units), or use the column mapper on a CSV."
            ),
        )
    try:
        series = parser(data, source=name, **options)
    except ingest.IngestError as exc:
        if fmt == "ha_statistics" and "say which quantity" in str(exc):
            quantities = {}
            for line in data.decode("utf-8", "replace").splitlines()[1:]:
                sid = line.split("\t")[0].split(",")[0].strip()
                low = sid.lower()
                if "gas" in low:
                    quantities[sid] = "gas_volume"
                elif "water" in low or "agua" in low:
                    quantities[sid] = "water_volume"
            try:
                series = parser(data, source=name, quantities=quantities, **options)
            except ingest.IngestError as again:
                return FileEntry(
                    name,
                    data,
                    "error",
                    message=f"This file could not be read: {again}",
                    problem=("file_unreadable", {"detail": str(again)}),
                )
        else:
            return FileEntry(
                name,
                data,
                "error",
                message=f"This file could not be read: {exc}",
                problem=("file_unreadable", {"detail": str(exc)}),
            )
    return FileEntry(name, data, "ok", format=fmt, series=list(series))


# ---------------------------------------------------------------- step 1


def questions() -> dict[str, Any]:
    """The first step's questions (the same data the build bakes into the page)."""
    return questions_json(LANG)


def assumptions(answers: dict[str, Any]) -> dict[str, Any]:
    """What the twin will start from, for these answers."""
    try:
        desc = HomeDescription.from_answers(answers)
    except ValueError as exc:
        return {"ok": False, "sentences": [str(exc)]}
    return {
        "ok": True,
        "sentences": _assumptions(desc),
        "summary": [{"topic": a, "text": b} for a, b in home_summary(desc, LANG)],
        "uses_gas": desc.uses_gas,
    }


# ---------------------------------------------------------------- step 2


def read_file(
    file_id: str, name: str, data: bytes, timezone_name: str = "Europe/Madrid"
) -> dict[str, Any]:
    """Read a dropped file in memory; recognised, needing a mapping, or refused."""
    entry = _parse(name, bytes(data), timezone_name)
    SESSION[file_id] = entry
    return _summary(file_id, entry, timezone_name)


def map_file(
    file_id: str, mapping: dict[str, Any], timezone_name: str = "Europe/Madrid"
) -> dict[str, Any]:
    """Read a file with the columns the householder picked in the mapper."""
    entry = SESSION[file_id]
    unit = {"°C": "degC", "°F": "degF", "m³": "m3"}.get(
        mapping.get("unit"), mapping.get("unit")
    )
    quantity = mapping["quantity"]
    kind = "instant" if quantity.endswith("temperature") else None
    try:
        cmap = ingest.ColumnMap(
            quantity=quantity,
            value=mapping["value"],
            unit=unit,
            time=mapping["time"],
            cumulative=bool(mapping.get("cumulative")),
            label=mapping.get("label", "start"),
            kind=kind,
            timezone=timezone_name,
            channel=entry.name,
        )
        series = ingest.parse_mapped(entry.data, cmap, source=entry.name)
    except (ingest.IngestError, ValueError, KeyError) as exc:
        entry.message = _t("mapping_failed", detail=str(exc))
        return {
            **_summary(file_id, entry, timezone_name),
            "status": "needs_mapping",
            "error": entry.message,
        }
    entry.status, entry.format, entry.series, entry.mapping = (
        "ok",
        "mapped",
        list(series),
        None,
    )
    return _summary(file_id, entry, timezone_name)


#: The bill form's fields, by the CSV column they become.
_FORM_FIELDS = {
    "inicio": "first reading date",
    "fin": "last reading date",
    "m3": "m³",
    "fc": "conversion factor (Fc)",
    "pcs_kwh_m3": "calorific value (PCS)",
    "kwh": "kWh",
    "importe_eur": "amount",
}


def add_bill(
    file_id: str, kind: str, bill: dict[str, Any], timezone_name: str = "Europe/Madrid"
) -> dict[str, Any]:
    """A gas or water bill typed into the form, read like an uploaded one.

    ``bill`` has ``start`` and ``end`` (the reading dates, YYYY-MM-DD), ``m3``,
    and for gas ``fc`` and ``pcs`` (as printed) and optionally ``kwh``; ``eur``
    is optional. Decimal commas are accepted. The bill goes through the same
    checks as a file, including kWh = m³ × Fc × PCS.
    """
    if kind not in ("gas", "water", "electricity"):
        raise ValueError(f"kind must be 'gas', 'water' or 'electricity', not {kind!r}")

    def num(key: str) -> str:
        v = str(bill.get(key) or "").strip().replace(",", ".")
        return v

    if kind == "electricity":
        return _add_electricity_bill(file_id, bill, num, timezone_name)

    record = {
        "inicio": bill.get("start", ""),
        "fin": bill.get("end", ""),
        "m3": num("m3"),
    }
    if kind == "gas":
        record.update(fc=num("fc"), pcs_kwh_m3=num("pcs"), kwh=num("kwh"))
    record["importe_eur"] = num("eur")
    csv = ingest.bills_to_csv([record]).encode()
    parser = ingest.parse_gas_bills if kind == "gas" else ingest.parse_water_bills
    what = _t("gas_bill_title") if kind == "gas" else _t("water_bill_title")

    def readable(d: str) -> str:
        try:
            return f"{date.fromisoformat(d):%d/%m/%Y}"
        except ValueError:
            return d or "?"

    name = _t(
        "typed_bill_name",
        what=what,
        first=readable(record["inicio"]),
        last=readable(record["fin"]),
    )
    try:
        series = parser(csv, source=name, timezone=timezone_name)
    except ingest.IngestError as exc:
        m = re.search(r"column '([^']+)': (.*)$", str(exc))
        if m:
            key = f"field_{m.group(1)}"
            field_ = _t(key) if key in _TEXT_KEYS else m.group(1)
            text = _t("check_field", field=field_, detail=m.group(2))
        else:
            text = str(exc).split(": ", 1)[-1]
        entry = FileEntry(
            name,
            csv,
            "error",
            message=f"This bill could not be read. {text}",
            problem=("bill_unreadable", {"detail": text}),
        )
    else:
        entry = FileEntry(name, csv, "ok", format=f"typed_{kind}", series=list(series))
    SESSION[file_id] = entry
    return _summary(file_id, entry, timezone_name)


def _add_electricity_bill(
    file_id: str, bill: dict[str, Any], num, tz: str
) -> dict[str, Any]:
    """An electricity bill: the kWh billed over its period and, if given, the
    amount. It does not replace the hourly electricity the fit needs; it
    tells what the electricity really cost (the bill panel) and lets the
    hourly record be checked against the bill."""
    zone = ZoneInfo(tz)
    name = _t("electricity_bill_title")
    try:
        start = datetime.fromisoformat(bill.get("start", "")).replace(tzinfo=zone)
        end = datetime.fromisoformat(bill.get("end", "")).replace(tzinfo=zone)
        kwh = float(num("kwh"))
        eur = float(num("eur")) if num("eur") else None
        if end <= start:
            raise ValueError(
                _t("check_field", field=_t("field_fin"), detail="end before start")
            )
        if not 1 <= kwh <= 20000:
            raise ValueError(_t("check_field", field="kWh", detail=f"{kwh} kWh"))
    except ValueError as exc:
        text = str(exc)
        entry = FileEntry(
            name,
            b"",
            "error",
            message=text,
            problem=("bill_unreadable", {"detail": text}),
        )
        SESSION[file_id] = entry
        return _summary(file_id, entry, tz)
    t0, t1 = int(start.timestamp()), int(end.timestamp())
    name = _t(
        "typed_bill_name", what=name, first=f"{start:%d/%m/%Y}", last=f"{end:%d/%m/%Y}"
    )
    series = [
        ingest.Series(
            "electricity_billed",
            "main",
            "interval",
            np.array([t0], dtype=np.int64),
            np.array([t1], dtype=np.int64),
            np.array([kwh * 3.6e6]),
            np.array([False]),
            source=name,
        )
    ]
    if eur is not None:
        series.append(
            ingest.Series(
                "electricity_cost",
                "main",
                "interval",
                np.array([t0], dtype=np.int64),
                np.array([t1], dtype=np.int64),
                np.array([eur]),
                np.array([False]),
                source=name,
            )
        )
    entry = FileEntry(name, b"", "ok", format="typed_electricity", series=series)
    SESSION[file_id] = entry
    return _summary(file_id, entry, tz)


def read_invoice(pages: list, hint: str | None = None) -> dict[str, Any]:
    """The fields of a bill, from the words on its pages (each page a list of
    ``{text, x, y, w, h, conf}``), with a sentence saying what was read and
    the form the page should prefill. Nothing is added to the session."""
    words = [
        [
            ingest.Word(
                str(w.get("text", "")),
                float(w.get("x", 0)),
                float(w.get("y", 0)),
                float(w.get("w", 0)),
                float(w.get("h", 0)),
                float(w.get("conf", 1.0)),
            )
            for w in page
            if str(w.get("text", "")).strip()
        ]
        for page in pages
    ]
    inv = ingest.read_invoice(words, hint)
    out = inv.as_dict()
    fields = {
        k: v["value"]
        for k, v in out.items()
        if isinstance(v, dict) and v and "value" in v
    }
    read_any = any(k in fields for k in ("kwh", "m3", "eur", "start"))
    kind = (
        inv.kind
        if inv.kind != "unknown"
        else (
            "gas"
            if "m3" in fields and "kwh" in fields
            else "water"
            if "m3" in fields
            else "electricity"
        )
    )
    form = {
        "start": fields.get("start", ""),
        "end": fields.get("end", ""),
        "kwh": _plain(fields.get("kwh")),
        "m3": _plain(fields.get("m3")),
        "fc": _plain(fields.get("fc")),
        "pcs": _plain(fields.get("pcs")),
        "eur": _plain(fields.get("eur")),
    }
    period = (
        _t("inv_period", first=_readable(fields["start"]), last=_readable(fields["end"]))
        if "start" in fields and "end" in fields
        else ""
    )
    amounts = []
    if "kwh" in fields:
        amounts.append(f"{_n(fields['kwh'])} kWh")
    if "m3" in fields:
        amounts.append(f"{_n(fields['m3'], 1)} m³")
    if "eur" in fields:
        amounts.append(f"{_n(fields['eur'], 2)} €")
    sentence = (
        _t(
            "inv_read",
            kind=_t(f"inv_kind_{inv.kind}"),
            **{"from": _t("inv_from", supplier=inv.supplier) if inv.supplier else ""},
            period=period,
            amounts=(": " + ", ".join(amounts)) if amounts else "",
        )
        if read_any
        else _t("inv_nothing")
    )
    notes = [_t(f"inv_{n}") for n in inv.notes if f"inv_{n}" in _TEXT_KEYS]
    return {
        "ok": read_any,
        "kind": kind,
        "fields": out,
        "form": form,
        "sentence": sentence,
        "notes": notes,
    }


def _plain(v) -> str:
    if v is None:
        return ""
    return str(int(v)) if float(v) == int(v) else str(round(float(v), 4))


def _readable(d: str) -> str:
    try:
        return f"{date.fromisoformat(d):%d/%m/%Y}"
    except ValueError:
        return d


def remove_file(file_id: str) -> dict[str, Any]:
    """Forget a file."""
    SESSION.pop(file_id, None)
    return {"ok": True}


def _series_of(quantity: str) -> list:
    return [
        s
        for e in SESSION.values()
        if e.status == "ok"
        for s in e.series
        if s.quantity == quantity
    ]


def _hourly(s):
    """Hourly electricity: quarter-hours summed when all four are present."""
    dur = s.end - s.start
    if np.all(dur == 3600):
        return s
    if not np.all(dur == 900):
        return None
    hours = (s.start // 3600) * 3600
    uniq, idx, counts = np.unique(hours, return_inverse=True, return_counts=True)
    total = np.bincount(idx, weights=s.value)
    keep = counts == 4
    return ingest.Series(
        s.quantity,
        s.channel,
        "interval",
        uniq[keep],
        uniq[keep] + 3600,
        total[keep],
        source=s.source,
    )


def _best_electricity():
    by_channel: dict[str, list] = {}
    for s in _series_of("electricity_import"):
        h = _hourly(s)
        if h is not None:
            by_channel.setdefault(s.channel, []).append(h)
    if not by_channel:
        return None
    merged = {
        c: ingest.merge(*ss) if len(ss) > 1 else ss[0] for c, ss in by_channel.items()
    }
    return max(merged.values(), key=len)


@dataclass(frozen=True)
class Bill:
    """One gas or water bill from the session: UTC seconds, m³, and for gas kWh."""

    start: int
    end: int
    m3: float
    kwh: float | None = None
    estimated: bool = False

    @property
    def days(self) -> float:
        """Length, days."""
        return (self.end - self.start) / 86400.0

    @property
    def kwh_per_m3(self) -> float | None:
        """The bill's own conversion, Fc × PCS: kWh per m³."""
        return self.kwh / self.m3 if self.kwh is not None and self.m3 > 0 else None


def _bills(kind: str) -> list[Bill]:
    """Every gas or water bill in the session, by date, repeats dropped.

    A bill is an interval of ``<kind>_volume`` that spans at least a day (an
    hourly water logger is a meter, not a bill); for gas, the bill's
    ``gas_energy`` from the same file gives its kWh.
    """
    found: dict[tuple[int, int], Bill] = {}
    for e in SESSION.values():
        if e.status != "ok":
            continue
        energy = {
            (int(a), int(b)): float(v) / 3.6e6
            for s in e.series
            if s.quantity == "gas_energy"
            for a, b, v in zip(s.start, s.end, s.value, strict=True)
        }
        for s in e.series:
            if s.quantity != f"{kind}_volume" or s.kind != "interval":
                continue
            for a, b, v, q in zip(
                s.start, s.end, s.values_in("m3"), s.quality, strict=True
            ):
                if b - a < 86400:
                    continue
                key = (int(a), int(b))
                found[key] = Bill(key[0], key[1], float(v), energy.get(key), bool(q))
    return [found[k] for k in sorted(found)]


def _gas_series(bills: list[Bill]):
    """Bills with kWh, as the ``gas_energy`` series calibration reads."""
    bills = [b for b in bills if b.kwh is not None]
    return ingest.Series(
        "gas_energy",
        "gas",
        "interval",
        np.array([b.start for b in bills], dtype=np.int64),
        np.array([b.end for b in bills], dtype=np.int64),
        np.array([b.kwh * 3.6e6 for b in bills]),
        np.array([b.estimated for b in bills], dtype=bool),
        source="gas bills",
    )


@dataclass(frozen=True)
class Period:
    """One stretch of time to calibrate on, UTC seconds [start, end).

    ``gas`` says the gas bills inside it go into the fit (gas heating)."""

    start: int
    end: int
    gas: bool = False

    @property
    def days(self) -> float:
        """Length, days."""
        return (self.end - self.start) / 86400.0


def _runs(starts: np.ndarray, max_gap: int) -> list[tuple[int, int]]:
    """Contiguous runs of hour starts, broken where readings stop for more than
    ``max_gap`` seconds: ``[(first, last + 1 h), ...]``."""
    t = np.unique(np.asarray(starts, dtype=np.int64))
    if not t.size:
        return []
    cut = np.flatnonzero(np.diff(t) > max_gap)
    firsts = np.concatenate([[0], cut + 1])
    lasts = np.concatenate([cut, [t.size - 1]])
    return [(int(t[a]), int(t[b]) + 3600) for a, b in zip(firsts, lasts, strict=True)]


def _blocks(elec, weather) -> list[tuple[int, int]]:
    """Where hourly electricity and outdoor temperature are both present, as
    separate blocks: three monthly downloads with weeks between them are
    three blocks. Short holes inside a block (a missing day of electricity,
    a few hours of weather) stay inside it."""
    e_runs = _runs(elec.start, 24 * 3600)
    w_runs = _runs(np.ceil(weather.start / 3600.0) * 3600, 4 * 3600)
    out = []
    for a0, a1 in e_runs:
        for b0, b1 in w_runs:
            t0, t1 = max(a0, b0), min(a1, b1)
            if t1 - t0 >= 86400:
                out.append((t0, t1))
    return sorted(out)


def _bill_groups(bills: list[Bill], t0: int, t1: int) -> list[tuple[int, int]]:
    """The gas bills inside [t0, t1), consecutive ones together while a group
    stays within :data:`MAX_GAS_RECORD_DAYS`."""
    inside = [b for b in bills if b.kwh is not None and t0 <= b.start and b.end <= t1]
    groups: list[list[int]] = []
    for b in inside:
        if (
            groups
            and groups[-1][1] == b.start
            and b.end - groups[-1][0] <= (MAX_GAS_RECORD_DAYS * 86400)
        ):
            groups[-1][1] = b.end
        else:
            groups.append([b.start, b.end])
    return [(a, b) for a, b in groups]


def _most_telling(t0: int, t1: int, weather, desc: HomeDescription) -> tuple[int, int]:
    """A block as it is, or its most telling 31 days when longer than five weeks."""
    if t1 - t0 <= 35 * 86400:
        return t0, t1
    wt = weather.start.astype(float)
    wv = weather.value
    candidates = []
    for start in range(t0, t1 - 31 * 86400 + 1, 86400):
        end = start + 31 * 86400
        sel = (wt >= start) & (wt < end)
        if sel.sum() < 31 * 24 * 0.9:
            continue
        candidates.append((float(wv[sel].mean()), start, end))
    if not candidates:
        return t1 - 31 * 86400, t1
    if desc.heating in ("heat_pump", "electric"):
        _, s, e = min(candidates)  # the coldest month shows the heating best
    elif desc.cooling == "yes":
        _, s, e = max(candidates)  # the hottest shows the air conditioning
    else:
        _, s, e = max(candidates, key=lambda c: c[1])  # the most recent
    return s, e


def _periods(desc: HomeDescription, elec, weather) -> list[Period]:
    """Every period the files allow calibrating on, oldest first.

    Each block of electricity and weather gives one period: for a gas-heated
    home, the dates of the gas bills inside it (so bill and record line up);
    otherwise the block, or its most telling 31 days. Periods shorter than
    :data:`MIN_PERIOD_DAYS` are left out; at most :data:`MAX_PERIODS`, the
    most recent, are kept."""
    bills = _bills("gas") if desc.heating == "gas" else []
    out: list[Period] = []
    for t0, t1 in _blocks(elec, weather):
        groups = _bill_groups(bills, t0, t1)
        if groups:
            for a, b in groups:
                if b - a < MIN_DAYS * 86400:  # pad a short bill with the days before
                    a = max(t0, b - MIN_DAYS * 86400)
                out.append(Period(a, b, gas=True))
        else:
            out.append(Period(*_most_telling(t0, t1, weather, desc)))
    out = [p for p in out if p.days >= MIN_PERIOD_DAYS]
    return out[-MAX_PERIODS:]


def _merged(series: list):
    """Several files of the same quantity (one weather file per month) as one
    series: by time, an instant given twice kept once."""
    if len(series) <= 1:
        return series[0] if series else None
    start = np.concatenate([s.start for s in series])
    order = np.argsort(start, kind="stable")
    start = start[order]
    keep = np.concatenate([[True], np.diff(start) > 0])
    pick = order[keep]
    cat = lambda name: np.concatenate([getattr(s, name) for s in series])[pick]  # noqa: E731
    first = series[0]
    return ingest.Series(
        first.quantity,
        first.channel,
        first.kind,
        start[keep],
        cat("end"),
        cat("value"),
        cat("quality"),
        source=", ".join(dict.fromkeys(s.source for s in series)),
    )


def _best_weather():
    return _merged(_series_of("outdoor_temperature"))


def _best_indoor():
    return _merged(_series_of("indoor_temperature"))


def _record(desc: HomeDescription, period: str | int = "all"):
    """The record to calibrate on: every period together, or one of them.

    Returns ``(data, elec, weather, periods, gas_used)``: ``periods`` lists
    every period the files allow; ``data`` joins the chosen ones (see
    :meth:`calibration.HourlyData.join`); ``gas_used`` says gas bills are in
    it (only when the heating runs on gas).
    """
    elec, weather = _best_electricity(), _best_weather()
    if elec is None or weather is None:
        return None, elec, weather, [], False
    periods = _periods(desc, elec, weather)
    if not periods:
        return None, elec, weather, [], False
    if period == "all":
        chosen = periods
    else:
        wanted = period if isinstance(period, list | tuple) else [period]
        for k in wanted:
            if not 0 <= int(k) < len(periods):
                raise ValueError(f"there is no period {k}; there are {len(periods)}")
        chosen = [periods[int(k)] for k in wanted]
    tz = ZoneInfo(desc.timezone)
    gas = _gas_series(_bills("gas")) if any(p.gas for p in chosen) else None
    pieces = [
        HourlyData.from_series(
            elec,
            weather,
            start=datetime.fromtimestamp(p.start, timezone.utc).astimezone(tz),
            end=datetime.fromtimestamp(p.end, timezone.utc).astimezone(tz),
            timezone_name=desc.timezone,
            gas=gas if p.gas else None,
            indoor=_best_indoor(),
            check_length=False,
        )
        for p in chosen
    ]
    data = HourlyData.join(pieces)
    if len(pieces) == 1:  # join returns the piece itself: check it as a whole
        data = replace(data, check_length=True)
    return data, elec, weather, periods, bool(data.gas_bills)


def _period_label(p: Period, tz: str) -> str:
    """15 Oct 2025 to 15 Nov 2025: the first day and the day after the last,
    as bills write their reading dates."""
    return f"{_date(p.start, tz)} {_t('to')} {_date(p.end, tz)}"


def _periods_info(periods: list[Period], weather, tz: str) -> list[dict[str, Any]]:
    out = []
    t = weather.start
    v = weather.values_in("degC")
    for k, p in enumerate(periods):
        sel = (t >= p.start) & (t < p.end)
        out.append(
            {
                "id": k,
                "label": _period_label(p, tz),
                "days": round(p.days, 1),
                "mean_c": round(float(v[sel].mean()), 1) if sel.any() else None,
                "gas_bill": p.gas,
            }
        )
    return out


def _date(ts: int, tz: str) -> str:
    """A day, as a householder writes it: 15 Dec 2025."""
    return _day(ts, tz)


def _period(b: Bill, tz: str) -> str:
    """A bill's reading dates: 15 Dec 2025 to 15 Jan 2026."""
    return f"{_date(b.start, tz)} {_t('to')} {_date(b.end, tz)}"


def _weather_request(desc: HomeDescription, elec) -> dict[str, Any] | None:
    if elec is None:
        return None
    p = next(p for p in PROVINCES if p.value == desc.province)
    tz = ZoneInfo(p.timezone)
    first = datetime.fromtimestamp(int(elec.start[0]), tz).date()
    last = datetime.fromtimestamp(int(elec.end[-1]) - 1, tz).date()
    last = min(last, date.today() - timedelta(days=5))  # the archive lags a few days
    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={p.latitude}&longitude={p.longitude}"
        f"&start_date={first:%Y-%m-%d}&end_date={last:%Y-%m-%d}"
        "&hourly=temperature_2m&timeformat=unixtime"
        f"&timezone={p.timezone.replace('/', '%2F')}"
    )
    return {"province": p.label, "url": url, "first": str(first), "last": str(last)}


def _gas_messages(desc: HomeDescription, data, gas_used: bool) -> list[str]:
    """What the page says about gas: what to add, and what will be used."""
    if not desc.uses_gas:
        return []
    tz = desc.timezone
    bills = _bills("gas")
    if not bills:
        if desc.heating == "gas":
            return [
                "Add your gas bill for the same dates. Your heating runs on gas, so the "
                "gas bill is what shows how well your home keeps its heat. Drop the "
                "file, or type the bill in below."
            ]
        return [
            "You can add your gas bill too: we will compare it with what your hot "
            "water and cooking would typically use."
        ]
    if gas_used:
        used = [b for b in bills if data is not None and _bill_in(data, b)]
        parts = [f"{_period(b, tz)} ({b.m3:.0f} m³, {b.kwh:,.0f} kWh)" for b in used]
        which = "Your gas bill" if len(used) == 1 else "Your gas bills"
        return [f"{which} will be used too: {'; '.join(parts)}."]
    if desc.heating == "gas" and data is not None:
        b = bills[-1]
        return [
            f"Your gas bill ({_period(b, tz)}) is outside the dates of your hourly "
            "electricity. Download your electricity for the bill's dates so we can "
            "use them together."
        ]
    return [
        "Your gas bill will be compared with the twin's typical hot water and cooking."
    ]


def _utc_spans(data) -> list[tuple[int, int]]:
    """Each period of the record as UTC seconds [start, end)."""
    return [
        (int(w.timestamp()), int(w.timestamp()) + 3600 * (j - i))
        for i, j, w in data.spans
    ]


def _bill_in(data, b: Bill) -> bool:
    return any(t0 <= b.start and b.end <= t1 for t0, t1 in _utc_spans(data))


def _hour_index(data, ts: int) -> int:
    """The record's hour that starts at UTC ``ts``."""
    return int(np.searchsorted(data.timestamps(), ts))


def data_status(answers: dict[str, Any]) -> dict[str, Any]:
    """Is there enough to calibrate? Plain sentences either way."""
    desc = HomeDescription.from_answers(answers)
    messages: list[str] = []
    try:
        data, elec, weather, periods, gas_used = _record(desc)
    except NotEnoughData as exc:
        return {"ready": False, "messages": [str(exc)], "weather_request": None}
    except ValueError as exc:
        return {
            "ready": False,
            "messages": [f"The files do not fit together: {exc}"],
            "weather_request": None,
        }
    if elec is None:
        messages.append(
            "Add your hourly electricity: download it from Datadis (datadis.es) or your "
            "distributor's website, and drop the file here."
        )
    if weather is None:
        messages.append(
            "Add the outdoor temperature for the same dates: drop a weather file, or let "
            "us fetch it from Open-Meteo for your province."
        )
    if data is None:
        if elec is not None and weather is not None:
            messages.append(
                "Your electricity and weather files do not cover the same days."
            )
        messages += _gas_messages(desc, None, False)
        return {
            "ready": False,
            "messages": messages,
            "weather_request": _weather_request(desc, elec) if weather is None else None,
        }
    tz = desc.timezone
    info = _periods_info(periods, weather, tz)
    if len(periods) == 1:
        first, last = data.hour_label(0)[:10], data.hour_label(data.hours - 1)[:10]
        messages.append(
            f"Ready: {data.days:.0f} days of hourly electricity and outdoor temperature, "
            f"{first} to {last}."
        )
    else:
        parts = [
            f"{x['label']} (average {x['mean_c']:.0f} °C)"
            if x["mean_c"] is not None
            else x["label"]
            for x in info
        ]
        messages.append(
            f"Ready: {len(periods)} periods of hourly electricity and outdoor temperature, "
            f"{data.days:.0f} days in all: " + "; ".join(parts) + "."
        )
        messages.append(
            "We calibrate on all of them together, so the twin sees your home in "
            "different weather. In the next step you can also pick one, or compare them."
        )
    covered = sum(p.end - p.start for p in periods)
    available = sum(b - a for a, b in _blocks(elec, weather))
    if available > covered + 2 * 86400:
        if gas_used:
            messages.append(
                "Your files cover more than your gas bills; we use the dates of the bills."
            )
        else:
            messages.append(
                "Your files cover more than a month; we use the 31 days that show "
                "your home best (the coldest, for electric heating)."
            )
    messages += _gas_messages(desc, data, gas_used)
    if desc.heating == "gas" and not gas_used:
        messages.append(
            "Without a gas bill for these dates, the electricity will tell us about "
            "your appliances and always-on use, not about your walls."
        )
    if EXAMPLE and EXAMPLE["made_for"] != _answers_key(desc):
        messages.append(
            "Example home: when you calibrate, it is simulated again with your answers "
            "from step 1 (the thermostat by day and at night), so its electricity, gas "
            "and interior thermometer follow them."
        )
    if _best_indoor() is not None:
        messages.append(
            "Your interior thermometer will be used too: it shows how fast your home "
            "cools at night and warms in the morning."
        )
    if _bills("water"):
        messages.append(
            "Your water bill will be compared with a typical home like yours."
        )
    else:
        messages.append(
            "Optional: add your water bill to see how your water use compares."
        )
    return {
        "ready": True,
        "messages": messages,
        "weather_request": None,
        "days": round(data.days, 1),
        "periods": info,
    }


def load_samples(sample: str = "electric") -> dict[str, Any]:
    """One example home's answers and files, read as if dropped.

    Any files already in the session are forgotten first, so the example
    is the whole data. ``sample`` is a key of :data:`SAMPLE_SETS`.
    """
    if sample not in SAMPLE_SETS:
        raise KeyError(f"no such example: {sample!r}; examples: {list(SAMPLE_SETS)}")
    label, home, names = SAMPLE_SETS[sample]
    SESSION.clear()
    answers = json.loads((SAMPLES / home).read_text())
    tz = HomeDescription.from_answers(answers).timezone
    files = []
    for i, name in enumerate(names):
        out = read_file(f"sample-{i}", Path(name).name, (SAMPLES / name).read_bytes(), tz)
        if out["status"] == "needs_mapping" and (
            "termometro" in name or out["mapping"].get("confident")
        ):
            # a thermometer's or a weather station's log: read with the guess
            out = map_file(out["id"], out["mapping"]["guess"], tz)
        files.append(out)
    truth_path = SAMPLES / Path(home).parent / "truth.json"
    EXAMPLE.clear()
    EXAMPLE.update(
        key=sample,
        truth=Truth.from_json(json.loads(truth_path.read_text())),
        made_for=_answers_key(HomeDescription.from_answers(answers)),
    )
    return {"answers": answers, "files": files, "label": label}


def _given(desc: HomeDescription) -> list[str]:
    """The parameters the householder knows, kept as given and never fitted:
    the heating's power when it was read off the nameplate."""
    return ["heating.thermostat.power"] if desc.heating_kw is not None else []


def _answers_key(desc: HomeDescription) -> tuple:
    return tuple(sorted((k, str(v)) for k, v in desc.__dict__.items()))


def _reread(file_id: str, name: str, data: bytes, tz: str) -> dict[str, Any]:
    """A regenerated example file, read as if dropped (a thermometer log
    through the column mapper's own guess)."""
    out = read_file(file_id, name, data, tz)
    if out["status"] == "needs_mapping":
        out = map_file(file_id, out["mapping"]["guess"], tz)
    return out


def prepare_example(answers: dict[str, Any]) -> dict[str, Any]:
    """For an example home: simulate it again from these answers.

    The example's real home (its ``truth.json``) is combined with the
    answers on the page, above all the thermostat by day and at night, and
    every period it was loaded with is simulated again over its own weather:
    its electricity, its gas bill and its interior thermometer are written
    anew and read back like dropped files. Nothing happens for files a
    householder dropped, or when the answers have not changed.
    """
    if not EXAMPLE:
        return {"example": False, "changed": False, "files": []}
    desc = HomeDescription.from_answers(answers)
    key = _answers_key(desc)
    if EXAMPLE["made_for"] == key:
        return {"example": True, "changed": False, "files": []}
    tz = desc.timezone
    zone = ZoneInfo(tz)
    weather = _best_weather()
    if weather is None:
        return {"example": True, "changed": False, "files": []}
    truth = EXAMPLE["truth"]
    wt, wv = weather.start.astype(float), weather.values_in("degC")
    updated = []
    samples = {
        k: e for k, e in SESSION.items() if k.startswith("sample-") and e.status == "ok"
    }
    for fid, entry in samples.items():
        elec = next((x for x in entry.series if x.quantity == "electricity_import"), None)
        if elec is None:
            continue
        t0, t1 = int(elec.start[0]), int(elec.end[-1])
        hours = (t1 - t0) // 3600
        start = datetime.fromtimestamp(t0, timezone.utc).astimezone(zone)
        end = datetime.fromtimestamp(t1, timezone.utc).astimezone(zone)
        outdoor = np.interp(t0 + 3600.0 * np.arange(hours), wt, wv)
        rec = example_period(desc, truth, start=start, outdoor_c=outdoor)
        cups = read_table(entry.data).rows[0][0]
        updated.append(
            _reread(
                fid,
                entry.name,
                electricity_csv(cups, start, rec.data.electricity_kwh),
                tz,
            )
        )
        for gid, g in samples.items():
            vol = next((x for x in g.series if x.quantity == "gas_volume"), None)
            if vol is None or int(vol.start[0]) != t0 or int(vol.end[0]) != t1:
                continue
            table = read_table(g.data)  # the bill's own Fc, PCS and first reading
            fc = table.number(0, table.find("fc"))
            pcs = table.number(0, table.find("pcs_kwh_m3"))
            r0 = int(table.number(0, table.find("lectura_inicio_m3")))
            csv, _, _ = gas_bill(start, end, r0, float(rec.gas_kwh.sum()), fc, pcs)
            updated.append(_reread(gid, g.name, csv, tz))
        for tid, th in samples.items():
            ind = next((x for x in th.series if x.quantity == "indoor_temperature"), None)
            if ind is None or not (t0 <= int(ind.start[0]) < t1):
                continue
            csv = thermometer_csv(rec.thermometer_utc, rec.thermometer_c, zone)
            updated.append(_reread(tid, th.name, csv, tz))
    EXAMPLE["made_for"] = key
    night = (
        _t("night_lower")
        if desc.night == "lower"
        else _t("night_same", day=desc.thermostat)
    )
    return {
        "example": True,
        "changed": True,
        "files": updated,
        "message": _t("example_remade", day=desc.thermostat, night=night),
    }


# ---------------------------------------------------------------- step 3


def calibrate_home(answers: dict[str, Any], period: str | int = "all") -> dict[str, Any]:
    """Fit the home to the session's data, and the report to show.

    ``period`` is ``"all"`` (every period together) or the index of one
    period, as listed by :func:`data_status`."""
    t_start = time.perf_counter()
    desc = HomeDescription.from_answers(answers)
    example = prepare_example(answers)  # an example home follows the answers
    try:
        data, _, weather, periods, gas_used = _record(desc, period)
    except (NotEnoughData, ValueError) as exc:
        return {"ok": False, "message": str(exc)}
    if data is None:
        return {"ok": False, "message": "Add your electricity and the weather first."}
    mean_out = float(np.mean(data.outdoor_c))
    heating, cooling = mean_out < 18.0, mean_out >= 18.0
    notes = []
    if desc.cooling == "yes" and not cooling:
        notes.append(
            "Your air conditioning was left out of this fit: this period needed "
            "no cooling. A summer month will show it."
        )
    if desc.heating in ("heat_pump", "electric") and not heating:
        notes.append(
            "Your heating was left out of this fit: this period needed no "
            "heating. A winter month will show it."
        )
    twin = build_twin(desc, backend=BACKEND, with_heating=heating, with_cooling=cooling)
    try:
        result = calibrate(twin, data, given=_given(desc))
    except NotEnoughData as exc:
        return {"ok": False, "message": str(exc)}
    tz = ZoneInfo(desc.timezone)
    stamps = data.timestamps()
    gas_report = _gas_report(desc, result, data, gas_used)
    heat = _heating_report(desc, result, data)
    chosen = periods if period == "all" else [periods[int(period)]]
    by_period = []
    for (i, j, _), p in zip(data.spans, chosen, strict=True):
        days: dict[str, list[float]] = {}
        for k in range(i, j):
            key = f"{datetime.fromtimestamp(int(stamps[k]), tz):%Y-%m-%d}"
            m, pr = result.measured_kwh[k], result.predicted_kwh[k]
            acc = days.setdefault(key, [0.0, 0.0])
            if np.isfinite(m):
                acc[0] += float(m)
                acc[1] += float(pr)
        bill_rows = [
            r for r in (gas_report or {}).get("bills", []) if p.start <= r["t0"] < p.end
        ]
        by_period.append(
            {
                "label": _period_label(p, desc.timezone),
                "days": round(p.days, 1),
                "mean_c": round(float(np.mean(data.outdoor_c[i:j])), 1),
                "electricity_kwh": round(float(np.nansum(result.measured_kwh[i:j])), 0),
                "twin_electricity_kwh": round(
                    float(np.nansum(result.predicted_kwh[i:j])), 0
                ),
                "gas_bill_kwh": (
                    float(sum(r["bill_kwh"] for r in bill_rows)) if bill_rows else None
                ),
                "twin_gas_kwh": (
                    float(sum(r["twin_kwh"] for r in bill_rows)) if bill_rows else None
                ),
                "daily": [
                    {"day": d, "measured": round(v[0], 3), "twin": round(v[1], 3)}
                    for d, v in days.items()
                ],
                "indoor": _indoor_week(result, stamps, i, j, tz),
                "heating_running": (
                    round(float(np.mean(heat["duty"][i:j])), 3) if heat else None
                ),
                "heating_calls_hours_a_day": (
                    round(24 * float(np.mean(heat["on"][i:j])), 1) if heat else None
                ),
            }
        )
    return {
        "ok": True,
        "verdict": result.verdict,
        "headline": result.headline,
        "notes": notes,
        "example": example.get("message") if example.get("changed") else None,
        "heating": heat["sentences"] if heat else [],
        "indoor_error": (
            round(result.indoor_error, 2) if np.isfinite(result.indoor_error) else None
        ),
        "gas": gas_report,
        "water": _water_report(desc, data),
        "findings": [
            {
                "label": f.label,
                "sentence": f.sentence,
                "verdict": f.verdict,
                "reason": f.reason,
                "value": round(f.value, 3) if f.measured else None,
                "unit": f.unit,
                "uncertainty": (
                    round(f.uncertainty, 4)
                    if f.uncertainty is not None and np.isfinite(f.uncertainty)
                    else None
                ),
            }
            for f in result.findings
        ],
        "hourly_error": result.hourly_error,
        "bias": result.bias,
        "period": "; ".join(
            f"{data.hour_label(i)[:10]} to {data.hour_label(j - 1)[:10]}"
            for i, j, _ in data.spans
        ),
        "periods": by_period,
        "chosen": period,
        "daily": [d for p in by_period for d in p["daily"]],
        "seconds": round(time.perf_counter() - t_start, 1),
    }


def _indoor_week(result, stamps, i: int, j: int, tz) -> list[dict[str, Any]] | None:
    """The first week of a period, hour by hour: what the thermometer read and
    what the twin's own thermometer read."""
    measured = result.measured_indoor_c
    if measured.size == 0 or not np.isfinite(measured[i:j]).any():
        return None
    out = []
    for k in range(i, min(j, i + 7 * 24)):
        m, p = measured[k], result.predicted_indoor_c[k]
        out.append(
            {
                "time": f"{datetime.fromtimestamp(int(stamps[k]), tz):%Y-%m-%d %H:%M}",
                "measured": round(float(m), 2) if np.isfinite(m) else None,
                "twin": round(float(p), 2),
            }
        )
    return out


def _heating_report(desc: HomeDescription, result, data) -> dict[str, Any] | None:
    """How the heating ran, from the twin's thermostat (its on/off and how much
    of each hour the machine ran), and what the home loses to the night sky."""
    twin = result.twin
    name = next(
        (
            n[: -len(".duty")]
            for n in twin.model.output_names
            if n.endswith(".thermostat.duty") and n.startswith("heating.")
        ),
        None,
    )
    params = twin.model.parameters
    zone = twin.zone.name
    sentences = []
    ua = params[f"{zone}.envelope.conductance"]
    depression = params.get(f"{zone}.sky.depression")
    if depression:
        rad = ua * depression
        vent = params.get(f"{zone}.ventilation.conductance", 0.0)
        share = rad / ((ua + vent) * 15.0 + rad)
        where = _t("radiates_flat" if desc.home_type == "flat" else "radiates_house")
        sentences.append(_t("radiates", w=_n(rad), where=where, pct=f"{100 * share:.0f}"))
    if name is None:
        return {"sentences": sentences, "duty": None, "on": None} if sentences else None
    meter = HourlyMeter(twin, data, substeps=auto_substeps(data))
    hourly = meter.hourly([f"{name}.duty", f"{name}.on"])
    duty, on = hourly[f"{name}.duty"], hourly[f"{name}.on"]
    machine = _t(f"machine_{desc.heating}")
    sentences.append(
        _t(
            "thermostat_ran",
            hours=f"{24 * float(np.mean(on)):.0f}",
            machine=machine,
            pct=f"{100 * float(np.mean(duty)):.0f}",
            full=_n(24 * float(np.mean(duty)), 1),
        )
    )
    return {"sentences": sentences, "duty": duty, "on": on}


_GAS_USES = (("heating", "heating"), ("water_heater", "hot water"), ("hob", "cooking"))


def _gas_report(
    desc: HomeDescription, result, data, gas_used: bool
) -> dict[str, Any] | None:
    """The gas bill against the twin, in m³ and kWh at the bill's own conversion."""
    twin = result.twin
    if not twin.gas_outputs:
        return None
    tz = desc.timezone
    meter = HourlyMeter(twin, data, substeps=auto_substeps(data))  # as the fit did
    hourly = meter.hourly(twin.gas_outputs)
    by_use = {
        label: sum(v.sum() for k, v in hourly.items() if k.startswith(f"{name}."))
        / 1000.0
        for name, label in _GAS_USES
    }
    total_twin = sum(by_use.values())
    bills = [b for b in _bills("gas") if _bill_in(data, b) and b.kwh is not None]
    lines: list[str] = []
    rows = []
    for b in bills:
        h0 = _hour_index(data, b.start)
        h1 = h0 + (b.end - b.start) // 3600
        twin_kwh = sum(v[h0:h1].sum() for v in hourly.values()) / 1000.0
        f = b.kwh_per_m3 or 0.0
        twin_m3 = twin_kwh / f if f else float("nan")
        off = (twin_kwh - b.kwh) / max(b.kwh, 1.0)  # type: ignore[operator]
        rows.append(
            {
                "period": _period(b, tz),
                "t0": b.start,
                "bill_m3": round(b.m3, 1),
                "bill_kwh": round(b.kwh, 0),  # type: ignore[arg-type]
                "kwh_per_m3": round(f, 3),
                "twin_kwh": float(round(twin_kwh, 0)),
                "twin_m3": float(round(twin_m3, 1)),
                "off": round(off, 4),
            }
        )
        if len(bills) > 1:  # the table carries the detail; one line each
            lines.append(
                _t(
                    "gas_line_many",
                    period=_period(b, tz),
                    m3=_n(b.m3),
                    kwh=_n(b.kwh),
                    factor=_n(f, 2),
                    twin_kwh=_n(twin_kwh),
                    twin_m3=_n(twin_m3),
                )
            )
            continue
        lines.append(
            _t(
                "gas_bill_one",
                period=_period(b, tz),
                m3=_n(b.m3),
                kwh=_n(b.kwh),
                factor=_n(f, 2),
            )
        )
        close = abs(off) < 0.02
        pct = f"{abs(100 * off):.0f}"
        how = (
            _t("almost_exactly")
            if close
            else _t("pct_more" if off > 0 else "pct_less", pct=pct)
        )
        lines.append(
            _t("gas_twin_one", kwh=_n(twin_kwh), m3=_n(twin_m3), how=how)
            + (_t("what_you_were_billed") if close else _t("than_the_bill"))
            + (_t("by_design") if gas_used else "")
        )
    if gas_used and len(bills) > 1:
        agree = max(abs(r["off"]) for r in rows) < 0.05
        lines.append(_t("gas_many_agree" if agree else "gas_many_disagree", n=len(bills)))
    if not bills:
        lines.append(_t("gas_no_bill", kwh=_n(total_twin), m3=_n(total_twin / 10.7)))
    elif not gas_used:
        lines.append(_t("gas_not_fitted"))
    shares = (
        [
            f"{_t('use_' + label)} {100 * v / total_twin:.0f} %"
            for label, v in by_use.items()
            if v > 0
        ]
        if total_twin > 0
        else []
    )
    if len(shares) > 1:
        lines.append(_t("gas_shares", shares=", ".join(shares)))
    return {
        "sentences": lines,
        "bills": rows,
        "used_in_fit": gas_used,
        "twin_kwh": round(total_twin, 0),
        "by_use_kwh": {k: round(v, 1) for k, v in by_use.items() if v > 0},
    }


def _water_report(desc: HomeDescription, data) -> dict[str, Any] | None:
    """The water bill against a typical household of the same size."""
    bills = _bills("water")
    if not bills:
        return None
    spans = _utc_spans(data)
    near = [b for b in bills if any(b.start < t1 and b.end > t0 for t0, t1 in spans)]
    near = near or bills[-1:]
    m3 = sum(b.m3 for b in near)
    days = sum(b.days for b in near)
    per_day = 1000.0 * m3 / days
    people = desc.people_count
    each = per_day / people
    typical = TYPICAL_WATER_L_PER_PERSON
    tz = desc.timezone
    when = (
        _t("water_one", period=_period(near[0], tz))
        if len(near) == 1
        else _t("water_many", periods="; ".join(_period(b, tz) for b in near))
    )
    ratio = each / typical - 1.0
    if abs(ratio) < 0.1:
        compare = _t("water_typical")
    else:
        compare = _t(
            "water_more" if ratio > 0 else "water_less", pct=f"{abs(100 * ratio):.0f}"
        )
    sentences = [
        _t("water_total", when=when, m3=_n(m3), days=f"{days:.0f}", per_day=_n(per_day)),
        (
            _t("water_each", each=_n(each), compare=compare, typical=_n(typical))
            if people > 1
            else _t("water_one_person", compare=compare, typical=_n(typical))
        ),
    ]
    return {
        "sentences": sentences,
        "m3": round(m3, 1),
        "days": round(days, 1),
        "litres_per_day": round(per_day, 0),
        "litres_per_person_day": round(each, 0),
        "typical_litres_per_person_day": typical,
    }


# ---------------------------------------------------------------- "My home"
# The dashboard's calls: what the page shows on its one screen. They return
# structured data and sentences in the session's language (set_language).

#: How well a home keeps the heat, as the energy certificate's letters: the
#: envelope's and the ventilation's conductance per m² of floor, W/K·m².
#: Provisional thresholds (ARCHITECTURE.md, "The grade"): a scale people know, not the
#: official certificate, which the page says.
LETTERS = ((0.8, "A"), (1.2, "B"), (1.7, "C"), (2.3, "D"), (3.0, "E"), (3.8, "F"))
#: Typical all-in prices (energy, standing charges, taxes), € per kWh, used
#: when a bill gives no amount: electricity on a regulated tariff, gas TUR.
PRICES = {"electricity": 0.17, "gas": 0.075, "water": 2.0}  # water: € per m³, all in
#: Envelope area per m² of floor, for "insulate the walls": a flat's facades,
#: a house's walls and roof.
_ENVELOPE_PER_M2 = {"flat": 0.9, "terraced": 2.0, "detached": 3.0}
#: The last analysis, so the page can change language without fitting again.
CACHE: dict[str, Any] = {}


def set_language(lang: str) -> dict[str, Any]:
    """Every sentence from now on in ``lang``: ``"en"`` or ``"es"``."""
    global LANG
    if lang not in ("en", "es"):
        raise ValueError(f"lang must be 'en' or 'es', not {lang!r}")
    LANG = lang
    return {"lang": LANG}


#: The demo homes a householder may start from, inside "My home": the
#: sample set, and a name in each language.
DEMO_HOMES = {
    "gas_winter": {
        "en": "Demo: gas flat in Madrid",
        "es": "Demo: piso con gas en Madrid",
    },
    "electric": {
        "en": "Demo: all-electric flat in Madrid",
        "es": "Demo: piso todo eléctrico en Madrid",
    },
}
_KIND_BY_NAME = (
    ("consumo", "electricity"),
    ("factura_gas", "gas"),
    ("factura_agua", "water"),
    ("termometro", "thermometer"),
    ("meteo", "weather"),
    ("open_meteo", "weather"),
)


def demo_home(key: str) -> dict[str, Any]:
    """A demo home to start from: its answers and its files (bytes, base64),
    each with the kind of data it holds, so the page adds them to a home of
    the householder's like files of their own. The bills are the demo
    home's own, simulated from the same answers, so a model built on them
    is exactly the demo home."""
    import base64

    if key not in DEMO_HOMES:
        raise KeyError(f"no demo home {key!r}; demos: {list(DEMO_HOMES)}")
    label, home, names = SAMPLE_SETS[key]
    answers = json.loads((SAMPLES / home).read_text())
    files = []
    for name in names:
        path = SAMPLES / name
        kind = next((k for word, k in _KIND_BY_NAME if word in path.name), "electricity")
        files.append(
            {
                "name": path.name,
                "kind": kind,
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
            }
        )
    return {"key": key, "name": DEMO_HOMES[key][LANG], "answers": answers, "files": files}


def files(timezone_name: str = "Europe/Madrid") -> dict[str, Any]:
    """Every file in the session, described again (after a language change)."""
    return {"files": [_summary(k, e, timezone_name) for k, e in SESSION.items()]}


def forget() -> dict[str, Any]:
    """Forget every file, the example and the last analysis."""
    SESSION.clear()
    EXAMPLE.clear()
    CACHE.clear()
    return {"ok": True}


def _letter(k_per_m2: float) -> str:
    return next((letter for limit, letter in LETTERS if k_per_m2 <= limit), "G")


def _use_of(output: str) -> str:
    head = output.split(".")[0]
    return {
        "heating": "heating",
        "cooling": "cooling",
        "water_heater": "hot water",
        "hob": "cooking",
        "base": "always_on",
    }.get(head, "appliances")


def _by_use(twin, kwh_by_output: dict[str, float]) -> list[dict[str, Any]]:
    """Energy by use and fuel, largest first."""
    acc: dict[tuple[str, str], float] = {}
    for name, kwh in kwh_by_output.items():
        fuel = "gas" if name in twin.gas_outputs else "electricity"
        key = (_use_of(name), fuel)
        acc[key] = acc.get(key, 0.0) + kwh
    rows = [
        {"use": u, "fuel": f, "kwh": round(v, 1), "label": _t("use_" + u)}
        for (u, f), v in acc.items()
        if v > 0.05
    ]
    return sorted(rows, key=lambda r: -r["kwh"])


#: The model's outputs the drawing of the house is made from: the heat the
#: zone loses to the outside (envelope and ventilation together, radiation to
#: the sky included), the part of it that is radiation, the part that is
#: ventilation, and the heat the heating machine put into the rooms.
_FLOW_OUTPUTS = (
    "zone.heat_loss",
    "zone.radiation_loss",
    "zone.ventilation.heat_flow",
    "heating.heat",
)


def _gain_outputs(twin) -> list[str]:
    """The other heat generated in the rooms: people (present half the time
    on average), appliances, the hob, the always-on load and the water
    heater's standby loss; not the heating."""
    names = []
    for n in twin.model.output_names:
        head, _, tail = n.rpartition(".")
        if (
            tail == "heat"
            and "." not in head
            and head not in ("heating", "water_heater", "zone")
        ):
            names.append(n)
    if "water_heater.standby_loss" in twin.model.output_names:
        names.append("water_heater.standby_loss")
    return names


def _flow_names(twin) -> list[str]:
    return [n for n in _FLOW_OUTPUTS if n in twin.model.output_names] + _gain_outputs(
        twin
    )


def _flows(
    desc: HomeDescription,
    uses: list[dict[str, Any]],
    *,
    kwh: dict[str, float],
    delta_c: float,
    hours: float,
    water_m3: float | None,
    loss_w_per_k: float,
    heater_w: float | None,
    period: dict[str, Any],
    gas_exact: bool = False,
    electricity_exact: bool = False,
    water_eur: float | None = None,
    to_hours: float | None = None,
) -> dict[str, Any]:
    """What flows into the home and out of it, for the drawing of the house.

    In: electricity and gas (kWh, from ``uses``) and water (m³, the bill or
    a typical household of this size). Made: the heat the heating machine
    put into the rooms, and the other heat generated inside (people,
    appliances, cooking, the always-on load, the water heater's standby).
    Out: the heat the zone lost to the outside, as the model itself computed
    it hour by hour (``zone.heat_loss``: transmission through the fabric,
    radiation to the sky and ventilation), split into the fabric (radiation
    included) and the air. In ISO 13790's terms the loss is Q_ht, the heat
    made is Q_H,nd and the other heat is Q_gn: Q_ht = Q_H,nd + η·Q_gn, so the
    loss is what leaves, not what was used to heat the home. ``kwh`` holds
    the energy of each output in :data:`_FLOW_OUTPUTS` and of the gains,
    over ``hours``; ``to_hours`` rescales every amount to that many hours
    (a month of 30.4 days, say).
    """
    factor = 1.0 if to_hours is None else to_hours / max(hours, 1.0)
    span = hours * factor
    loss = kwh.get("zone.heat_loss", 0.0) * factor
    air = kwh.get("zone.ventilation.heat_flow", 0.0) * factor
    radiation = kwh.get("zone.radiation_loss", 0.0) * factor
    heat = kwh["heating.heat"] * factor if "heating.heat" in kwh else None
    gains = sum(v for n, v in kwh.items() if n not in _FLOW_OUTPUTS) * factor
    if water_m3 is None:
        water = TYPICAL_WATER_L_PER_PERSON * desc.people_count * span / 24.0 / 1000.0
        water_typical = True
    else:
        water, water_typical = water_m3 * factor, False
    by_use = [
        {
            **r,
            "kwh": round(r["kwh"] * factor, 1),
            "eur": round(r.get("eur", 0.0) * factor),
        }
        for r in uses
    ]
    # what the drawing shows: the energy spent on conditioning the rooms
    # (heating in winter, cooling in summer), by fuel; the rest by fuel
    conditioning = [
        {"kind": r["use"], "fuel": r["fuel"], "kwh": round(r["kwh"]), "eur": r["eur"]}
        for r in by_use
        if r["use"] in ("heating", "cooling")
    ]
    by_fuel = {
        fuel: [r for r in by_use if r["fuel"] == fuel]
        for fuel in ("electricity", "gas")
        if any(r["fuel"] == fuel for r in by_use)
    }
    water_cost = water * PRICES["water"] if water_eur is None else water_eur * factor
    bill = {
        "electricity": {
            "kwh": round(sum(r["kwh"] for r in by_fuel.get("electricity", []))),
            "eur": round(sum(r["eur"] for r in by_fuel.get("electricity", []))),
            "exact": electricity_exact,
        },
        "gas": {
            "kwh": round(sum(r["kwh"] for r in by_fuel["gas"])),
            "eur": round(sum(r["eur"] for r in by_fuel["gas"])),
            "exact": gas_exact,
        }
        if "gas" in by_fuel
        else None,
        "water": {
            "m3": round(water, 1),
            "eur": round(water_cost),
            "exact": water_eur is not None,
        },
    }
    bill["total_eur"] = sum(
        part["eur"] for part in bill.values() if isinstance(part, dict)
    )
    return {
        "period": period,
        "conditioning": conditioning,
        "by_fuel": by_fuel,
        "bill": bill,
        "hours": round(span),
        "electricity_kwh": round(
            sum(r["kwh"] for r in by_use if r["fuel"] == "electricity")
        ),
        "gas_kwh": round(sum(r["kwh"] for r in by_use if r["fuel"] == "gas")),
        "water_m3": round(water, 1),
        "water_typical": water_typical,
        "heat_kwh": None if heat is None else round(heat),
        "gains_kwh": round(gains),
        "loss_kwh": round(loss),
        "loss_fabric_kwh": round(loss - air),
        "loss_radiation_kwh": round(radiation),
        "loss_air_kwh": round(air),
        # the loss as a rate: the conductance to the outside (fabric and air,
        # W per °C) and the mean power over the period
        "loss_w_per_k": round(loss_w_per_k),
        "loss_kw": round(loss / max(span, 1.0), 2),
        "heater_kw": None if heater_w is None else round(heater_w / 1000.0, 1),
        "heater_given": desc.heating_kw is not None,
        "delta_c": round(delta_c, 1),
        "heater": desc.heating,
        "water_heater": desc.water,
        "cooking": desc.cooking,
        "by_use": by_use,
    }


def _header(desc: HomeDescription) -> str:
    province = next(p.label for p in PROVINCES if p.value == desc.province)
    return " · ".join(
        [
            province,
            _t(f"kind_{desc.home_type}"),
            f"{desc.area:.0f} m²",
            _t(f"heat_{desc.heating}"),
        ]
    )


def _estimate(desc: HomeDescription) -> dict[str, Any]:
    """A typical January of a home like this, from the answers alone."""
    from calibration import winter_weather

    p = next(p for p in PROVINCES if p.value == desc.province)
    twin = build_twin(desc, backend=BACKEND)
    zone = ZoneInfo(desc.timezone)
    start = datetime(2026, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    spin, hours, sub = 7 * 24, 31 * 24, 4
    t = np.arange((spin + hours) * sub + 1) * (3600.0 / sub)
    weather = winter_weather(mean_c=p.january_c, seed=0)
    outdoor = 273.15 + weather(t - spin * 3600.0)
    flow_names = _flow_names(twin)
    run = twin.simulate(
        t,
        start=start - timedelta(hours=spin),
        outdoor=outdoor,
        track=flow_names,
    )
    window = (spin * 3600.0, float(t[-1]))
    kwh = {
        n: run.energy_j(n, between=window) / 3.6e6
        for n in list(twin.electric_outputs) + list(twin.gas_outputs)
    }
    uses = _by_use(twin, kwh)
    for r in uses:
        r["eur"] = round(r["kwh"] * PRICES[r["fuel"]], 0)
    total = sum(r["eur"] for r in uses)
    heating = sum(r["eur"] for r in uses if r["use"] == "heating")
    inside = t >= window[0]
    flows = _flows(
        desc,
        uses,
        kwh={n: run.energy_j(n, between=window) / 3.6e6 for n in flow_names},
        delta_c=float(np.mean(run.indoor_temperature[inside] - outdoor[inside])),
        hours=hours,
        water_m3=None,
        loss_w_per_k=desc.envelope_ua + desc.ventilation_ua,
        heater_w=twin.model.parameters.get("heating.thermostat.power"),
        period={
            "label": MONTHS[LANG][0],
            "periods": 1,
            "outdoor_c": round(p.january_c, 1),
            "indoor_c": round(float(np.mean(run.indoor_temperature[inside])) - 273.15, 1),
            "typical": True,
        },
    )
    return {
        "flows": flows,
        "month": MONTHS[LANG][0],
        "january_c": p.january_c,
        "province": p.label,
        "eur": round(total, 0),
        "heating_share": round(heating / total, 3) if total else 0.0,
        "by_use": uses,
        "electricity_kwh": round(
            sum(r["kwh"] for r in uses if r["fuel"] == "electricity"), 0
        ),
        "gas_kwh": round(sum(r["kwh"] for r in uses if r["fuel"] == "gas"), 0),
    }


def home(answers: dict[str, Any]) -> dict[str, Any]:
    """The home as described: its one-line header, the summary, a typical
    letter for its age and kind, and a first estimate before any data."""
    try:
        desc = HomeDescription.from_answers(answers)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}
    k = (desc.envelope_ua + desc.ventilation_ua) / desc.area
    return {
        "ok": True,
        "header": _header(desc),
        "summary": [{"topic": a, "text": b} for a, b in home_summary(desc, LANG)],
        "typical_letter": _letter(k),
        "uses_gas": desc.uses_gas,
        "estimate": _estimate(desc),
    }


# ------------------------------------------------------------ the cards


def _kind_of(e: FileEntry) -> str:
    if e.status != "ok":
        return "other"
    qs = {s.quantity for s in e.series}
    for kind, names in (
        ("electricity", {"electricity_import", "electricity_billed"}),
        ("gas", {"gas_volume", "gas_energy"}),
        ("water", {"water_volume"}),
        ("thermometer", {"indoor_temperature"}),
        ("weather", {"outdoor_temperature"}),
    ):
        if qs & names:
            return kind
    return "other"


def cards(answers: dict[str, Any], timezone_name: str | None = None) -> dict[str, Any]:
    """The five data cards, what each holds, and the next best step."""
    desc = HomeDescription.from_answers(answers)
    tz = timezone_name or desc.timezone
    by_kind: dict[str, list] = {
        k: [] for k in ("electricity", "gas", "water", "thermometer", "weather", "other")
    }
    for fid, e in SESSION.items():
        by_kind[_kind_of(e)].append(_summary(fid, e, tz))
    elec, weather, indoor = _best_electricity(), _best_weather(), _best_indoor()
    blocks_e = _runs(elec.start, 24 * 3600) if elec is not None else []

    def span(a: int, b: int) -> str:
        return f"{_date(a, tz)} – {_date(b - 1, tz)}"

    out = []
    # electricity
    lines, status = [], "empty"
    if elec is not None:
        status = "ready"
        for a, b in blocks_e:
            sel = (elec.start >= a) & (elec.start < b)
            amount = f"{_n(elec.values_in('kWh')[sel].sum())} kWh"
            lines.append(_t("card_period", period=span(a, b), amount=amount))
        days = sum(b - a for a, b in blocks_e) / 86400
        if days < MIN_DAYS:
            status = "problem"
            lines.append(_t("card_days_short", days=f"{days:.0f}", need=MIN_DAYS))
    out.append({"kind": "electricity", "status": status, "lines": lines})
    # gas
    gas_bills = _bills("gas")
    lines = [
        _t("card_bill_kwh", period=_period(b, tz), m3=_n(b.m3), kwh=_n(b.kwh))
        if b.kwh is not None
        else _t("card_bill", period=_period(b, tz), m3=_n(b.m3))
        for b in gas_bills
    ]
    status = "ready" if gas_bills else ("empty" if desc.uses_gas else "not_needed")
    out.append({"kind": "gas", "status": status, "lines": lines})
    # water
    water = _bills("water")
    lines = [_t("card_bill", period=_period(b, tz), m3=_n(b.m3)) for b in water]
    out.append({"kind": "water", "status": "ready" if water else "empty", "lines": lines})
    # thermometer
    lines = []
    if indoor is not None:
        for a, b in _runs(indoor.start - indoor.start % 3600, 24 * 3600):
            sel = (indoor.start >= a) & (indoor.start < b)
            v = indoor.values_in("degC")[sel]
            lines.append(
                _t(
                    "card_thermo",
                    period=span(a, b),
                    lo=f"{v.min():.0f}",
                    hi=f"{v.max():.0f}",
                )
            )
    out.append(
        {
            "kind": "thermometer",
            "status": "ready" if indoor is not None else "empty",
            "lines": lines,
        }
    )
    # weather: automatic
    lines, status, request = [], "waiting", None
    covered = False
    if weather is not None:
        w_runs = _runs(np.ceil(weather.start / 3600.0) * 3600, 4 * 3600)
        lines = [_t("card_weather_files", period=span(a, b)) for a, b in w_runs]
        covered = bool(blocks_e) and all(
            any(wa <= a and b <= wb for wa, wb in w_runs) for a, b in blocks_e
        )
        status = "ready"
    if elec is not None and not covered:
        status, request = "needs_ok", _weather_request(desc, elec)
    out.append({"kind": "weather", "status": status, "lines": lines, "request": request})
    for c in out:
        c["files"] = by_kind[c["kind"]]
    # can we analyse? and on which periods?
    ready, periods_info, problem = False, [], None
    try:
        data, _, w, periods, _ = _record(desc)
        if data is not None:
            ready = True
            periods_info = _periods_info(periods, w, tz)
    except (NotEnoughData, ValueError) as exc:
        problem = str(exc)
    return {
        "cards": out,
        "other": by_kind["other"],
        "ready": ready,
        "problem": problem,
        "periods": periods_info,
        "next": _next_step(desc, out, periods_info),
        "warnings": _plausibility(desc, elec),
        "example": EXAMPLE.get("key"),
    }


#: The first estimate by answers, kept so the cards can compare the bills
#: with it without simulating again each time.
_ESTIMATE_CACHE: dict[tuple, dict[str, Any]] = {}


def _typical_per_day(desc: HomeDescription) -> dict[str, float]:
    """A typical January's kWh a day by fuel, for a home as described."""
    key = (_answers_key(desc), LANG)
    if key not in _ESTIMATE_CACHE:
        _ESTIMATE_CACHE.clear()
        _ESTIMATE_CACHE[key] = _estimate(desc)
    est = _ESTIMATE_CACHE[key]
    return {
        "electricity": est["electricity_kwh"] / 31.0,
        "gas": est["gas_kwh"] / 31.0,
    }


def _plausibility(desc: HomeDescription, elec) -> list[dict[str, Any]]:
    """Do the bills look like this home's? A gas bill or an electricity record
    far from what a home as described would use (less than a third, or
    more than three times, a typical January's) is most likely another
    home's bill, or the answers do not describe this home. A warning the
    page shows before anyone trusts a fit on them."""
    typical = _typical_per_day(desc)
    warnings = []
    gas_bills = _bills("gas")
    if gas_bills and typical["gas"] > 0:
        kwh = sum(b.kwh for b in gas_bills if b.kwh is not None)
        days = sum(b.days for b in gas_bills if b.kwh is not None)
        if days > 0:
            per_day = kwh / days
            if per_day > 3.0 * typical["gas"] or per_day < typical["gas"] / 3.0:
                warnings.append(
                    {
                        "kind": "gas",
                        "text": _t(
                            "gas_implausible",
                            bill=_n(per_day, 1),
                            typical=_n(typical["gas"], 1),
                        ),
                    }
                )
    elif gas_bills and typical["gas"] == 0:
        warnings.append({"kind": "gas", "text": _t("gas_but_no_gas")})
    if elec is not None and len(elec):
        days = (int(elec.end[-1]) - int(elec.start[0])) / 86400.0
        if days >= 7:
            per_day = float(elec.values_in("kWh").sum()) / days
            if (
                per_day > 3.0 * typical["electricity"]
                or per_day < typical["electricity"] / 3.0
            ):
                warnings.append(
                    {
                        "kind": "electricity",
                        "text": _t(
                            "elec_implausible",
                            record=_n(per_day, 1),
                            typical=_n(typical["electricity"], 1),
                        ),
                    }
                )
    return warnings


def _next_step(desc: HomeDescription, out: list[dict], periods: list) -> str:
    """The one thing that would help most now (a key the page words)."""
    st = {c["kind"]: c["status"] for c in out}
    if st["electricity"] == "empty":
        return "add_electricity"
    if st["electricity"] == "problem":
        return "more_electricity"
    if st["weather"] == "needs_ok":
        return "allow_weather"
    if desc.heating == "gas" and st["gas"] == "empty":
        return "add_gas_heating"
    if st["gas"] == "empty":
        return "add_gas"
    if st["thermometer"] == "empty":
        return "add_thermometer"
    if len(periods) < 2:
        return "add_month"
    if st["water"] == "empty":
        return "add_water"
    return "explore"


# ------------------------------------------------------------ the analysis


#: Fitted parameters whose uncertainty widens or narrows the energy the home
#: uses: the conductances (more loss, more heating) and the always-on load.
#: Moving them together by their own uncertainty, up and then down, gives the
#: band the page draws around the twin: not a full statistical interval, but
#: what the fit itself says it may be off by.
_BAND_ROLES = (".envelope.conductance", ".ventilation.conductance", "base.power")
_DEFAULT_UNCERTAINTY = 0.10


def _band_overrides(
    values: dict[str, float], uncertainty: dict[str, float], sign: float
) -> dict[str, float]:
    out = {}
    for name, v in values.items():
        if any(name.endswith(r) or name == r for r in _BAND_ROLES):
            u = uncertainty.get(name)
            u = (
                _DEFAULT_UNCERTAINTY
                if u is None or not np.isfinite(u)
                else min(float(u), 0.5)
            )
            out[name] = float(v) * (1.0 + sign * u)
    return out


def _hourly_band(result, data) -> tuple[np.ndarray, np.ndarray] | None:
    """The twin's hourly electricity with its measured parameters moved by
    their uncertainty, both ways: ``(low, high)`` kWh per hour."""
    try:
        runs = []
        for sign in (-1.0, 1.0):
            twin = replace(
                result.twin,
                model=result.twin.model.with_parameters(
                    _band_overrides(result.values, result.uncertainty, sign)
                ),
            )
            meter = HourlyMeter(twin, data, substeps=auto_substeps(data))
            elec, _, _ = meter.readings()
            runs.append(np.asarray(elec, dtype=float))
        lo = np.minimum(runs[0], runs[1])
        hi = np.maximum(runs[0], runs[1])
        return lo, hi
    except Exception:  # noqa: BLE001  (a band is an extra; the fit stands without it)
        return None


def analyse(answers: dict[str, Any]) -> dict[str, Any]:
    """Get to know the home from everything in the session; the dashboard."""
    t_start = time.perf_counter()
    desc = HomeDescription.from_answers(answers)
    example = prepare_example(answers)
    try:
        data, _, weather, periods, gas_used = _record(desc, "all")
    except (NotEnoughData, ValueError) as exc:
        return {"ok": False, "message": str(exc)}
    if data is None:
        return {"ok": False, "message": "no data"}
    mean_out = float(np.mean(data.outdoor_c))
    twin = build_twin(
        desc, backend=BACKEND, with_heating=mean_out < 18.0, with_cooling=mean_out >= 18.0
    )
    try:
        result = calibrate(twin, data, given=_given(desc))
    except NotEnoughData as exc:
        return {"ok": False, "message": str(exc)}
    CACHE.clear()
    CACHE.update(
        desc=desc,
        result=result,
        data=data,
        gas_used=gas_used,
        periods=periods,
        example_changed=bool(example.get("changed")),
        whatif=_what_ifs(desc, result, data),
        trust=None,
        band=_hourly_band(result, data),
        seconds=round(time.perf_counter() - t_start, 1),
    )
    return report()


def _tariff(data) -> Tariff:
    from scenarios import ElectricityTariff, GasTariff, Tariff

    elec = ElectricityTariff(
        "typical",
        0.15,
        power_kw=4.6,
        power_eur_per_kw_day=0.0885,
        meter_eur_per_day=0.0266,
    )
    gas = GasTariff("TUR", 0.058, fixed_eur_per_day=0.17)
    return Tariff(elec, gas)


def _what_ifs(desc: HomeDescription, result, data) -> list[dict[str, Any]]:
    """The household's levers, worked out on the last period, in € a month."""
    from scenarios import Insulation, OutdoorShift, ScenarioStudy, SetpointChange

    last = data.period(len(data.spans) - 1) if data.periods else data
    try:
        study = ScenarioStudy.from_calibration(result, last, _tariff(last))
    except ValueError:
        return []
    heats = any(n.startswith("heating.") for n in result.twin.model.output_names)
    area = _ENVELOPE_PER_M2[desc.home_type] * desc.area
    levers: list[tuple[str, object]] = []
    if heats:
        levers += [
            ("thermostat_down", SetpointChange(-1.0)),
            ("thermostat_up", SetpointChange(1.0)),
        ]
    levers += [
        # only the opaque part takes insulation: windows and doors are about
        # 40 % of a Spanish envelope's loss
        ("insulate", Insulation(r_value=2.0, area_m2=0.6 * area, envelope_area_m2=area)),
        ("colder", OutdoorShift(-2.0)),
    ]
    days = last.hours / 24.0
    out = []
    for key, scenario in levers:
        try:
            r = study.run(scenario)
        except (ValueError, KeyError):
            continue
        base, new = r.baseline.total_eur, r.outcome.total_eur
        out.append(
            {
                "key": key,
                "eur_before": round(base, 2),
                "eur_after": round(new, 2),
                "eur_month_change": round((new - base) / days * 30.4, 1),
                "gas_kwh_change": round(
                    sum(m.gas_kwh for m in r.outcome.months)
                    - sum(m.gas_kwh for m in r.baseline.months),
                    0,
                ),
                "electricity_kwh_change": round(
                    r.outcome.electricity_kwh - r.baseline.electricity_kwh, 0
                ),
                "t0": int(last.start.timestamp()),
                "t1": int(last.start.timestamp()) + 3600 * last.hours,
            }
        )
    return out


def _sources(result) -> str:
    parts = []
    if np.isfinite(result.hourly_error):
        parts.append(_t("src_electricity"))
    n = result.measured_bills_kwh.size
    if n:
        parts.append(_t("src_bill") if n == 1 else _t("src_bills"))
    if np.isfinite(result.indoor_error):
        parts.append(_t("src_indoor"))
    return _list(parts)


def _list(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {_t('and')} " + items[-1]


_REASONS = (
    ("runs on gas, so the electricity meter", "r_gas_no_bills"),
    ("not how quickly your home warms up", "r_bills_storage"),
    ("not the peaks that would show", "r_bills_size"),
    ("the twin has no heating or cooling", "r_no_heating"),
    ("no hourly electricity was given", "r_no_electricity"),
    ("never ran at full power", "r_full_power"),
    ("shows only when the indoor temperature changes", "r_no_storage"),
    ("different parts of it point to different values", "r_unstable"),
    ("does not pin this down", "r_not_pinned"),
)


def _reason(text: str) -> str:
    low = text.lower()
    for needle, key in _REASONS:
        if needle in low:
            return _t(key)
    return text


def _findings(result, desc: HomeDescription) -> list[dict[str, Any]]:
    """Every finding in plain words, in the session's language."""
    machine = _t(f"machine_{desc.heating}") if desc.heating != "none" else ""
    params = result.twin.model.parameters
    zone = result.twin.zone.name
    vent = params.get(f"{zone}.ventilation.conductance", 0.0)
    out = []
    for f in result.findings:
        u = f.uncertainty
        if f.key == "thermometer.offset":
            pm = (
                f" (±{_n(max(u or 0.05, 0.05), 1)} °C)"
                if u is not None and np.isfinite(u)
                else ""
            )
        else:
            pm = (
                f" (±{max(round(100 * u), 1)} %)"
                if u is not None and np.isfinite(u) and u <= 1.0
                else ""
            )
        if f.key.endswith(".envelope.conductance"):
            label = _t("label_heat_loss")
            text = _t(
                "f_heat_loss",
                w=_n(f.value),
                pm=pm,
                kw=_n((f.value + vent) * 15 / 1000, 1),
            )
        elif f.key.endswith(".air.capacity"):
            label = _t("label_keeps_warm")
            text = _t("f_keeps_warm", hours=_n(f.value), pm=pm)
        elif f.key.endswith(".thermostat.power"):
            cool = f.key.startswith("cooling.")
            label = _t("label_cooler") if cool else _t("label_machine", machine=machine)
            text = (
                _t("f_machine_cool", kw=_n(f.value, 1), pm=pm)
                if cool
                else _t("f_machine", machine=machine, kw=_n(f.value, 1), pm=pm)
            )
        elif f.key.endswith(".power"):  # the always-on load
            label = _t("label_base")
            text = _t("f_base", w=_n(f.value), pm=pm, kwh=_n(f.value * 24 * 30 / 1000))
        elif f.key == "thermometer.offset":
            label = _t("label_thermo")
            text = (
                _t("f_thermo_ok", pm=pm)
                if abs(f.value) < 0.05
                else _t(
                    "f_thermo_off",
                    k=_n(abs(f.value), 1),
                    where=_t("warmer" if f.value > 0 else "cooler"),
                    pm=pm,
                )
            )
        else:
            label, text = f.label, f.sentence
        if not f.measured:
            text = _t("not_measured")
        out.append(
            {
                "key": f.key,
                "label": label,
                "text": text,
                "verdict": f.verdict,
                "counted": f.counted,
                "reason": _reason(f.reason) if f.reason else "",
                "value": round(f.value, 3) if f.measured else None,
                "uncertainty": round(u, 4) if u is not None and np.isfinite(u) else None,
            }
        )
    return out


def _confidence(result, findings: list[dict[str, Any]]) -> tuple[str, str]:
    code = {"good": "reliable", "usable": "approximate"}.get(result.verdict, "more_data")
    sources = _sources(result) or _t("nothing_yet")
    if result.headline.startswith("Not enough data: the twin does not yet reproduce"):
        what = (
            _t("src_bills") if "gas bills" in result.headline else _t("src_electricity")
        )
        return "more_data", _t("conf_mismatch", what=what)
    counted = [f for f in findings if f["counted"]]
    good = [f["label"].lower() for f in counted if f["verdict"] == "good"]
    rough = [f["label"].lower() for f in counted if f["verdict"] == "usable"]
    poor = [f["label"].lower() for f in counted if f["verdict"] == "not enough data"]
    if code == "reliable":
        return code, _t("conf_reliable", sources=sources)
    if code == "approximate":
        return code, _t(
            "conf_approximate",
            sources=sources,
            good=_list(good) or _t("nothing_yet"),
            rough=_list(rough),
        )
    return code, _t("conf_more", poor=_list(poor) or _t("nothing_yet"), sources=sources)


class _AdoptedFit:
    """A fit taken as given (a demo home's, baked at build time): what the
    forecast needs of a calibration, without fitting."""

    def __init__(
        self, twin, values: dict[str, float], given: dict[str, float], uncertainty=None
    ) -> None:
        self.twin = twin
        self.values = dict(values)
        self.given = dict(given)
        self.uncertainty = dict(uncertainty or {})


def adopt_fit(answers: dict[str, Any], fit: dict[str, Any]) -> dict[str, Any]:
    """Take a fit as given: ``fit`` has ``values`` and ``given`` (parameters
    by name) and ``periods`` (``[[start, end], ...]``, UTC seconds). The
    forecast can then run on it as if it had just been fitted here."""
    desc = HomeDescription.from_answers(answers)
    twin = build_twin(desc, backend=BACKEND, with_cooling=False)
    params = twin.model.parameters
    values = {k: float(v) for k, v in fit.get("values", {}).items() if k in params}
    given = {k: float(v) for k, v in fit.get("given", {}).items() if k in params}
    twin.model.set_parameters({**values, **given})
    CACHE.clear()
    CACHE.update(
        desc=desc,
        result=_AdoptedFit(twin, values, given, fit.get("uncertainty")),
        data=None,
        gas_used=False,
        periods=[Period(int(a), int(b)) for a, b in fit.get("periods", [])],
        example_changed=False,
        whatif=[],
        trust=None,
        seconds=0.0,
        adopted=True,
    )
    return {"ok": True, "parameters": len(values) + len(given)}


def fit_summary() -> dict[str, Any]:
    """The last fit's parameters and periods, to bake beside a demo's report."""
    if not CACHE:
        return {}
    r = CACHE["result"]
    return {
        "values": {k: float(v) for k, v in r.values.items()},
        "given": {k: float(v) for k, v in r.given.items()},
        "uncertainty": {
            k: float(v)
            for k, v in getattr(r, "uncertainty", {}).items()
            if np.isfinite(v)
        },
        "periods": [[p.start, p.end] for p in CACHE["periods"]],
    }


def report() -> dict[str, Any]:
    """The dashboard from the last analysis, in the session's language (no
    fitting: changing the language is instant)."""
    if not CACHE:
        return {"ok": False, "message": "no analysis yet"}
    desc, result, data = CACHE["desc"], CACHE["result"], CACHE["data"]
    tz = ZoneInfo(desc.timezone)
    twin = result.twin
    params = twin.model.parameters
    zone = twin.zone.name
    k = (
        params[f"{zone}.envelope.conductance"]
        + params.get(f"{zone}.ventilation.conductance", 0.0)
    ) / desc.area
    findings = _findings(result, desc)
    code, conf_text = _confidence(result, findings)
    # energy by use, over everything analysed
    meter = HourlyMeter(twin, data, substeps=auto_substeps(data))
    outs = list(twin.electric_outputs) + list(twin.gas_outputs)
    flow_names = _flow_names(twin)
    hourly = meter.hourly(outs + flow_names)
    uses = _by_use(twin, {n: float(hourly[n].sum()) / 1000.0 for n in outs})
    gas_bills = [b for b in _bills("gas") if _bill_in(data, b)]
    gas_price = PRICES["gas"]
    amounts = _gas_amounts(gas_bills)
    if amounts:
        gas_price = amounts[0] / max(amounts[1], 1.0)
    elec_price = PRICES["electricity"]
    elec_amounts = _electricity_amounts(data)
    if elec_amounts:
        elec_price = elec_amounts[0] / max(elec_amounts[1], 1.0)
    for r in uses:
        r["eur"] = round(r["kwh"] * (gas_price if r["fuel"] == "gas" else elec_price), 0)
    total = sum(r["eur"] for r in uses)
    days = data.hours / 24.0
    heat = _heating_report(desc, result, data)
    gas_report = _gas_report(desc, result, data, CACHE["gas_used"])
    water_report = _water_report(desc, data)
    water_bills = [b for b in _bills("water") if _bill_in(data, b)] or _bills("water")[
        -1:
    ]
    indoor = (
        result.predicted_indoor_c
        if result.predicted_indoor_c.size == data.outdoor_c.size
        else np.full(data.outdoor_c.shape, desc.setpoint_c - 1.0)
    )
    flows = _flows(
        desc,
        uses,
        kwh={n: float(hourly[n].sum()) / 1000.0 for n in flow_names},
        delta_c=float(np.nanmean(indoor - data.outdoor_c)),
        hours=data.hours,
        water_m3=water_report["m3"] * data.hours / 24.0 / water_report["days"]
        if water_report
        else None,
        loss_w_per_k=params[f"{zone}.envelope.conductance"]
        + params.get(f"{zone}.ventilation.conductance", 0.0),
        heater_w=params.get("heating.thermostat.power"),
        period=_period_summary(CACHE["periods"], desc.timezone, data.outdoor_c, indoor),
        gas_exact=bool(amounts),
        electricity_exact=bool(elec_amounts),
        water_eur=(
            _water_amounts(water_bills) * data.hours / 24.0 / water_report["days"]
            if water_report and _water_amounts(water_bills) is not None
            else None
        ),
        to_hours=30.4 * 24.0,
    )
    stamps = data.timestamps()
    by_period = []
    for (i, j, _), p in zip(data.spans, CACHE["periods"], strict=True):
        rows = [
            r for r in (gas_report or {}).get("bills", []) if p.start <= r["t0"] < p.end
        ]
        by_period.append(
            {
                "label": _period_label(p, desc.timezone),
                "mean_c": round(float(np.mean(data.outdoor_c[i:j])), 1),
                "electricity_kwh": round(float(np.nansum(result.measured_kwh[i:j])), 0),
                "twin_electricity_kwh": round(
                    float(np.nansum(result.predicted_kwh[i:j])), 0
                ),
                "gas_bill_kwh": float(sum(r["bill_kwh"] for r in rows)) if rows else None,
                "twin_gas_kwh": float(sum(r["twin_kwh"] for r in rows)) if rows else None,
                "indoor": _indoor_week(result, stamps, i, j, tz),
                "daily": _daily(result, stamps, i, j, tz),
            }
        )
    keeps = next((f for f in findings if f["key"].endswith(".air.capacity")), None)
    machine = next(
        (
            f
            for f in findings
            if f["key"].endswith(".thermostat.power")
            and not f["key"].startswith("cooling")
        ),
        None,
    )
    if "heating.thermostat.power" in result.given:
        boiler = "given"
    elif machine is None or machine["value"] is None:
        boiler = "unknown"
    elif not machine["counted"]:
        boiler = "bigger_than_needed"
    else:
        boiler = "measured"
    whatif = []
    for w in CACHE["whatif"]:
        change = w["eur_month_change"]
        if abs(change) < 0.5:
            effect = _t("wi_same")
        elif change < 0:
            effect = _t("wi_saves", eur=_n(-change))
        else:
            effect = _t("wi_costs", eur=_n(change))
        title = _t(
            f"wi_{w['key']}",
            roof="" if desc.home_type == "flat" else _t("wi_roof"),
        )
        whatif.append({**w, "title": title, "effect": effect})
    basis = (
        _t(
            "wi_basis",
            period=f"{_date(CACHE['whatif'][0]['t0'], desc.timezone)} {_t('to')} "
            f"{_date(CACHE['whatif'][0]['t1'], desc.timezone)}",
        )
        if CACHE["whatif"]
        else ""
    )
    return {
        "ok": True,
        "letter": _letter(k),
        "k_per_m2": round(k, 2),
        "typical_letter": _letter((desc.envelope_ua + desc.ventilation_ua) / desc.area),
        "confidence": code,
        "confidence_text": conf_text,
        "money": {
            "eur": round(total, 0),
            "days": round(days, 1),
            "eur_per_month": round(total / days * 30.4, 0),
            "by_use": uses,
            "gas_price": round(gas_price, 3),
            "electricity_price": round(elec_price, 3),
            "from_bills": bool(amounts) or bool(elec_amounts),
        },
        "heating_share": round(
            sum(r["eur"] for r in uses if r["use"] == "heating") / total, 3
        )
        if total
        else 0.0,
        "keeps_warm_hours": keeps["value"]
        if keeps and keeps["value"] is not None
        else None,
        "keeps_warm_verdict": keeps["verdict"] if keeps else None,
        "boiler": boiler,
        "boiler_kw": result.given["heating.thermostat.power"] / 1000.0
        if boiler == "given"
        else machine["value"]
        if machine
        else None,
        "heating": heat["sentences"] if heat else [],
        "running": round(float(np.mean(heat["duty"])), 3)
        if heat and heat["duty"] is not None
        else None,
        "findings": findings,
        "gas": gas_report,
        "water": water_report,
        "flows": flows,
        "periods": by_period,
        "whatif": whatif,
        "whatif_basis": basis,
        "trust": _trust_text(),
        "example": (
            _t(
                "example_remade",
                day=desc.thermostat,
                night=_t("night_lower")
                if desc.night == "lower"
                else _t("night_same", day=desc.thermostat),
            )
            if CACHE["example_changed"]
            else None
        ),
        "seconds": CACHE["seconds"],
    }


def _daily(result, stamps, i: int, j: int, tz) -> list[dict[str, Any]]:
    """Electricity day by day over one period: the meter, the model, and the
    model's band (its measured parameters moved by their uncertainty)."""
    band = CACHE.get("band")
    days: dict[str, list[float]] = {}
    for k in range(i, j):
        key = f"{datetime.fromtimestamp(int(stamps[k]), tz):%Y-%m-%d}"
        m, p = result.measured_kwh[k], result.predicted_kwh[k]
        acc = days.setdefault(key, [0.0, 0.0, 0.0, 0.0])
        if np.isfinite(m):
            acc[0] += float(m)
            acc[1] += float(p)
            if band is not None:
                acc[2] += float(band[0][k])
                acc[3] += float(band[1][k])
    return [
        {
            "day": d,
            "measured": round(v[0], 3),
            "twin": round(v[1], 3),
            **({"lo": round(v[2], 3), "hi": round(v[3], 3)} if band is not None else {}),
        }
        for d, v in days.items()
    ]


def _period_summary(periods: list, tz: str, outdoor_c, indoor_c) -> dict[str, Any]:
    """The months analysed, as the drawing labels them ("Dec–Jan"; several
    periods are averaged), with the mean outdoor and indoor temperatures."""
    zone = ZoneInfo(tz)
    first = datetime.fromtimestamp(periods[0].start, zone)
    last = datetime.fromtimestamp(periods[-1].end - 1, zone)
    months = MONTHS[LANG]
    label = (
        months[first.month - 1]
        if (first.year, first.month) == (last.year, last.month)
        else f"{months[first.month - 1]}–{months[last.month - 1]}"
    )
    return {
        "label": label,
        "periods": len(periods),
        "outdoor_c": round(float(np.nanmean(outdoor_c)), 1),
        "indoor_c": round(float(np.nanmean(indoor_c)), 1),
        "typical": False,
    }


def _electricity_amounts(data) -> tuple[float, float] | None:
    """(€, kWh) over the electricity bills that overlap the record, or None."""
    spans = _utc_spans(data)
    eur = kwh = 0.0
    for e in SESSION.values():
        if e.status != "ok" or e.format != "typed_electricity":
            continue
        energy = next(s for s in e.series if s.quantity == "electricity_billed")
        cost = next((s for s in e.series if s.quantity == "electricity_cost"), None)
        if cost is None:
            continue
        a, b = int(energy.start[0]), int(energy.end[0])
        if any(a < t1 and b > t0 for t0, t1 in spans):
            eur += float(cost.value[0])
            kwh += float(energy.values_in("kWh")[0])
    return (eur, kwh) if eur > 0 and kwh > 0 else None


def _water_amounts(bills: list[Bill]) -> float | None:
    """€ over the water bills whose amount is known, or None."""
    eur = 0.0
    for e in SESSION.values():
        if e.status != "ok":
            continue
        for c in (x for x in e.series if x.quantity == "water_cost"):
            for a, b, v in zip(c.start, c.end, c.value, strict=True):
                if any(int(a) == x.start and int(b) == x.end for x in bills):
                    eur += float(v)
    return eur if eur > 0 else None


def _gas_amounts(bills: list[Bill]) -> tuple[float, float] | None:
    """(€, kWh) over the gas bills whose amount is known."""
    eur = kwh = 0.0
    for e in SESSION.values():
        if e.status != "ok":
            continue
        cost = [s for s in e.series if s.quantity == "gas_cost"]
        energy = [s for s in e.series if s.quantity == "gas_energy"]
        for c in cost:
            for a, b, v in zip(c.start, c.end, c.value, strict=True):
                if any(int(a) == x.start and int(b) == x.end for x in bills):
                    eur += float(v)
                    kwh += sum(
                        float(ev) / 3.6e6
                        for en in energy
                        for ea, eb, ev in zip(en.start, en.end, en.value, strict=True)
                        if int(ea) == int(a) and int(eb) == int(b)
                    )
    return (eur, kwh) if eur > 0 and kwh > 0 else None


# ------------------------------------------------------------ the next twelve months

#: What a simulation may change on top of the answers: how much insulating
#: the walls, or the walls and the windows, cuts the envelope's loss.
INSULATION_FACTOR = {"as_is": 1.0, "walls": 0.75, "walls_windows": 0.55}
_MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _seen_months(tz: str) -> set[int]:
    """The months (1-12) the fitted record covers for at least a week."""
    seen: set[int] = set()
    zone = ZoneInfo(tz)
    for p in CACHE.get("periods", []):
        t = p.start
        while t < p.end:
            d = datetime.fromtimestamp(t, zone)
            month_end = datetime(
                d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=zone
            )
            covered = min(p.end, int(month_end.timestamp())) - t
            if covered >= 7 * 86400:
                seen.add(d.month)
            t = int(month_end.timestamp())
    return seen


def forecast(
    answers: dict[str, Any],
    changes: dict[str, Any] | None = None,
    prices: dict[str, float] | None = None,
    year: int = 2026,
) -> dict[str, Any]:
    """The next twelve months of the home, month by month, on an average
    year's weather, from the fitted model.

    ``changes`` are answers to replace (another heating system, a different
    thermostat, air conditioning…) plus ``insulation`` (``as_is``, ``walls``
    or ``walls_windows``). What the fit measured is kept wherever the
    scenario keeps the same thing: the envelope (scaled by the insulation
    chosen), what the home stores, the always-on load; a heating system
    that changed takes its own typical or nameplate size. ``prices`` are
    € per kWh of electricity and gas; the bills' own by default.
    """
    if not CACHE:
        return {"ok": False, "message": "no model yet"}
    base = CACHE["desc"]
    result = CACHE["result"]
    changes = dict(changes or {})
    insulation = changes.pop("insulation", "as_is")
    if insulation not in INSULATION_FACTOR:
        raise ValueError(f"insulation must be one of {list(INSULATION_FACTOR)}")
    desc = HomeDescription.from_answers({**answers, **changes})
    twin = build_twin(
        desc, backend=BACKEND, with_heating=True, with_cooling=desc.cooling == "yes"
    )
    zone = twin.zone.name
    params = twin.model.parameters
    fitted = {**result.values, **result.given}
    overrides: dict[str, float] = {}
    for name, value in fitted.items():
        if (
            name not in params
            or name.startswith("cooling.")
            or name == "thermometer.offset"
        ):
            continue
        if name.startswith("heating.") and desc.heating != base.heating:
            continue  # another machine: its own size
        overrides[name] = float(value)
    ratio = desc.area / base.area  # a bigger home in the scenario: in proportion
    for name in list(overrides):
        if name.startswith(f"{zone}.") and ratio != 1.0:
            overrides[name] *= ratio
    key = f"{zone}.envelope.conductance"
    if key in overrides:
        overrides[key] *= INSULATION_FACTOR[insulation]
    twin.model.set_parameters(overrides)
    uncertainty = getattr(result, "uncertainty", {}) or {}
    band_overrides = [
        {
            **overrides,
            **_band_overrides({k: overrides[k] for k in overrides}, uncertainty, sign),
        }
        for sign in (-1.0, 1.0)
    ]

    start, outdoor_c = typical_year(desc.province, year)
    hours = outdoor_c.size
    sub = 2
    prefix = 14 * 24  # two weeks of January replayed before it, so the home starts warm
    full = np.concatenate([outdoor_c[:prefix], outdoor_c])
    n = full.size
    t = np.arange(n * sub + 1) * (3600.0 / sub)
    mid = (t[:-1] + t[1:]) / 2 / 3600.0
    outdoor = np.append(np.interp(mid, np.arange(n, dtype=float), full), full[-1])
    start_utc = start.astimezone(timezone.utc) - timedelta(hours=prefix)
    outs = list(twin.electric_outputs) + list(twin.gas_outputs)

    def year_of(model_twin):
        run = model_twin.simulate(t, start=start_utc, outdoor=outdoor + 273.15)
        return {
            o: run.step_mean[o].reshape(n, sub).mean(axis=1)[prefix:] / 1000.0
            for o in outs
        }

    hourly = year_of(twin)  # kWh per hour
    band_hourly = [
        year_of(replace(twin, model=twin.model.with_parameters(ov)))
        for ov in band_overrides
    ]

    gas_price = PRICES["gas"]
    elec_price = PRICES["electricity"]
    data = CACHE.get("data")
    if data is not None:
        amounts = _gas_amounts([b for b in _bills("gas") if _bill_in(data, b)])
        if amounts:
            gas_price = amounts[0] / max(amounts[1], 1.0)
        elec_amounts = _electricity_amounts(data)
        if elec_amounts:
            elec_price = elec_amounts[0] / max(elec_amounts[1], 1.0)
    if prices:
        gas_price = float(prices.get("gas", gas_price))
        elec_price = float(prices.get("electricity", elec_price))

    seen = _seen_months(desc.timezone)
    zone_tz = ZoneInfo(desc.timezone)
    stamps = [start + timedelta(hours=k) for k in range(hours)]
    month_of = np.array([s.astimezone(zone_tz).month for s in stamps])
    months = []
    for m in range(1, 13):
        sel = month_of == m
        by_output = {o: float(v[sel].sum()) for o, v in hourly.items()}
        uses = _by_use(twin, by_output)
        elec = sum(r["kwh"] for r in uses if r["fuel"] == "electricity")
        gas = sum(r["kwh"] for r in uses if r["fuel"] == "gas")
        band_eur, band_kwh = [], []
        for h in band_hourly:
            e = sum(float(h[o][sel].sum()) for o in twin.electric_outputs)
            g = sum(float(h[o][sel].sum()) for o in twin.gas_outputs)
            band_kwh.append(e + g)
            band_eur.append(e * elec_price + g * gas_price)
        months.append(
            {
                "band_eur": [round(min(band_eur)), round(max(band_eur))],
                "band_kwh": [round(min(band_kwh)), round(max(band_kwh))],
                "month": m,
                "label": MONTHS[LANG][m - 1],
                "outdoor_c": round(float(outdoor_c[sel].mean()), 1),
                "seen": m in seen,
                "electricity_kwh": round(elec),
                "gas_kwh": round(gas),
                "eur_electricity": round(elec * elec_price),
                "eur_gas": round(gas * gas_price),
                "eur": round(elec * elec_price + gas * gas_price),
                "by_use": {r["use"]: round(r["kwh"]) for r in uses},
                "conditioning_kwh": round(
                    sum(r["kwh"] for r in uses if r["use"] in ("heating", "cooling"))
                ),
            }
        )
    return {
        "ok": True,
        "months": months,
        "totals": {
            "electricity_kwh": round(sum(x["electricity_kwh"] for x in months)),
            "gas_kwh": round(sum(x["gas_kwh"] for x in months)),
            "eur": round(sum(x["eur"] for x in months)),
            "eur_electricity": round(sum(x["eur_electricity"] for x in months)),
            "eur_gas": round(sum(x["eur_gas"] for x in months)),
        },
        "prices": {"electricity": round(elec_price, 3), "gas": round(gas_price, 3)},
        "seen": sorted(seen),
        "year": year,
        "insulation": insulation,
        "heater": desc.heating,
        "cooling": desc.cooling == "yes",
    }


# ------------------------------------------------------------ the hidden-month test


def trust_test(answers: dict[str, Any]) -> dict[str, Any]:
    """Hide the last period, learn from the others, guess the hidden one."""
    desc = HomeDescription.from_answers(answers)
    try:
        _, _, _, periods, _ = _record(desc, "all")
    except (NotEnoughData, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    if len(periods) < 2:
        CACHE["trust"] = {"status": "needs_two"}
        return _trust_text()
    held = len(periods) - 1
    try:
        train, *_ = _record(desc, list(range(held)))
        test, *_ = _record(desc, held)
        twin = build_twin(desc, backend=BACKEND, with_cooling=False)
        result = calibrate(twin, train, given=_given(desc))
    except (NotEnoughData, ValueError) as exc:
        CACHE["trust"] = {"status": "error", "message": str(exc)}
        return _trust_text()
    from calibration.fit import OFFSET_BASE_K, THERMOMETER_OFFSET

    offset = result.values.get(THERMOMETER_OFFSET, OFFSET_BASE_K) - OFFSET_BASE_K
    meter = HourlyMeter(result.twin, test, substeps=auto_substeps(test), offset_k=offset)
    elec, gas, indoor = meter.readings()
    obs = test.observed
    real_e, guess_e = float(np.sum(test.electricity_kwh[obs])), float(np.sum(elec[obs]))
    trust: dict[str, Any] = {
        "status": "done",
        "t0": int(test.start.timestamp()),
        "t1": int(test.start.timestamp()) + 3600 * test.hours,
        "electricity": (round(guess_e, 0), round(real_e, 0)),
    }
    if test.gas_bills:
        real_g = float(sum(b.kwh for b in test.gas_bills))
        guess_g = float(meter.bill_totals(gas).sum())
        trust["gas"] = (round(guess_g, 0), round(real_g, 0))
    if indoor is not None and test.indoor_c is not None:
        ind = test.indoor_observed
        trust["indoor_k"] = round(
            float(np.sqrt(np.mean((indoor[ind] - test.indoor_c[ind]) ** 2))), 2
        )
    worst = max(
        abs(g / max(r, 1.0) - 1)
        for g, r in [trust["electricity"], trust.get("gas", (1, 1))]
    )
    trust["passed"] = bool(worst <= 0.1 and trust.get("indoor_k", 0.0) <= 0.6)
    CACHE["trust"] = trust
    return _trust_text()


def _trust_text() -> dict[str, Any] | None:
    trust = CACHE.get("trust")
    if not trust:
        return None
    if trust["status"] != "done":
        text = (
            _t("trust_needs_two")
            if trust["status"] == "needs_two"
            else trust.get("message", "")
        )
        return {**trust, "sentences": [text]}
    tz = CACHE["desc"].timezone if "desc" in CACHE else "Europe/Madrid"
    period = f"{_date(trust['t0'], tz)} {_t('to')} {_date(trust['t1'], tz)}"

    def off(guess: float, real: float) -> str:
        return _t("pct_off", pct=f"{abs(100 * (guess / max(real, 1.0) - 1)):.0f}")

    lines = [_t("trust_intro", period=period)]
    if "gas" in trust:
        g, r = trust["gas"]
        lines.append(_t("trust_gas", guess=_n(g), real=_n(r), off=off(g, r)))
    g, r = trust["electricity"]
    lines.append(_t("trust_elec", guess=_n(g), real=_n(r), off=off(g, r)))
    if "indoor_k" in trust:
        lines.append(_t("trust_indoor", k=_n(trust["indoor_k"], 1)))
    lines.append(_t("trust_pass" if trust["passed"] else "trust_fail"))
    return {**trust, "sentences": lines}


PUBLIC = {
    "questions": questions,
    "assumptions": assumptions,
    "read_file": read_file,
    "map_file": map_file,
    "remove_file": remove_file,
    "data_status": data_status,
    "load_samples": load_samples,
    "add_bill": add_bill,
    "read_invoice": read_invoice,
    "demo_home": demo_home,
    "forecast": forecast,
    "adopt_fit": adopt_fit,
    "prepare_example": prepare_example,
    "set_language": set_language,
    "files": files,
    "home": home,
    "cards": cards,
    "analyse": analyse,
    "report": report,
    "trust_test": trust_test,
    "forget": forget,
    "calibrate_home": calibrate_home,
    "ping": lambda: {"status": "ok", "python": sys.version.split()[0]},
}


def dispatch(func: str, payload: dict[str, Any], data: Any = None) -> dict[str, Any]:
    """Call a public function; ``data`` is a file's bytes (or a JS typed array)."""
    if func not in PUBLIC:
        raise KeyError(f"no such function: {func}")
    if data is not None:
        if hasattr(data, "to_bytes"):
            data = data.to_bytes()
        payload = {**payload, "data": bytes(data)}
    return PUBLIC[func](**payload)
