"""A malformed file fails, and the error names the offending column.

Each case takes a valid fixture, breaks it the way real files break (a typo
in a number, a missing column, Wh written under a kWh header, an hour that
does not exist, a bill whose kWh disagrees with m³ × Fc × PCS), and checks
that the parser refuses it with an :class:`ingest.IngestError` whose
``column`` is the one at fault and whose message says where.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest

import ingest
from fixtures.make_fixtures import DATA, ColumnMap, write_xlsx


def text(name: str) -> str:
    raw = (DATA / name).read_bytes()
    return raw.decode("latin-1" if name.startswith("ide") else "utf-8")


def sub(name: str, old: str, new: str, count: int = 1) -> bytes:
    t = text(name)
    assert old in t, f"{old!r} not in {name}"
    return t.replace(old, new, count).encode()


def line_edit(name: str, line: int, fn: Callable[[str], str]) -> bytes:
    """Apply ``fn`` to 1-based ``line`` of the fixture."""
    lines = text(name).split("\n")
    lines[line - 1] = fn(lines[line - 1])
    return "\n".join(lines).encode()


def drop_column(name: str, column: str | list[str], delimiter: str) -> bytes:
    columns = [column] if isinstance(column, str) else column
    lines = [ln for ln in text(name).replace("\r\n", "\n").split("\n") if ln]
    header = lines[0].split(delimiter)
    idx = sorted((header.index(c) for c in columns), reverse=True)
    out = []
    for ln in lines:
        cells = ln.split(delimiter)
        for i in idx:
            del cells[i]
        out.append(delimiter.join(cells))
    return ("\n".join(out) + "\n").encode()


def cell_edit(name: str, line: int, col: int, value: str, delimiter: str) -> bytes:
    """Set one cell (1-based line, 0-based column) of the fixture."""
    return line_edit(
        name,
        line,
        lambda ln: delimiter.join(
            value if i == col else c for i, c in enumerate(ln.split(delimiter))
        ),
    )


@dataclass
class Case:
    id: str
    data: Callable[[], bytes]
    column: str
    match: str
    line: int | None = None
    options: dict[str, Any] = field(default_factory=dict)
    parser: Callable[..., list[ingest.Series]] | None = None


CNMC = "cnmc_consumo.csv"
EDIS = "edistribucion_curva.csv"
IDE = "ide_consumos.csv"
DATADIS = "datadis_consumo.json"
SHELLY = "shelly_em1data.csv"
HA_STATS = "ha_statistics.tsv"
HA_HIST = "ha_history.csv"
GAS = "gas_bills.csv"
WATER = "water_bills.csv"
OM_JSON = "open_meteo.json"
OM_CSV = "open_meteo.csv"
GENERIC = "generic_water_logger.csv"
_GAS_Q = {"quantities": {"sensor.gas_meter": "gas_volume"}}
_HIST_UNITS = {
    "units": {"sensor.washer_energy": "kWh", "sensor.bedroom_temperature": "°C"}
}


def _datadis(mutate: Callable[[list[dict]], None]) -> Callable[[], bytes]:
    def make() -> bytes:
        records = json.loads((DATA / DATADIS).read_bytes())
        mutate(records)
        return json.dumps(records).encode()

    return make


def _open_meteo(mutate: Callable[[dict], None]) -> Callable[[], bytes]:
    def make() -> bytes:
        obj = json.loads((DATA / OM_JSON).read_bytes())
        mutate(obj)
        return json.dumps(obj).encode()

    return make


def _cnmc_wh() -> bytes:
    """Values in Wh under a kWh header: 0,267 kWh written as 267."""
    lines = text(CNMC).split("\r\n")
    out = [lines[0]]
    for ln in lines[1:]:
        if not ln:
            continue
        c = ln.split(";")
        c[3] = str(round(float(c[3].replace(",", ".")) * 1000))
        out.append(";".join(c))
    return ("\r\n".join(out) + "\r\n").encode()


def _gas_row(k: int, col: int, value: str) -> Callable[[], bytes]:
    def make() -> bytes:
        return line_edit(
            GAS,
            k,
            lambda ln: ";".join(
                value if i == col else c for i, c in enumerate(ln.split(";"))
            ),
        )

    return make


CASES = [
    # ---- CNMC family
    Case(
        "cnmc-bad-number",
        lambda: line_edit(
            CNMC, 14, lambda ln: ln.replace(";R", ";R").rsplit(";", 2)[0] + ";0,2x7;R"
        ),
        "Consumo_kWh",
        "not a number",
        line=14,
    ),
    Case(
        "cnmc-missing-hour-column",
        lambda: drop_column(CNMC, "Hora", ";"),
        "hora",
        "missing the hour column",
    ),
    Case(
        "cnmc-impossible-date",
        lambda: sub(CNMC, "29/03/2025", "31/02/2025"),
        "Fecha",
        "not a valid date",
        line=2,
    ),
    Case(
        "cnmc-hour-24-on-23-hour-day",
        lambda: sub(CNMC, "30/03/2025;23;", "30/03/2025;24;"),
        "Hora",
        "outside 1..23",
    ),
    Case(
        "cnmc-unknown-method",
        lambda: line_edit(CNMC, 5, lambda ln: ln[:-1] + "X"),
        "Metodo_obtencion",
        "neither a real",
        line=5,
    ),
    Case("cnmc-wh-under-kwh-header", _cnmc_wh, "Consumo_kWh", "not plausible"),
    Case(
        "cnmc-short-row",
        lambda: line_edit(CNMC, 9, lambda ln: ln.rsplit(";", 2)[0]),
        "Consumo_kWh",
        "cells but the header has",
        line=9,
    ),
    Case(
        "edis-bad-export",
        lambda: line_edit(
            EDIS,
            30,
            lambda ln: ";".join(
                "1,2,3" if i == 4 else c for i, c in enumerate(ln.split(";"))
            ),
        ),
        "AS_KWh",
        "not a number",
        line=30,
    ),
    # ---- Datadis JSON
    Case(
        "datadis-missing-consumption",
        _datadis(lambda r: r[6].pop("consumptionKWh")),
        "consumptionKWh",
        "not a number",
        line=7,
    ),
    Case(
        "datadis-bad-method",
        _datadis(lambda r: r[3].update(obtainMethod="Quizá")),
        "obtainMethod",
        "neither a real",
        line=4,
    ),
    # ---- i-DE
    Case(
        "ide-wh-declared-as-kwh",
        lambda: sub(IDE, "CONSUMO Wh", "CONSUMO kWh"),
        "CONSUMO kWh",
        "not plausible",
    ),
    Case(
        "ide-wrong-summer-flag",
        lambda: line_edit(IDE, 2, lambda ln: ln.replace(";0;", ";1;")),
        "INV / VER",
        "disagrees",
        line=2,
    ),
    Case(
        "ide-header-without-unit",
        lambda: sub(IDE, "CONSUMO Wh", "CONSUMO"),
        "CONSUMO",
        "Wh or kWh",
    ),
    # ---- Shelly
    Case(
        "shelly-no-energy-column",
        lambda: sub(SHELLY, "timestamp,total_act_energy,", "timestamp,act_energy,"),
        "total_act_energy",
        "no active-energy column",
    ),
    Case(
        "shelly-bad-timestamp",
        lambda: line_edit(SHELLY, 3, lambda ln: "17x" + ln[3:]),
        "timestamp",
        "not a unix timestamp",
        line=3,
    ),
    Case(
        "shelly-bad-energy",
        lambda: line_edit(
            SHELLY,
            4,
            lambda ln: ",".join(
                "abc" if i == 1 else c for i, c in enumerate(ln.split(","))
            ),
        ),
        "total_act_energy",
        "not a number",
        line=4,
    ),
    # ---- Home Assistant
    Case(
        "ha-sum-goes-down",
        lambda: cell_edit(HA_STATS, 10, 6, "1000.000", "\t"),
        "sum",
        "cannot be negative",
        line=10,
        options=_GAS_Q,
    ),
    Case(
        "ha-volume-without-quantity",
        lambda: (DATA / HA_STATS).read_bytes(),
        "unit",
        "gas_volume",
    ),
    Case(
        "ha-unknown-unit",
        lambda: sub(HA_STATS, "\tkWh\t", "\tkWhh\t", -1),
        "unit",
        "unknown unit",
        options=_GAS_Q,
    ),
    Case(
        "ha-history-no-unit-given",
        lambda: (DATA / HA_HIST).read_bytes(),
        "entity_id",
        "no unit given",
        options={"units": {"sensor.washer_energy": "kWh"}},
    ),
    Case(
        "ha-history-bad-state",
        lambda: sub(HA_HIST, "10.250", "10.25O"),
        "state",
        "not a number",
        line=3,
        options=_HIST_UNITS,
    ),
    # ---- bills
    Case("gas-kwh-disagrees", _gas_row(3, 7, "9999"), "kwh", "m³ × Fc × PCS", line=3),
    Case("gas-pcs-in-mj", _gas_row(2, 6, "42,1"), "pcs_kwh_m3", "MJ/m³", line=2),
    Case(
        "gas-reading-chain-broken",
        _gas_row(4, 2, "10.871"),
        "lectura_inicio_m3",
        "previous bill's end reading",
        line=4,
    ),
    Case(
        "gas-overlapping-bill", _gas_row(3, 0, "01/12/2024"), "inicio", "overlaps", line=3
    ),
    Case(
        "gas-unknown-reading-type",
        _gas_row(5, 4, "aproximada"),
        "tipo",
        "neither real nor estimada",
        line=5,
    ),
    Case(
        "gas-no-energy-at-all",
        lambda: drop_column(GAS, "kwh", ";").replace(b";0,98;", b";;"),
        "fc",
        "no kWh and no Fc",
    ),
    Case(
        "water-reading-goes-back",
        lambda: sub(WATER, ";541;559;", ";541;530;"),
        "reading_end_m3",
        "below the start reading",
        line=3,
    ),
    Case(
        "water-end-before-start",
        lambda: sub(WATER, "2025-01-02;2025-04-01", "2025-01-02;2024-12-01"),
        "end",
        "ends on",
        line=3,
    ),
    Case(
        "water-missing-volume",
        lambda: drop_column(WATER, ["reading_start_m3", "reading_end_m3"], ";"),
        "m3",
        "missing the volume",
    ),
    # ---- Open-Meteo
    Case(
        "meteo-local-iso-times",
        _open_meteo(
            lambda o: o["hourly"].update(
                time=[f"2025-10-25T{h:02d}:00" for h in range(24)] * 3
            )
        ),
        "hourly.time",
        "timeformat=unixtime",
        line=1,
    ),
    Case(
        "meteo-celsius-declared-kelvin",
        _open_meteo(lambda o: o["hourly_units"].update(temperature_2m="K")),
        "hourly.temperature_2m",
        "outside the plausible range",
    ),
    Case(
        "meteo-no-units",
        _open_meteo(lambda o: o.pop("hourly_units")),
        "hourly_units.temperature_2m",
        "no unit",
    ),
    Case(
        "meteo-length-mismatch",
        _open_meteo(lambda o: o["hourly"]["shortwave_radiation"].pop()),
        "hourly.shortwave_radiation",
        "values for 72 times",
    ),
    Case(
        "meteo-csv-no-unit",
        lambda: sub(OM_CSV, "temperature_2m (°C)", "temperature_2m"),
        "temperature_2m",
        "does not give a unit",
    ),
    Case(
        "meteo-csv-bad-value",
        lambda: line_edit(OM_CSV, 8, lambda ln: ln.replace(",", ",x", 1)),
        "temperature_2m (°C)",
        "not a number",
        line=8,
    ),
]


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_malformed_file_names_the_column(case: Case) -> None:
    data = case.data()
    with pytest.raises(ingest.IngestError) as err:
        if case.parser is not None:
            case.parser(data, source="bad", **case.options)
        else:
            ingest.load(data, source="bad", **case.options)
    e = err.value
    assert e.column == case.column, str(e)
    assert f"column '{case.column}'" in str(e)
    assert case.match in str(e), str(e)
    assert str(e).startswith("bad"), str(e)  # the file is named first
    if case.line is not None:
        assert e.line == case.line, str(e)


# ---------------------------------------------------------------- generic mapper

_CMAP = ColumnMap(
    quantity="water_volume",
    value="Lectura (L)",
    time="Fecha y hora",
    cumulative=True,
    channel="water_logger",
)


@pytest.mark.parametrize(
    "data, cmap, column, match",
    [
        (
            lambda: cell_edit(GENERIC, 6, 1, "1520000", ";"),
            _CMAP,
            "Lectura (L)",
            "went down from",
        ),
        (
            lambda: (DATA / GENERIC).read_bytes(),
            ColumnMap(
                quantity="electricity_import",
                value="Lectura (L)",
                time="Fecha y hora",
                cumulative=True,
            ),
            "Lectura (L)",
            "measured in energy",
        ),
        (
            lambda: (DATA / GENERIC).read_bytes(),
            ColumnMap(quantity="water_volume", value="Lectura", time="Fecha y hora"),
            "Lectura",
            "not in the file",
        ),
        (
            lambda: sub(GENERIC, "Lectura (L)", "Lectura"),
            ColumnMap(
                quantity="water_volume",
                value="Lectura",
                time="Fecha y hora",
                cumulative=True,
            ),
            "Lectura",
            "pass unit=",
        ),
        (
            lambda: line_edit(GENERIC, 6, lambda ln: "32/10/2025" + ln[10:]),
            _CMAP,
            "Fecha y hora",
            "not a valid date",
        ),
        (
            lambda: (DATA / GENERIC).read_bytes(),
            ColumnMap(
                quantity="water_volume",
                value="Lectura (L)",
                time="Fecha y hora",
                unit="parsecs",
                cumulative=True,
            ),
            "Lectura (L)",
            "unknown unit",
        ),
    ],
    ids=[
        "reading-goes-down",
        "wrong-dimension",
        "missing-column",
        "no-unit",
        "bad-time",
        "unknown-unit",
    ],
)
def test_generic_mapper_names_the_column(data, cmap, column, match) -> None:
    with pytest.raises(ingest.IngestError) as err:
        ingest.parse_mapped(data(), cmap, source="logger.csv")
    assert err.value.column == column, str(err.value)
    assert match in str(err.value), str(err.value)


# ---------------------------------------------------------------- Tapo workbook


def _tapo(rows) -> bytes:
    return write_xlsx([("Hourly", [["Time", "Energy Usage (kWh)"], *rows])])


@pytest.mark.parametrize(
    "rows, column, match, line",
    [
        (
            [["2025/10/21 00:00", 0.1], ["2025/10/21 01:00", "n/a"]],
            "Energy Usage (kWh)",
            "not a number",
            3,
        ),
        (
            [["2025/03/30 01:00", 0.1], ["2025/03/30 02:00", 0.1]],
            "Time",
            "never happened",
            3,
        ),
        (
            [["2025/10/21 00:00", 0.1], ["21 Oct 2025 01:00", 0.1]],
            "Time",
            "not a date",
            3,
        ),
        ([["2025/10/21 00:00", 0.1], ["2025/10/22", 0.1]], "Time", "labelled by date", 3),
        ([["2025/10/21 00:00", 9.9]], "Energy Usage (kWh)", "", 2),  # valid: control
    ],
    ids=["bad-value", "skipped-hour", "unreadable-time", "mixed-resolution", "control"],
)
def test_tapo_errors_name_the_column(rows, column, match, line) -> None:
    data = _tapo(rows)
    if not match:
        [s] = ingest.parse_tapo_xlsx(data, source="tapo.xlsx")
        assert len(s) == 1
        return
    with pytest.raises(ingest.IngestError) as err:
        ingest.parse_tapo_xlsx(data, source="tapo.xlsx")
    e = err.value
    assert e.column == column and e.line == line, str(e)
    assert match in str(e) and "tapo.xlsx#Hourly: row" in str(e), str(e)


def test_unrecognised_csv_lists_its_columns() -> None:
    with pytest.raises(ingest.IngestError) as err:
        ingest.load(b"Dia;Litros\n01/01/2025;12\n", source="x.csv")
    assert "['Dia', 'Litros']" in str(err.value) and "ColumnMap" in str(err.value)
    assert str(err.value).startswith("x.csv")


def test_corrupt_workbook_is_refused() -> None:
    with pytest.raises(ingest.IngestError, match="zip"):
        ingest.parse_tapo_xlsx(b"PK\x03\x04 not really a zip", source="t.xlsx")
