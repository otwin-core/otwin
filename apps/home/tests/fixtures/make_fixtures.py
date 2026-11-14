"""Synthetic household data files, one per format the ingest parsers read.

No real household data is used anywhere. Each fixture is generated from a
*truth*: the series a correct parser must return, built directly in UTC
here. The file is then written in the vendor's layout, with that format's
quirks: decimal comma, hour numbers 1-25, end-of-hour labels with a
summer/winter flag, Excel date serials, cumulative sums, thousands
separators in meter readings. The tests check that parsing each file gives
back its truth, and that this script reproduces the committed files byte for
byte, so nobody edits a fixture by hand.

Every electricity window includes a DST change day (30 March 2025 has 23
hours, 26 October 2025 has 25), because that is where parsers go wrong.

Regenerate with::

    python apps/home/tests/fixtures/make_fixtures.py

The CUPS and the coordinates are fictitious or public (Madrid city centre).
"""

from __future__ import annotations

import io
import json
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
APP = HERE.parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from ingest import (  # noqa: E402
    ESTIMATED,
    INSTANT,
    INTERVAL,
    MEAN,
    REAL,
    ColumnMap,
    Series,
)

TZ = ZoneInfo("Europe/Madrid")
CUPS = "ES0021000000000001AB0F"  # fictitious supply point
LAT, LON = 40.4165, -3.70256

#: Local days covered by the hourly electricity fixtures: both 2025 DST changes.
DAYS = [date(2025, 3, 29) + timedelta(days=k) for k in range(3)] + [
    date(2025, 10, 25) + timedelta(days=k) for k in range(3)
]


@dataclass
class Fixture:
    """A generated file, the series it must parse to, and the parse options."""

    name: str
    format: str  # detect_format() result, or "generic" for the column-mapper case
    data: bytes
    truth: list[Series]
    options: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- helpers


def _midnight(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=TZ).timestamp())


def _hour_starts(d: date) -> list[int]:
    """UTC starts of every hour of local day ``d`` (23, 24 or 25 of them)."""
    return list(range(_midnight(d), _midnight(d + timedelta(days=1)), 3600))


def _local(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, TZ)


def _series(quantity, channel, kind, start, end, value, quality=None, source=""):
    return Series(
        quantity=quantity,
        channel=channel,
        kind=kind,
        start=np.asarray(start, dtype=np.int64),
        end=np.asarray(end, dtype=np.int64),
        value=np.asarray(value, dtype=float),
        quality=None if quality is None else np.asarray(quality, dtype=np.int8),
        source=source,
    )


def _comma(x: float, decimals: int) -> str:
    return f"{x:.{decimals}f}".replace(".", ",")


# ---------------------------------------------------------------- electricity


@dataclass
class _Hour:
    day: date
    index: int  # 0-based elapsed hour of the local day
    start: int
    wh: int
    export_wh: int
    self_wh: int
    estimated: bool


def _hours(rng: np.random.Generator) -> list[_Hour]:
    out = []
    for d in DAYS:
        for k, s in enumerate(_hour_starts(d)):
            sunny = 10 <= _local(s).hour <= 17
            out.append(
                _Hour(
                    day=d,
                    index=k,
                    start=s,
                    wh=int(rng.integers(80, 2500)),
                    export_wh=int(rng.integers(0, 1500)) if sunny else 0,
                    self_wh=int(rng.integers(0, 800)) if sunny else 0,
                    estimated=bool(rng.random() < 0.06),
                )
            )
    return out


def _electric_truth(hours, quantity, attr, *, quality=True, only=None, source=""):
    hs = [h for h in hours if only is None or only(h)]
    return _series(
        quantity,
        CUPS,
        INTERVAL,
        [h.start for h in hs],
        [h.start + 3600 for h in hs],
        [getattr(h, attr) * 3600.0 for h in hs],
        [ESTIMATED if (quality and h.estimated) else REAL for h in hs],
        source,
    )


def cnmc_csv(hours: list[_Hour]) -> Fixture:
    """CNMC standard: hours numbered 1..n per local day, kWh with decimal comma."""
    lines = ["CUPS;Fecha;Hora;Consumo_kWh;Metodo_obtencion"]
    for h in hours:
        lines.append(
            f"{CUPS};{h.day:%d/%m/%Y};{h.index + 1};{_comma(h.wh / 1000, 3)};"
            f"{'E' if h.estimated else 'R'}"
        )
    truth = [_electric_truth(hours, "electricity_import", "wh")]
    return Fixture(
        "cnmc_consumo.csv",
        "distributor_csv",
        ("\r\n".join(lines) + "\r\n").encode(),
        truth,
    )


def edistribucion_csv(hours: list[_Hour]) -> Fixture:
    """e-distribución: import, export and self-consumption; AE_AUTOCONS blank in March."""
    lines = ["CUPS;Fecha;Hora;AE_kWh;AS_KWh;AE_AUTOCONS_kWh;REAL/ESTIMADO"]
    for h in hours:
        autocons = "" if h.day.month == 3 else _comma(h.self_wh / 1000, 3)
        lines.append(
            f"{CUPS};{h.day:%d/%m/%Y};{h.index + 1};{_comma(h.wh / 1000, 3)};"
            f"{_comma(h.export_wh / 1000, 3)};{autocons};{'E' if h.estimated else 'R'}"
        )
    truth = [
        _electric_truth(hours, "electricity_export", "export_wh"),
        _electric_truth(hours, "electricity_import", "wh"),
        _electric_truth(
            hours,
            "electricity_self_consumption",
            "self_wh",
            only=lambda h: h.day.month != 3,
        ),
    ]
    return Fixture(
        "edistribucion_curva.csv",
        "distributor_csv",
        ("\n".join(lines) + "\n").encode("utf-8"),
        truth,
    )


def ide_csv(hours: list[_Hour]) -> Fixture:
    """i-DE: Wh, end-of-hour local label, INV / VER = 1 in summer time, trailing ';'."""
    lines = ["CUPS;FECHA-HORA;INV / VER;CONSUMO Wh;GENERACION Wh;"]
    for h in hours:
        during = _local(h.start)
        offset = during.utcoffset()
        assert offset is not None
        end_label = (
            datetime.fromtimestamp(h.start + 3600, timezone.utc).replace(tzinfo=None)
            + offset
        )
        flag = 1 if during.dst() else 0
        lines.append(f"{CUPS};{end_label:%Y/%m/%d %H:%M};{flag};{h.wh};{h.export_wh};")
    truth = [
        _electric_truth(hours, "electricity_export", "export_wh", quality=False),
        _electric_truth(hours, "electricity_import", "wh", quality=False),
    ]
    return Fixture(
        "ide_consumos.csv",
        "ide_csv",
        ("\r\n".join(lines) + "\r\n").encode("latin-1"),
        truth,
    )


def datadis_json(hours: list[_Hour]) -> Fixture:
    """Datadis API/web JSON: "HH:00" labels 01..24 (25 in October), kWh floats."""
    records = []
    for h in hours:
        records.append(
            {
                "cups": CUPS,
                "date": f"{h.day:%Y/%m/%d}",
                "time": f"{h.index + 1:02d}:00",
                "consumptionKWh": round(h.wh / 1000, 3),
                "obtainMethod": "Estimada" if h.estimated else "Real",
                "surplusEnergyKWh": round(h.export_wh / 1000, 3),
            }
        )
    text = (
        "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n]\n"
    )
    truth = [
        _electric_truth(hours, "electricity_export", "export_wh"),
        _electric_truth(hours, "electricity_import", "wh"),
    ]
    return Fixture("datadis_consumo.json", "datadis_json", text.encode(), truth)


# ---------------------------------------------------------------- plugs

_SHELLY_KEYS = [
    "timestamp",
    "total_act_energy",
    "fund_act_energy",
    "total_act_ret_energy",
    "fund_act_ret_energy",
    "lag_react_energy",
    "lead_react_energy",
    "max_act_power",
    "min_act_power",
    "max_aprt_power",
    "min_aprt_power",
    "max_voltage",
    "min_voltage",
    "avg_voltage",
    "max_current",
    "min_current",
    "avg_current",
]


def shelly_csv(rng: np.random.Generator) -> Fixture:
    """Shelly EM1Data CSV, 1-minute records, device offline for 10 minutes."""
    t0 = int(datetime(2025, 10, 26, 0, 0, tzinfo=timezone.utc).timestamp())
    lines = [",".join(_SHELLY_KEYS)]
    starts, values = [], []
    for m in range(180):
        if 60 <= m < 70:
            continue  # offline
        ts = t0 + 60 * m
        mwh = int(rng.integers(0, 40_000))  # up to 2.4 kW over the minute
        wh = mwh / 1000
        p = wh * 60
        v = 228 + rng.random() * 6
        lines.append(
            ",".join(
                [
                    str(ts),
                    f"{wh:.3f}",
                    f"{wh:.3f}",
                    "0.000",
                    "0.000",
                    "0.010",
                    "0.000",
                    f"{p * 1.1:.1f}",
                    f"{p * 0.9:.1f}",
                    f"{p * 1.15:.1f}",
                    f"{p * 0.95:.1f}",
                    f"{v + 1:.1f}",
                    f"{v - 1:.1f}",
                    f"{v:.1f}",
                    f"{p / v * 1.1:.3f}",
                    f"{p / v * 0.9:.3f}",
                    f"{p / v:.3f}",
                ]
            )
        )
        starts.append(ts)
        values.append(mwh * 3.6)  # mWh -> J
    truth = [
        _series(
            "plug_energy",
            "washing_machine",
            INTERVAL,
            starts,
            [s + 60 for s in starts],
            values,
        )
    ]
    return Fixture(
        "shelly_em1data.csv",
        "shelly_csv",
        ("\n".join(lines) + "\n").encode(),
        truth,
        {"channel": "washing_machine"},
    )


_M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col(c: int) -> str:
    s = ""
    c += 1
    while c:
        c, rem = divmod(c - 1, 26)
        s = chr(65 + rem) + s
    return s


def write_xlsx(sheets: list[tuple[str, list[list[Any]]]]) -> bytes:
    """A minimal but valid .xlsx (shared strings, numeric cells), stored uncompressed
    with fixed timestamps so the bytes are reproducible."""
    shared: list[str] = []
    index: dict[str, int] = {}
    sheet_parts = []
    for _, rows in sheets:
        rows_xml = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, v in enumerate(row):
                if v is None:
                    continue
                ref = f"{_col(c)}{r}"
                if isinstance(v, str):
                    if v not in index:
                        index[v] = len(shared)
                        shared.append(v)
                    cells.append(f'<c r="{ref}" t="s"><v>{index[v]}</v></c>')
                else:
                    cells.append(f'<c r="{ref}"><v>{v!r}</v></c>')
            rows_xml.append(f'<row r="{r}">{"".join(cells)}</row>')
        sheet_parts.append(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<worksheet xmlns="{_M}"><sheetData>{"".join(rows_xml)}</sheetData></worksheet>'
        )
    n = len(sheets)
    files = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/'
            'vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            + "".join(
                f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                'ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                for i in range(n)
            )
            + '<Override PartName="/xl/sharedStrings.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{_PR}"><Relationship Id="rId1" '
            f'Type="{_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>'
        ),
        "xl/workbook.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<workbook xmlns="{_M}" xmlns:r="{_R}"><sheets>'
            + "".join(
                f'<sheet name="{escape(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                for i, (name, _) in enumerate(sheets)
            )
            + "</sheets></workbook>"
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{_PR}">'
            + "".join(
                f'<Relationship Id="rId{i + 1}" Type="{_R}/worksheet" '
                f'Target="worksheets/sheet{i + 1}.xml"/>'
                for i in range(n)
            )
            + f'<Relationship Id="rId{n + 1}" Type="{_R}/sharedStrings" '
            'Target="sharedStrings.xml"/></Relationships>'
        ),
        "xl/sharedStrings.xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<sst xmlns="{_M}" count="{len(shared)}" uniqueCount="{len(shared)}">'
            + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared)
            + "</sst>"
        ),
    }
    for i, xml in enumerate(sheet_parts):
        files[f"xl/worksheets/sheet{i + 1}.xml"] = xml
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zf.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


def _excel_serial(d: date) -> float:
    return float((d - date(1899, 12, 30)).days)


def tapo_xlsx(rng: np.random.Generator) -> Fixture:
    """Tapo app export: hourly (7 days, incl. the 25-hour day), daily (Excel
    serial dates), monthly ("yyyy/mm"), and 5-minute instantaneous power."""
    hourly: list[list[Any]] = [["Tapo P110 · Fridge"], [], ["Time", "Energy Usage (kWh)"]]
    h_start, h_val = [], []
    for k in range(7):
        d = date(2025, 10, 21) + timedelta(days=k)
        for s in _hour_starts(d):
            kwh = int(rng.integers(20, 180)) / 1000
            hourly.append([f"{_local(s):%Y/%m/%d %H:%M}", kwh])
            h_start.append(s)
            h_val.append(kwh * 3.6e6)
    daily: list[list[Any]] = [["Date", "Energy Usage (kWh)"]]
    d_start, d_end, d_val = [], [], []
    d = date(2025, 7, 28)
    while d <= date(2025, 10, 27):
        kwh = int(rng.integers(900, 2600)) / 1000
        daily.append([_excel_serial(d), kwh])
        d_start.append(_midnight(d))
        d_end.append(_midnight(d + timedelta(days=1)))
        d_val.append(kwh * 3.6e6)
        d += timedelta(days=1)
    monthly: list[list[Any]] = [["Month", "Energy Usage (kWh)"]]
    m_start, m_end, m_val = [], [], []
    for k in range(12):
        y, mo = 2024 + (10 + k) // 12, (10 + k) % 12 + 1
        ny, nmo = y + (mo == 12), mo % 12 + 1
        kwh = int(rng.integers(30_000, 75_000)) / 1000
        monthly.append([f"{y}/{mo:02d}", kwh])
        m_start.append(_midnight(date(y, mo, 1)))
        m_end.append(_midnight(date(ny, nmo, 1)))
        m_val.append(kwh * 3.6e6)
    power: list[list[Any]] = [["Time", "Power (W)"]]
    p_t, p_val = [], []
    t0 = _midnight(date(2025, 10, 27)) + 14 * 3600
    for k in range(24):
        ts = t0 + 300 * k
        w = int(rng.integers(0, 160))
        power.append([f"{_local(ts):%Y/%m/%d %H:%M:%S}", w])
        p_t.append(ts)
        p_val.append(float(w))
    data = write_xlsx(
        [("Hourly", hourly), ("Daily", daily), ("Monthly", monthly), ("Power", power)]
    )
    truth = [
        _series(
            "plug_energy", "fridge", INTERVAL, h_start, [s + 3600 for s in h_start], h_val
        ),
        _series("plug_energy", "fridge", INTERVAL, d_start, d_end, d_val),
        _series("plug_energy", "fridge", INTERVAL, m_start, m_end, m_val),
        _series("plug_power", "fridge", INSTANT, p_t, p_t, p_val),
    ]
    return Fixture("tapo_fridge.xlsx", "tapo_xlsx", data, truth, {"channel": "fridge"})


# ---------------------------------------------------------------- Home Assistant


def ha_statistics_tsv(rng: np.random.Generator) -> Fixture:
    """homeassistant-statistics export: TSV, 'dd.mm.yyyy HH:MM' local hour starts
    (02:00 twice on 26 October), an energy sum, a temperature mean and a gas
    meter in m³ that needs an explicit quantity."""
    starts = [
        s for k in range(3) for s in _hour_starts(date(2025, 10, 25) + timedelta(k))
    ]
    lines = ["statistic_id\tunit\tstart\tmin\tmax\tmean\tsum\tstate"]
    e_sum, g_sum = 1_234_000, 4_520_000  # Wh, litres
    e_rows, g_rows = [], []
    for s in starts:
        e_sum += int(rng.integers(20, 250))
        g_sum += int(rng.integers(0, 400))
        e_rows.append((s, e_sum))
        g_rows.append((s, g_sum))
    label = {s: f"{_local(s):%d.%m.%Y %H:%M}" for s in starts}
    for s, total in e_rows:
        kwh = f"{total / 1000:.3f}"
        lines.append(f"sensor.fridge_energy\tkWh\t{label[s]}\t\t\t\t{kwh}\t{kwh}")
    t_vals = []
    for s in starts:
        mean = round(20.5 + 1.5 * np.sin(s / 7200) + rng.normal(0, 0.2), 1)
        t_vals.append(mean)
        lines.append(
            f"sensor.living_room_temperature\t°C\t{label[s]}\t{mean - 0.3:.1f}\t"
            f"{mean + 0.3:.1f}\t{mean:.1f}\t\t"
        )
    for s, total in g_rows:
        m3 = f"{total / 1000:.3f}"
        lines.append(f"sensor.gas_meter\tm³\t{label[s]}\t\t\t\t{m3}\t{m3}")

    def diffs(rows, scale):
        return (
            [a[0] + 3600 for a in rows[:-1]],
            [b[0] + 3600 for b in rows[1:]],
            [(b[1] - a[1]) * scale for a, b in zip(rows, rows[1:], strict=False)],
        )

    es, ee, ev = diffs(e_rows, 3600.0)  # Wh -> J
    gs, ge, gv = diffs(g_rows, 1e-3)  # L -> m^3
    truth = [
        _series("plug_energy", "sensor.fridge_energy", INTERVAL, es, ee, ev),
        _series(
            "indoor_temperature",
            "sensor.living_room_temperature",
            MEAN,
            starts,
            [s + 3600 for s in starts],
            [v + 273.15 for v in t_vals],
        ),
        _series("gas_volume", "sensor.gas_meter", INTERVAL, gs, ge, gv),
    ]
    return Fixture(
        "ha_statistics.tsv",
        "ha_statistics",
        ("\n".join(lines) + "\n").encode(),
        truth,
        {"quantities": {"sensor.gas_meter": "gas_volume"}},
    )


def ha_history_csv() -> Fixture:
    """History panel download: raw state changes in UTC, an 'unavailable' gap and
    a counter reset on the energy sensor."""
    base = int(datetime(2025, 10, 26, 8, 0, tzinfo=timezone.utc).timestamp())
    energy = [
        (0, "10.000"),
        (1800, "10.250"),
        (2400, "unavailable"),
        (3700, "10.700"),
        (5000, "0.150"),
        (7200, "0.400"),
    ]
    temps = [(0, "19.5"), (900, "19.8"), (4000, "20.4")]

    def iso(ts: int) -> str:
        dt = datetime.fromtimestamp(ts, timezone.utc)
        return f"{dt:%Y-%m-%dT%H:%M:%S}.000Z"

    lines = ["entity_id,state,last_changed"]
    lines += [f"sensor.washer_energy,{v},{iso(base + dt)}" for dt, v in energy]
    lines += [f"sensor.bedroom_temperature,{v},{iso(base + dt)}" for dt, v in temps]
    num = [(base + dt, float(v)) for dt, v in energy if v != "unavailable"]
    e_val = [
        ((b - a) if b >= a else b) * 3.6e6
        for (_, a), (_, b) in zip(num, num[1:], strict=False)
    ]
    truth = [
        _series(
            "plug_energy",
            "sensor.washer_energy",
            INTERVAL,
            [t for t, _ in num[:-1]],
            [t for t, _ in num[1:]],
            e_val,
        ),
        _series(
            "indoor_temperature",
            "sensor.bedroom_temperature",
            INSTANT,
            [base + dt for dt, _ in temps],
            [base + dt for dt, _ in temps],
            [float(v) + 273.15 for _, v in temps],
        ),
    ]
    units = {"sensor.washer_energy": "kWh", "sensor.bedroom_temperature": "°C"}
    return Fixture(
        "ha_history.csv",
        "ha_history",
        ("\n".join(lines) + "\n").encode(),
        truth,
        {"units": units},
    )


# ---------------------------------------------------------------- bills


def gas_bills_csv() -> Fixture:
    """Two-monthly gas bills as typed from the paper: decimal comma, meter readings
    with a thousands dot, Fc and PCS per bill, one estimated reading."""
    dates = [
        date(2024, 11, 7),
        date(2025, 1, 8),
        date(2025, 3, 7),
        date(2025, 5, 8),
        date(2025, 7, 8),
        date(2025, 9, 8),
        date(2025, 11, 7),
    ]
    readings = [10412, 10655, 10870, 10951, 10983, 11010, 11080]
    pcs = [11.72, 11.68, 11.75, 11.63, 11.59, 11.66]
    kinds = ["real", "real", "estimada", "real", "real", "real"]
    fc = 0.98
    lines = [
        "inicio;fin;lectura_inicio_m3;lectura_fin_m3;tipo;fc;pcs_kwh_m3;kwh;importe_eur"
    ]
    vol, kwh_v, eur, q = [], [], [], []
    for k in range(6):
        m3 = readings[k + 1] - readings[k]
        kwh = round(m3 * fc * pcs[k])
        euros = round(8.3 * (dates[k + 1] - dates[k]).days / 30 + 0.071 * kwh, 2)
        r0, r1 = (f"{x:,}".replace(",", ".") for x in (readings[k], readings[k + 1]))
        lines.append(
            f"{dates[k]:%d/%m/%Y};{dates[k + 1]:%d/%m/%Y};{r0};{r1};{kinds[k]};"
            f"{_comma(fc, 2)};{_comma(pcs[k], 2)};{kwh};{_comma(euros, 2)}"
        )
        vol.append(float(m3))
        kwh_v.append(kwh * 3.6e6)
        eur.append(euros)
        q.append(ESTIMATED if kinds[k] == "estimada" else REAL)
    s = [_midnight(d) for d in dates[:-1]]
    e = [_midnight(d) for d in dates[1:]]
    truth = [
        _series("gas_volume", "gas", INTERVAL, s, e, vol, q),
        _series("gas_energy", "gas", INTERVAL, s, e, kwh_v, q),
        _series("gas_cost", "gas", INTERVAL, s, e, eur, q),
    ]
    return Fixture(
        "gas_bills.csv", "gas_bills", ("\n".join(lines) + "\n").encode(), truth
    )


def water_bills_csv() -> Fixture:
    """Quarterly water bills with English headers, ISO dates and a decimal point."""
    dates = [
        date(2024, 10, 1),
        date(2025, 1, 2),
        date(2025, 4, 1),
        date(2025, 7, 1),
        date(2025, 10, 1),
    ]
    readings = [523, 541, 559, 580, 598]
    amounts = [41.20, 41.20, 46.85, 41.95]
    lines = ["start;end;reading_start_m3;reading_end_m3;type;amount_eur"]
    for k in range(4):
        lines.append(
            f"{dates[k]:%Y-%m-%d};{dates[k + 1]:%Y-%m-%d};{readings[k]};{readings[k + 1]};"
            f"real;{amounts[k]:.2f}"
        )
    s = [_midnight(d) for d in dates[:-1]]
    e = [_midnight(d) for d in dates[1:]]
    vol = [float(readings[k + 1] - readings[k]) for k in range(4)]
    truth = [
        _series("water_volume", "water", INTERVAL, s, e, vol),
        _series("water_cost", "water", INTERVAL, s, e, amounts),
    ]
    return Fixture(
        "water_bills.csv", "water_bills", ("\n".join(lines) + "\n").encode(), truth
    )


# ---------------------------------------------------------------- weather


def _weather(rng: np.random.Generator, t0: int, n: int):
    times = [t0 + 3600 * k for k in range(n)]
    temps, rad = [], []
    for ts in times:
        hour = _local(ts).hour
        temps.append(
            round(14 + 6 * np.sin((hour - 9) / 24 * 2 * np.pi) + rng.normal(0, 0.5), 1)
        )
        rad.append(
            int(max(0.0, 650 * np.sin((hour - 7) / 12 * np.pi))) if 7 < hour < 19 else 0
        )
    return times, temps, rad


def open_meteo_json(rng: np.random.Generator) -> Fixture:
    """Archive API with timeformat=unixtime; one missing temperature (null)."""
    t0 = int(datetime(2025, 10, 25, 0, 0, tzinfo=timezone.utc).timestamp())
    times, temps, rad = _weather(rng, t0, 72)
    temps_out: list[float | None] = list(temps)
    temps_out[30] = None
    obj = {
        "latitude": LAT,
        "longitude": LON,
        "generationtime_ms": 0.5,
        "utc_offset_seconds": 7200,
        "timezone": "Europe/Madrid",
        "timezone_abbreviation": "GMT+2",
        "elevation": 657.0,
        "hourly_units": {
            "time": "unixtime",
            "temperature_2m": "°C",
            "shortwave_radiation": "W/m²",
        },
        "hourly": {
            "time": times,
            "temperature_2m": temps_out,
            "shortwave_radiation": rad,
        },
    }
    keep = [k for k in range(72) if k != 30]
    channel = f"{LAT},{LON}"
    truth = [
        _series(
            "outdoor_temperature",
            channel,
            INSTANT,
            [times[k] for k in keep],
            [times[k] for k in keep],
            [temps[k] + 273.15 for k in keep],
        ),
        _series(
            "solar_irradiance",
            channel,
            MEAN,
            [t - 3600 for t in times],
            times,
            [float(r) for r in rad],
        ),
    ]
    text = json.dumps(obj, ensure_ascii=False, indent=1) + "\n"
    return Fixture("open_meteo.json", "open_meteo_json", text.encode(), truth)


def open_meteo_csv(rng: np.random.Generator) -> Fixture:
    """Website CSV download, requested in GMT (so ISO times are UTC)."""
    t0 = int(datetime(2025, 3, 29, 0, 0, tzinfo=timezone.utc).timestamp())
    times, temps, rad = _weather(rng, t0, 72)
    lines = [
        "latitude,longitude,elevation,utc_offset_seconds,timezone,timezone_abbreviation",
        f"{LAT},{LON},657.0,0,GMT,GMT",
        "",
        "time,temperature_2m (°C),shortwave_radiation (W/m²)",
    ]
    for ts, t, r in zip(times, temps, rad, strict=True):
        dt = datetime.fromtimestamp(ts, timezone.utc)
        lines.append(f"{dt:%Y-%m-%dT%H:%M},{t:.1f},{r}")
    channel = f"{LAT},{LON}"
    truth = [
        _series(
            "outdoor_temperature",
            channel,
            INSTANT,
            times,
            times,
            [t + 273.15 for t in temps],
        ),
        _series(
            "solar_irradiance",
            channel,
            MEAN,
            [t - 3600 for t in times],
            times,
            [float(r) for r in rad],
        ),
    ]
    return Fixture(
        "open_meteo.csv", "open_meteo_csv", ("\n".join(lines) + "\n").encode(), truth
    )


# ---------------------------------------------------------------- generic


def generic_water_logger(rng: np.random.Generator) -> Fixture:
    """An unknown device: cumulative litres every 15 minutes in local wall-clock
    time, across the October change (02:00-02:45 written twice)."""
    t0 = _midnight(date(2025, 10, 26))
    lines = ["Fecha y hora;Lectura (L)"]
    total = 1_520_300
    stamps, totals = [], []
    for k in range(21):  # 00:00 .. 04:00 local over 5 real hours
        ts = t0 + 900 * k
        total += int(rng.integers(0, 60)) if k else 0
        lines.append(f"{_local(ts):%d/%m/%Y %H:%M};{total}")
        stamps.append(ts)
        totals.append(total)
    truth = [
        _series(
            "water_volume",
            "water_logger",
            INTERVAL,
            stamps[:-1],
            stamps[1:],
            [(b - a) / 1000 for a, b in zip(totals, totals[1:], strict=False)],
        )
    ]
    cmap = ColumnMap(
        quantity="water_volume",
        value="Lectura (L)",
        time="Fecha y hora",
        cumulative=True,
        channel="water_logger",
    )
    return Fixture(
        "generic_water_logger.csv",
        "generic",
        ("\n".join(lines) + "\n").encode(),
        truth,
        {"cmap": cmap},
    )


# ---------------------------------------------------------------- all


def build() -> list[Fixture]:
    """Every fixture, generated deterministically."""
    rng = np.random.default_rng(20251113)
    hours = _hours(rng)
    return [
        cnmc_csv(hours),
        edistribucion_csv(hours),
        ide_csv(hours),
        datadis_json(hours),
        shelly_csv(rng),
        tapo_xlsx(rng),
        ha_statistics_tsv(rng),
        ha_history_csv(),
        gas_bills_csv(),
        water_bills_csv(),
        open_meteo_json(rng),
        open_meteo_csv(rng),
        generic_water_logger(rng),
    ]


def main() -> None:
    """Write every fixture into ``data/``."""
    DATA.mkdir(exist_ok=True)
    for fx in build():
        (DATA / fx.name).write_bytes(fx.data)
        print(f"wrote {fx.name} ({len(fx.data)} bytes)")


if __name__ == "__main__":
    main()
