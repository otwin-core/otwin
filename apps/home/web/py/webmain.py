"""What the browser calls: the wizard's session, over plain JSON.

This module runs inside Pyodide, unpacked to ``/app`` next to ``otwin`` and
the Otwin Home packages, and is the only surface ``runtime.js`` talks to.
The page calls :func:`dispatch` with a function name, keyword arguments and,
for files, the raw bytes; everything comes back as JSON-sized dicts with
plain sentences ready to show. Files are read here, in the browser's own
memory, and kept in :data:`SESSION`; nothing is sent anywhere.

The wizard's three steps map to:

1. :func:`questions`, :func:`assumptions` — the home, by selectors only;
2. :func:`read_file`, :func:`map_file`, :func:`remove_file`,
   :func:`data_status`, :func:`load_samples` — the data, by drag and drop,
   with the column mapper for CSVs no parser knows;
3. :func:`calibrate_home` — the one-click fit and its plain-language report.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

import ingest
from calibration import HourlyData, NotEnoughData, calibrate
from ingest._table import read_table
from ingest.units import dimension_of
from survey import PROVINCES, HomeDescription, build_twin, questions_json
from survey import assumptions as _assumptions

#: The engine in the browser is the NumPy backend; tests may switch it.
BACKEND = "numpy"
#: The example files: next to this module in the bundle (/app/samples), in
#: web/samples/ when run from the repository.
_HERE = Path(__file__).resolve().parent
SAMPLES = _HERE / "samples" if (_HERE / "samples").is_dir() else _HERE.parent / "samples"

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
    "indoor_temperature": "indoor temperature",
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


SESSION: dict[str, FileEntry] = {}


# ---------------------------------------------------------------- helpers


def _day(ts: int, tz: str) -> str:
    d = datetime.fromtimestamp(int(ts), ZoneInfo(tz))
    return f"{d.day} {_MONTHS[d.month - 1][:3]} {d.year}"


def _describe_series(s, tz: str) -> str:
    what = _QUANTITIES.get(s.quantity, s.quantity)
    span = (
        f"{_day(s.start[0], tz)} to {_day(s.end[-1] - 1, tz)}"
        if len(s)
        else "no readings"
    )
    if s.kind == "interval" and s.quantity.endswith(
        ("_import", "_export", "consumption", "energy")
    ):
        total = f", {s.values_in('kWh').sum():.0f} kWh"
    elif s.quantity.endswith("_volume"):
        total = f", {s.values_in('m3').sum():.1f} m³"
    elif s.quantity.endswith("temperature"):
        v = s.values_in("degC")
        total = f", {v.min():.0f} to {v.max():.0f} °C"
    else:
        total = ""
    step = ""
    if s.kind != "instant" and len(s):
        h = float(np.median(s.end - s.start)) / 3600.0
        step = "hourly " if h == 1 else "quarter-hourly " if h == 0.25 else ""
    return f"{step}{what}, {len(s)} readings from {span}{total}"


def _summary(file_id: str, e: FileEntry, tz: str) -> dict[str, Any]:
    out: dict[str, Any] = {"id": file_id, "name": e.name, "status": e.status}
    if e.status == "ok":
        order = list(_QUANTITIES)
        ranked = sorted(
            e.series,
            key=lambda s: order.index(s.quantity) if s.quantity in order else len(order),
        )
        parts = [_describe_series(s, tz) for s in ranked]
        out["format"] = _FORMATS.get(e.format, e.format)
        out["message"] = f"Read as {out['format']}: " + "; ".join(parts) + "."
    else:
        out["message"] = e.message
    if e.mapping is not None:
        out["mapping"] = e.mapping
    return out


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
        quantity = {
            "temperature": "outdoor_temperature",
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
                    name, data, "error", message=f"This file could not be read: {exc}"
                )
            return FileEntry(
                name,
                data,
                "needs_mapping",
                message="We don't know this layout. Tell us which column is which.",
                mapping=mapping,
            )
        return FileEntry(
            name, data, "error", message=f"This file could not be read: {exc}"
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
                    name, data, "error", message=f"This file could not be read: {again}"
                )
        else:
            return FileEntry(
                name, data, "error", message=f"This file could not be read: {exc}"
            )
    return FileEntry(name, data, "ok", format=fmt, series=list(series))


# ---------------------------------------------------------------- step 1


def questions() -> dict[str, Any]:
    """The first step's questions (the same data the build bakes into the page)."""
    return questions_json()


def assumptions(answers: dict[str, Any]) -> dict[str, Any]:
    """What the twin will start from, for these answers."""
    try:
        desc = HomeDescription.from_answers(answers)
    except ValueError as exc:
        return {"ok": False, "sentences": [str(exc)]}
    return {"ok": True, "sentences": _assumptions(desc)}


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
        entry.message = f"Those columns did not work: {exc}"
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


def _best_weather():
    temps = _series_of("outdoor_temperature")
    return max(temps, key=len) if temps else None


def _window(elec, weather, desc: HomeDescription) -> tuple[int, int] | None:
    """The record to calibrate on, UTC seconds [t0, t1): the overlap, or the
    most telling 31 days of it when longer than five weeks."""
    t0 = max(int(elec.start[0]), int(np.ceil(weather.start[0] / 3600.0) * 3600))
    t1 = min(int(elec.end[-1]), int(weather.end[-1]) + 3600)
    if t1 - t0 < 24 * 3600:
        return None
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


def _record(desc: HomeDescription):
    elec, weather = _best_electricity(), _best_weather()
    if elec is None or weather is None:
        return None, elec, weather, None
    win = _window(elec, weather, desc)
    if win is None:
        return None, elec, weather, None
    tz = ZoneInfo(desc.timezone)
    start = datetime.fromtimestamp(win[0], timezone.utc).astimezone(tz)
    end = datetime.fromtimestamp(win[1], timezone.utc).astimezone(tz)
    return (
        HourlyData.from_series(
            elec, weather, start=start, end=end, timezone_name=desc.timezone
        ),
        elec,
        weather,
        win,
    )


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


def data_status(answers: dict[str, Any]) -> dict[str, Any]:
    """Is there enough to calibrate? Plain sentences either way."""
    desc = HomeDescription.from_answers(answers)
    messages: list[str] = []
    try:
        data, elec, weather, win = _record(desc)
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
        return {
            "ready": False,
            "messages": messages,
            "weather_request": _weather_request(desc, elec) if weather is None else None,
        }
    first, last = data.hour_label(0)[:10], data.hour_label(data.hours - 1)[:10]
    messages.append(
        f"Ready: {data.days:.0f} days of hourly electricity and outdoor temperature, "
        f"{first} to {last}."
    )
    if win and (int(elec.end[-1]) - int(elec.start[0])) > 35 * 86400:
        messages.append(
            "Your files cover more than a month; we use the 31 days that show "
            "your home best (the coldest, for electric heating)."
        )
    if desc.heating == "gas":
        messages.append(
            "Your heating runs on gas, so the electricity will tell us about "
            "your appliances and always-on use, not about your walls."
        )
    return {
        "ready": True,
        "messages": messages,
        "weather_request": None,
        "days": round(data.days, 1),
    }


def load_samples() -> dict[str, Any]:
    """The example home's answers and files, read as if dropped."""
    answers = json.loads((SAMPLES / "home.json").read_text())
    files = []
    for i, name in enumerate(
        ["consumo_horario_enero_2026.csv", "estacion_meteo_enero_2026.csv"]
    ):
        files.append(read_file(f"sample-{i}", name, (SAMPLES / name).read_bytes()))
    return {"answers": answers, "files": files}


# ---------------------------------------------------------------- step 3


def calibrate_home(answers: dict[str, Any]) -> dict[str, Any]:
    """Fit the home to the session's data, and the report to show."""
    t_start = time.perf_counter()
    desc = HomeDescription.from_answers(answers)
    try:
        data, _, _, _ = _record(desc)
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
        result = calibrate(twin, data)
    except NotEnoughData as exc:
        return {"ok": False, "message": str(exc)}
    tz = ZoneInfo(desc.timezone)
    t0 = data.start.astimezone(timezone.utc)
    days: dict[str, list[float]] = {}
    for k in range(data.hours):
        key = f"{(t0 + timedelta(hours=k)).astimezone(tz):%Y-%m-%d}"
        m, p = result.measured_kwh[k], result.predicted_kwh[k]
        acc = days.setdefault(key, [0.0, 0.0])
        if np.isfinite(m):
            acc[0] += float(m)
            acc[1] += float(p)
    return {
        "ok": True,
        "verdict": result.verdict,
        "headline": result.headline,
        "notes": notes,
        "findings": [
            {
                "label": f.label,
                "sentence": f.sentence,
                "verdict": f.verdict,
                "reason": f.reason,
            }
            for f in result.findings
        ],
        "hourly_error": result.hourly_error,
        "bias": result.bias,
        "period": f"{data.hour_label(0)[:10]} to {data.hour_label(data.hours - 1)[:10]}",
        "daily": [
            {"day": d, "measured": round(v[0], 3), "twin": round(v[1], 3)}
            for d, v in days.items()
        ],
        "seconds": round(time.perf_counter() - t_start, 1),
    }


# ---------------------------------------------------------------- the demo page


def run_example() -> dict[str, Any]:
    """The demo page's run: calibrate the sample month and answer five what-ifs."""
    from scenarios import (
        ElectricityTariff,
        Insulation,
        MoveAppliance,
        OutdoorShift,
        ScenarioStudy,
        SetpointChange,
        Tariff,
        TariffChange,
    )

    timings: dict[str, int] = {}
    t = time.perf_counter()
    SESSION.clear()
    answers = json.loads((SAMPLES / "home.json").read_text())
    read_file(
        "demo-elec",
        "consumo_horario_enero_2026.csv",
        (SAMPLES / "consumo_horario_enero_2026.csv").read_bytes(),
    )
    read_file(
        "demo-weather",
        "open_meteo_enero_2026.json",
        (SAMPLES / "open_meteo_enero_2026.json").read_bytes(),
    )
    timings["read_files_ms"] = round((time.perf_counter() - t) * 1000)
    t = time.perf_counter()
    desc = HomeDescription.from_answers(answers)
    data, *_ = _record(desc)
    result = calibrate(build_twin(desc, backend=BACKEND, with_cooling=False), data)
    timings["calibrate_ms"] = round((time.perf_counter() - t) * 1000)
    t = time.perf_counter()
    tariff = Tariff(
        ElectricityTariff(
            "2.0TD",
            {"P1": 0.19, "P2": 0.12, "P3": 0.08},
            power_kw=4.6,
            power_eur_per_kw_day=0.0885,
            meter_eur_per_day=0.0266,
        )
    )
    flat = Tariff(
        ElectricityTariff(
            "Tarifa Plana",
            0.135,
            power_kw=4.6,
            power_eur_per_kw_day=0.0885,
            meter_eur_per_day=0.0266,
        )
    )
    study = ScenarioStudy.from_calibration(result, data, tariff)
    runs = study.run_all(
        [
            OutdoorShift(-3.0),
            SetpointChange(-1.0),
            MoveAppliance("dishwasher", from_hours=(21,), to_hours=(2,)),
            Insulation(r_value=2.0, area_m2=40.0, envelope_area_m2=120.0),
            TariffChange(flat),
        ]
    )
    timings["scenarios_ms"] = round((time.perf_counter() - t) * 1000)
    import otwin
    import scipy

    return {
        "calibration": {
            "verdict": result.verdict,
            "headline": result.headline,
            "findings": [f.line() for f in result.findings],
        },
        "scenarios": [{"name": r.name, "sentence": r.sentence} for r in runs],
        "timings": timings,
        "versions": (
            f"Python {sys.version.split()[0]} on {sys.platform}, otwin "
            f"{otwin.__version__}, NumPy {np.__version__}, SciPy {scipy.__version__}"
            " — all inside this page."
        ),
    }


# ---------------------------------------------------------------- the bridge

PUBLIC = {
    "questions": questions,
    "assumptions": assumptions,
    "read_file": read_file,
    "map_file": map_file,
    "remove_file": remove_file,
    "data_status": data_status,
    "load_samples": load_samples,
    "calibrate_home": calibrate_home,
    "run_example": run_example,
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
